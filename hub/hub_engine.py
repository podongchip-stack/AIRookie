"""GPS+병원 정보로 먼저 존 기반 후보 리스트를 만들어두고, voice 정보가 도착하면
이를 반영해 재처리하는 2단계 매칭 엔진. CLAUDE.md "feature/hub 담당자 참고사항" 참고.

모델/API 호출부(SpecialtyMatcher)와 비즈니스 로직(존 분류, 스코어링)을 분리해뒀기
때문에, 나중에 매칭 모델을 바꿔도 이 엔진의 흐름은 바뀌지 않는다.

스레드 안전(2026-09-28): app.py는 대시보드 소켓마다 스레드를 쓰고, 매칭은 별도 작업
스레드에서 돈다. 사건·병원 상태는 전부 `self._lock`(RLock) 안에서만 읽고 쓴다. 다만
임베딩 계산과 카카오 호출은 수 초가 걸릴 수 있어 락 **밖**에서 하고(그동안 승인 액션이
막히지 않게), 결과를 조립·저장하는 순간에만 다시 락을 잡는다.
"""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import bed_reliability
import decision_log
from geo import active_zones, haversine_km, should_expand_zone, zone_of
from schema import (
    AmbulanceInfo,
    ApprovalAction,
    GpsPoint,
    HospitalInfo,
    HospitalMatch,
    HospitalStatus,
    HubMatchResult,
    PatientInfo,
    ReliabilityInfo,
    SevereFreshness,
    SpecialtyMatch,
    VoiceCallSummaryMessage,
)
from scoring import calibrate_min_per_km, expertise_bonus_min, final_score, rank_key
from specialty_matcher import SpecialtyMatcher

if TYPE_CHECKING:
    from routing import KakaoRouting

# 병상 차감을 지속시키는 방식(2026-08-13 변경). 예전엔 hub가 깎은 값을
# feature/info의 Supabase에 써서 다음 재조회 때도 유지시켰는데, info가 이제
# Supabase 없이 E-Gen 실 API만 쓰면서(조회 전용이라 쓰기 자체가 불가능) 그
# 경로가 사라졌다. 대신 hub가 짧은 시간만 자기 메모리에 차감분을 얹어 보여주는
# TTL 오버레이로 대체한다 — 그 시간이 지나면 E-Gen 자신이 갱신한 진짜 값을
# 그대로 믿는다. 15분은 hvidate 갱신 간격 실측(중앙값 5분, 88.7%가 10분
# 이내)에서 여유를 둔 값이다.
BED_OVERLAY_TTL_MIN = 15

# 이송이 확정(final_approval)된 사건을 인메모리 캐시에 얼마나 더 들고 있을지.
# hub는 상시 정리 스레드가 없는 순수 요청-응답 구조라, 사건별 dict
# (_case_results 등)가 프로세스가 사는 동안 무한히 쌓인다. 확정된 사건은
# 이송이 끝난 것이므로, 뒤늦게 연결되는 대시보드 탭의 따라잡기(_send_catchup)에
# 필요한 잠깐만 남겨두고 이 시간이 지나면 조회 시점에 걷어낸다. 진행 중이거나
# 아직 확정 전인 사건은 절대 지우지 않는다.
CASE_RETENTION_MIN = 60

# 병상 값이 이보다 오래 갱신되지 않았으면 "오래된 값"으로 본다. info hospital_score의
# STALE_THRESHOLD(1일)와 같은 기준 — assessment가 없는 병원도 hub가 updatedAt으로 직접
# 판정할 수 있게 값을 복사해 둔다(브랜치 폴더 원칙상 info/를 import할 수 없다).
BED_DATA_STALE_AFTER = timedelta(days=1)

# hub 재시작 뒤 디스크에서 복구한 사건에는 통화 원문이 없다 — 개인정보가 섞일 수 있는
# 자유 텍스트라 상태 파일에 저장하지 않는다(decision_log에서 지문으로 치환하는 것과 같은
# 원칙). 원본은 feature/voice 로컬 파일에 보존된다.
TRANSCRIPT_NOT_PERSISTED = (
    "(hub 재시작으로 복구된 사건 — 통화 원문은 hub에 저장하지 않아 표시할 수 없음. "
    "원본은 feature/voice 로컬 파일에 보존)"
)

STATE_VERSION = 1


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _redact_transcript(payload: dict) -> dict:
    """decision_log에 남길 hub_match_result 사본에서 통화 전문(raw/filtered)을
    지문(sha256 + 글자 수)으로 치환한다.

    decision_log는 위변조 방지 append-only 파일이라 한 번 쓰면 지우지 않는데,
    통화 전문(개인정보가 섞일 수 있는 자유 텍스트)의 원본은 이미 feature/voice의
    로컬 파일(data/voice_data/summary_text/*.json)에 보존된다. "어떤 환자
    정보로 어떤 병원 순위가 나왔는지"의 감사는 구조화 필드(severity·mechanism·
    symptoms·병원 순위)로 충분하고, 지문이 남아 voice 원본과 대조도 된다.
    dashboard로 나가는 HubMatchResult 자체는 이 함수를 거치지 않으므로 통화
    전문 표시 기능은 그대로다.
    """
    patient = payload.get("patientInfo")
    if not isinstance(patient, dict):
        return payload
    for key in ("rawTranscript", "filteredTranscript"):
        text = patient.get(key)
        if isinstance(text, str):
            patient[key] = {
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "chars": len(text),
            }
    return payload


# dashboard의 ApprovalAction.action -> 매칭 결과에 반영할 상태.
# hospital_approve/hospital_reject는 "병원의 승인은 후보 등록일 뿐"(CLAUDE.md)이라
# 상태만 바뀌고 병상은 안 줄어든다. final_approval(구급대원의 이송 승인)만 실제
# 확정이라 병상을 차감한다(TTL 오버레이).
_ACTION_TO_STATUS: dict[str, HospitalStatus] = {
    "hospital_approve": "approved",
    "hospital_reject": "rejected",
    "final_approval": "confirmed",
}

# 액션마다 보낼 수 있는 주체(2026-09-28). 병원 승인·거절은 병원만, 이송 승인은 구급대원만.
# dashboard는 이미 이 짝으로만 보낸다(병원 화면 role="hospital", 구급차 화면 이송 승인) —
# 여기서는 짝이 어긋난 요청(조작·버그)을 막는 방어선이다.
_ACTION_ACTOR: dict[str, str] = {
    "hospital_approve": "hospital",
    "hospital_reject": "hospital",
    "final_approval": "paramedic",
}


# feature/info는 성인 응급실 병상 수를 bedsByType["ER_ADULT"]로 보내고, 미상이면
# 그 키 자체를 넣지 않는다 (availableBedCount에는 보수적으로 0이 들어간다).
_ER_ADULT = "ER_ADULT"


def _is_bed_count_unknown(info: HospitalInfo) -> bool:
    """병상 수가 "확인된 만실"이 아니라 "미상"인지 판정한다.

    이 구분을 살리지 않으면 미상인 병원이 대시보드에 "병상 0"으로 떠서, 시스템이
    후보에서 빼지 않아도 구급대원이 보고 스스로 뺀다 — 뺑뺑이를 줄이려는 목적과
    정반대 결과가 된다.
    """
    if info.availableBedCount > 0:
        return False
    return info.bedsByType is None or _ER_ADULT not in info.bedsByType


def _is_bed_data_stale(info: HospitalInfo, now: datetime) -> bool:
    """병상 값이 오래됐거나(마지막 갱신 1일 초과) 실시간 피드에 아예 없는지.

    info의 assessment가 이미 판정해 보내주는 `conditions.stale`·`missingFromFeed`를
    우선 쓰고, assessment가 없는 병원은 updatedAt(E-Gen hvidate)으로 직접 판정한다.
    E-Gen 전국 가용병상 1위가 2,457일 묵은 값이었던 사례가 있어(CLAUDE.md), 이런 병원의
    "병상 0"을 확인된 만실로 믿고 순위를 내리면 안 된다.
    """
    if info.assessment is not None:
        conditions = info.assessment.conditions
        if conditions.stale or conditions.missingFromFeed:
            return True
    updated = _parse_iso(info.updatedAt)
    return updated is not None and now - updated > BED_DATA_STALE_AFTER


# info-v2(hospital_score.vocabulary.GROUPS)의 15개 중증질환군 이름. **폴백 전용**이다
# (2026-10-01) — 실제 매칭 어휘는 info가 보낸 병원들의 assessment.groups 키에서 만든다
# (_assessment_vocabulary). 예전엔 이 목록만 써서, info 쪽 어휘가 바뀌면 hub의 질환군 매칭이
# 조용히 어긋났다. assessment를 가진 병원이 하나도 없을 때(구 feature/info 데이터)만 쓴다.
_ASSESSMENT_GROUPS = [
    "재관류중재술",
    "뇌출혈수술",
    "대동맥응급",
    "담낭담관질환",
    "복부응급수술",
    "장중첩/폐색",
    "응급내시경",
    "저체중출생아",
    "산부인과응급",
    "중증화상",
    "사지접합",
    "응급투석",
    "정신과적응급",
    "안과적수술",
    "영상의학혈관중재",
]


def _assessment_vocabulary(infos: list[HospitalInfo]) -> list[str]:
    """이번 후보들의 assessment에 실제로 있는 질환군 이름들(정렬). 없으면 폴백 목록."""
    groups = {g for info in infos if info.assessment is not None for g in info.assessment.groups}
    return sorted(groups) if groups else _ASSESSMENT_GROUPS


def _reliability_for(info: HospitalInfo, group: str) -> ReliabilityInfo | None:
    """이 병원의 assessment(info-v2 신뢰도 진단)에서 group에 해당하는 판정을
    꺼내 dashboard 설명용 ReliabilityInfo로 옮긴다.

    finalScore 값 자체의 계산식(진료과 임베딩 가중합)에는 관여하지 않는다 —
    이건 "왜 이 순위인지"를 dashboard에 보여주기 위한 설명 필드다. 다만
    같은 판정이 순위의 "정렬 순서"에는 영향을 준다(`_should_demote()` 참고,
    finalScore를 건드리지 않는 별도 경로). assessment 자체가 없는 병원
    (심평원 미연동 구 데이터)이나 그 질환군 판정이 없으면 None을 돌려주고,
    dashboard는 이 경우 설명 섹션을 안 보여주면 된다.
    """
    if info.assessment is None:
        return None
    group_score = info.assessment.groups.get(group)
    if group_score is None:
        return None
    return ReliabilityInfo(
        group=group,
        score=group_score.score,
        confidence=group_score.confidence,
        basis=group_score.basis,
    )


#: 중증질환 수용가능 신고의 통상 만료 규칙(초). feature/info의 실측(스냅샷
#: 47일)에서 Y 신고가 정보미제공으로 꺼지는 수명의 60.1%가 정확히 9.0시간에
#: 몰려 있었다 — 시스템 자동 만료로 해석되는 규칙이라 모델이 아닌 상수로
#: 둔다(재현: info의 `python -m reliability.probe_severe`).
SEVERE_EXPIRY_RULE_SEC = 9 * 3600


def _severe_freshness_for(info: HospitalInfo, group: str | None) -> SevereFreshness | None:
    """매칭된 질환군의 수용가능 신고 신선도 — 신고 나이와 9시간 만료 규칙
    기준 잔여를 매칭 시점에 계산한다. 순위에는 관여하지 않는 설명용이고,
    신고가 없거나(정보미제공) 구 feature/info 데이터면 None이다."""
    if info.severeDeclarations is None or group is None:
        return None
    declaration = info.severeDeclarations.groups.get(group)
    if declaration is None:
        return None
    born = datetime.fromisoformat(declaration.bornAt.replace("Z", "+00:00"))
    if born.tzinfo is None:
        born = born.replace(tzinfo=timezone.utc)
    age = max((datetime.now(timezone.utc) - born).total_seconds(), 0.0)
    return SevereFreshness(
        group=group,
        value=declaration.value,
        ageSec=round(age, 1),
        ageIsMin=declaration.ageIsMin,
        ruleRemainingSec=round(max(SEVERE_EXPIRY_RULE_SEC - age, 0.0), 1),
    )


def _should_demote(info: HospitalInfo, group: str | None) -> bool:
    """assessment의 관련 질환군이 `declared_no`(병원이 명시적으로 "수용 불가"라고
    신고)인지. 가중합으로 섞지 않고 순서로만 내리는 이유는 scoring.rank_key() 참고.
    거절 로그가 쌓여 실측 기반 가중치를 낼 수 있게 되면 가중합으로 승격하는 걸 재검토한다.
    """
    if info.assessment is None or group is None:
        return False
    group_score = info.assessment.groups.get(group)
    return group_score is not None and group_score.tier == "declared_no"


def _demote_reasons(
    info: HospitalInfo,
    group: str | None,
    status: HospitalStatus,
    effective_beds: int,
    bed_unknown: bool,
    bed_stale: bool,
) -> list[str]:
    """이 병원을 순위 뒤쪽으로 내릴 이유들(2026-09-28). 비면 finalScore 순서 그대로다.

    - 이 사건에 대해 병원이 거절했으면 rejected 하나로 맨 뒤.
    - 병원이 이 사건에 승인·확정 응답을 했으면 내리지 않는다 — 그 병원의 명시적 응답이
      미리 해둔 신고(declared_no)나 병상 숫자보다 우선이다. 특히 확정 직후 오버레이로 병상이
      0이 된 병원이 자기 사건에서 만실로 밀려나면 안 된다.
    - beds_full은 "확인된 만실"일 때만. 미상·오래된 값은 순위를 막지 않는다(미상을 이유로
      밀어내면 뺑뺑이가 오히려 늘어난다는 기존 원칙).
    """
    if status == "rejected":
        return ["rejected"]
    if status in ("approved", "confirmed"):
        return []
    reasons = []
    if _should_demote(info, group):
        reasons.append("declared_no")
    if not bed_unknown and not bed_stale and effective_beds <= 0:
        reasons.append("beds_full")
    return reasons


def _sort_matches(matches: list[HospitalMatch]) -> list[HospitalMatch]:
    return sorted(
        matches,
        key=lambda m: rank_key(m.finalScore or 0.0, m.distanceKm, m.hospitalId, m.demoteReasons, m.status),
    )


def _ceil_minutes(seconds: int) -> int:
    """초를 분으로 올림한다 — 도착 시간은 짧게 보여주는 쪽이 더 위험하다."""
    return max(1, -(-seconds // 60))


def _display_signature(result: HubMatchResult | None) -> tuple | None:
    """대시보드에 다시 보낼 만큼 달라졌는지 비교하는 값. 병상 신뢰도는 시간이 지나면서
    계속 조금씩 떨어지므로 소수 둘째 자리까지만 본다."""
    if result is None:
        return None
    return (
        tuple(result.zoneActive),
        tuple(
            (
                h.hospitalId,
                h.status,
                h.availableBedCount,
                h.bedCountUnknown,
                h.bedDataStale,
                h.etaMin,
                tuple(h.demoteReasons),
                round(h.bedReliability.authority, 2) if h.bedReliability else None,
                round(h.bedReliability.rArrive, 2) if h.bedReliability else None,
            )
            for h in result.hospitals
        ),
    )


def _decision_signature(result: HubMatchResult | None) -> tuple | None:
    """의사결정 로그에 새로 남길 만큼 달라졌는지 — 순위·상태·병상처럼 판단에 쓰이는 값만
    본다(병상 신뢰도의 자연 감소까지 매번 남기면 로그가 불어난다)."""
    if result is None:
        return None
    return (
        tuple(result.zoneActive),
        tuple(
            (h.hospitalId, h.status, h.availableBedCount, h.bedCountUnknown, tuple(h.demoteReasons))
            for h in result.hospitals
        ),
    )


def _voice_without_transcript(voice: VoiceCallSummaryMessage) -> dict:
    data = voice.model_dump()
    data["transcript"]["raw_text"] = TRANSCRIPT_NOT_PERSISTED
    data["transcript"]["filtered_text"] = TRANSCRIPT_NOT_PERSISTED
    return data


def _result_without_transcript(result: HubMatchResult) -> dict:
    data = result.model_dump()
    data["patientInfo"]["rawTranscript"] = TRANSCRIPT_NOT_PERSISTED
    data["patientInfo"]["filteredTranscript"] = TRANSCRIPT_NOT_PERSISTED
    return data


class HubEngine:
    def __init__(
        self,
        specialty_matcher: SpecialtyMatcher | None = None,
        router: "KakaoRouting | None" = None,
    ) -> None:
        # 사건·병원 상태 전체를 지키는 락. 재진입 가능해야 한다(maybe_expand_zone →
        # process_voice_summary처럼 메서드끼리 부르는 경로가 있다).
        self._lock = threading.RLock()
        # SpecialtyMatcher의 임베딩 캐시는 스레드 안전하지 않다. 매칭 계산은 상태 락 밖에서
        # 하므로 별도 락으로 보호한다.
        self._matcher_lock = threading.Lock()
        self._hospitals: dict[str, HospitalInfo] = {}
        self._matcher = specialty_matcher or SpecialtyMatcher()
        # 도로 기준 ETA 조회기(routing.py, 카카오모빌리티). None이면 ETA 없이 직선거리 추정만
        # 쓴다 — 테스트(run_match.py)와 키 없는 환경은 이 경로다.
        self._router = router
        # dashboard가 보낸 승인 액션 결과. 여러 사건이 동시에 진행될 수 있어
        # (caseId, hospitalId) 조합을 키로 쓴다 — hospitalId만 쓰면 서로 다른
        # 사건이 같은 병원을 후보로 둘 때 승인 상태가 섞인다.
        self._approval_status: dict[tuple[str, str], HospitalStatus] = {}
        # 구급차 레지스트리(feature/info가 Supabase ambulances 테이블에서
        # 읽어 보내줌). GPS·voicePort 조회에 쓴다.
        self._ambulances: dict[str, AmbulanceInfo] = {}
        # 출동 시뮬레이션이 얹는 현재 위치(apid -> GPS, 2026-10-01). _ambulances의 GPS는 Supabase
        # 등록값(= 기지)으로 그대로 두고, 조회할 때만 이 값으로 바꿔 보여준다 — info의 30분 재전송이
        # 시뮬레이션 위치를 덮어쓰지 않고, 시뮬레이션을 끄면 바로 등록값으로 돌아간다. 저장하지 않는다.
        self._gps_override: dict[str, GpsPoint] = {}
        # 통화 시작 시점에 dashboard가 보낸 (caseId -> apid) 매핑. 나중에
        # /voice/summary가 도착하면 voice.caseId로 이 apid를 찾아 그 구급차의
        # GPS를 조회하는 데 쓴다 — VoiceCallSummaryMessage엔 apid가 없다
        # (voice는 caseId만 그대로 돌려주면 되게 설계했다).
        self._case_apid: dict[str, str] = {}
        # 사건별 최신 매칭 결과 캐시. 승인 액션이 들어왔을 때 재계산 없이
        # 해당 병원의 status만 패치해서 dashboard에 재브로드캐스트하는 데 쓴다.
        self._case_results: dict[str, HubMatchResult] = {}
        # 사건별 현재 max_zone. 존 확장(reject_ratio 기반)이 어디까지 넓혔는지
        # 기억해둔다 — 다음 승인 액션이 왔을 때 "지금 어느 zone에서 시작해야
        # 하는지"의 기준점이 된다.
        self._case_max_zone: dict[str, int] = {}
        # 사건별 마지막 VoiceCallSummaryMessage. 존 확장·주기적 재계산 때 같은 환자
        # 정보로 매칭을 다시 계산해야 하는데, 그 시점엔 voice 데이터가 다시 오지
        # 않는다 — 그래서 마지막 값을 들고 있다가 재사용한다.
        self._case_voice: dict[str, VoiceCallSummaryMessage] = {}
        # 사건별로 고른 중증질환군(15개 중 하나). 승인 액션 뒤 재정렬할 때 declared_no
        # 판정을 다시 해야 해서 기억해 둔다.
        self._case_group: dict[str, str | None] = {}
        # 사건별로 구급차 좌표가 기본 좌표로 대체됐는지. 재계산 결과에도 같은 표시를 싣는다.
        self._case_gps_fallback: dict[str, bool] = {}
        # (caseId, hospitalId) -> 그 확정이 얹은 병상 차감의 만료 시각. 이송 병원을 다시
        # 고르면 이전 병원의 차감을 이것으로 찾아 회수한다(2026-09-28).
        self._case_overlay: dict[tuple[str, str], datetime] = {}
        # hospitalId -> 아직 유효한 차감 만료 시각 목록. final_approval마다 하나씩
        # 추가되고, effective_bed_count()가 조회 시점에 만료분을 걸러낸다.
        self._bed_overlay: dict[str, list[datetime]] = {}
        # caseId -> 이송이 확정된 시각(UTC). 위 dict들과 달리 이건 정리용이다 —
        # process_voice_summary()/apply_approval_action() 진입 때마다 여기서
        # CASE_RETENTION_MIN이 지난 사건을 골라 모든 사건 dict에서 걷어낸다
        # (_prune_old_cases). _bed_overlay와 같은 "조회 시점 lazy 정리" 패턴이다.
        self._case_confirmed_at: dict[str, datetime] = {}
        # hospitalId -> 병원 대시보드가 "현재 정보 확인"을 누른 시각(2026-09-29).
        # infosurv의 조건부 생존 갱신 S(a)/S(u)에 쓰는 유효 확인 이력 —
        # E-Gen 자기 신고 바깥에서 처음 생기는 관측이다. 값이 바뀌면(새 claim
        # 탄생) 자동으로 무효가 된다: bed_reliability.evaluate()가 확인 시각이
        # 현재 bornAt보다 뒤일 때만 적용하기 때문.
        self._info_confirmations: dict[str, datetime] = {}
        # 디스크 저장(app.py 백그라운드)이 필요한 변경이 있었는지.
        self._dirty = False

    # ── 레지스트리 ────────────────────────────────────────────────────────────

    def update_hospital_info(self, info: HospitalInfo) -> None:
        """feature/info로부터 받은 병원 정보를 hospitalId 기준으로 upsert한다.

        병상 차감이 TTL 오버레이(읽는 시점에 얹는 방식)라, info가 보내주는 값은 매번
        최신 E-Gen 원본 그대로 덮어써도 된다.
        """
        with self._lock:
            self._hospitals[info.hospitalId] = info
            self._dirty = True

    def apply_hospital_roster(self, hospital_ids: list[str]) -> tuple[list[str], list[str]]:
        """info가 한 주기에 보낸 전체 병원 목록에 없는 병원을 뺀다(2026-10-01).

        - 진행 중인 사건의 후보에 있는 병원은 이번엔 남긴다(이송 중 확정 병원이 사라지면 안 된다).
          사건이 끝난 뒤 다음 주기에 빠진다.
        - 목록이 지금 아는 병원의 절반도 안 되면 E-Gen 조회가 일부만 성공한 것으로 보고 아무것도
          안 뺀다(부분 실패가 병원 대량 삭제로 이어지지 않게).
        (지운 목록, 남긴 목록)을 돌려준다."""
        roster = set(hospital_ids)
        with self._lock:
            missing = [hid for hid in self._hospitals if hid not in roster]
            if not missing or len(roster) < len(self._hospitals) / 2:
                return [], missing
            in_use = {h.hospitalId for r in self._case_results.values() for h in r.hospitals}
            removed = [hid for hid in missing if hid not in in_use]
            kept = [hid for hid in missing if hid in in_use]
            for hid in removed:
                del self._hospitals[hid]
                self._bed_overlay.pop(hid, None)
                self._info_confirmations.pop(hid, None)
            if removed:
                self._dirty = True
            return removed, kept

    def get_hospital(self, hospital_id: str) -> HospitalInfo | None:
        with self._lock:
            return self._hospitals.get(hospital_id)

    def confirm_hospital_info(self, hospital_id: str, ts: datetime) -> bool:
        """병원 대시보드의 "현재 정보 확인" 신호를 기록한다(2026-09-29).
        모르는 병원이면 False — 잘못된 hpid의 확인이 조용히 쌓이지 않게."""
        with self._lock:
            if hospital_id not in self._hospitals:
                return False
            self._info_confirmations[hospital_id] = ts
            self._dirty = True
            return True

    def get_info_confirmation(self, hospital_id: str) -> datetime | None:
        with self._lock:
            return self._info_confirmations.get(hospital_id)

    def update_ambulance_info(self, info: AmbulanceInfo) -> None:
        """feature/info로부터 받은 구급차 정보를 apid 기준으로 upsert한다."""
        with self._lock:
            self._ambulances[info.apid] = info
            self._dirty = True

    def get_ambulance(self, apid: str) -> AmbulanceInfo | None:
        """시뮬레이션 위치가 있으면 그 GPS로 바꾼 사본을 돌려준다(매칭·경로·ETA가 전부 이걸 쓴다)."""
        with self._lock:
            ambulance = self._ambulances.get(apid)
            override = self._gps_override.get(apid)
        if ambulance is not None and override is not None:
            return ambulance.model_copy(update={"gps": override})
        return ambulance

    def get_ambulance_base(self, apid: str) -> AmbulanceInfo | None:
        """등록값 그대로(시뮬레이션의 기지 좌표)."""
        with self._lock:
            return self._ambulances.get(apid)

    def list_ambulances(self) -> list[AmbulanceInfo]:
        with self._lock:
            return list(self._ambulances.values())

    def set_gps_override(self, apid: str, gps: GpsPoint | None) -> None:
        with self._lock:
            if gps is None:
                self._gps_override.pop(apid, None)
            else:
                self._gps_override[apid] = gps

    def register_case(self, case_id: str, apid: str) -> None:
        """통화 시작(CallSignal) 시점에 이 사건이 어느 구급차 것인지 기억해둔다."""
        with self._lock:
            self._case_apid[case_id] = apid
            self._dirty = True

    def get_case_apid(self, case_id: str) -> str | None:
        with self._lock:
            return self._case_apid.get(case_id)

    def get_case_result(self, case_id: str) -> HubMatchResult | None:
        """app.py가 승인 액션 처리 후 캐시된 최신 결과를 꺼내 dashboard에
        재브로드캐스트할 때 쓴다."""
        with self._lock:
            return self._case_results.get(case_id)

    def get_cases_for_hospital(self, hospital_id: str) -> list[HubMatchResult]:
        """이 hospitalId가 후보로 들어있는 사건 전부(따라잡기용, app.py `_send_catchup()`)."""
        with self._lock:
            return [
                result
                for result in self._case_results.values()
                if any(h.hospitalId == hospital_id for h in result.hospitals)
            ]

    def get_cases_for_apid(self, apid: str) -> list[HubMatchResult]:
        """이 apid(구급차)가 등록한 사건 전부를 돌려준다. 구급차는 실제로는
        한 번에 사건 하나만 진행하지만(voice 마이크가 한 대뿐이라), 같은
        방식으로 여러 건이 나와도 안전하게 동작하도록 리스트로 반환한다."""
        with self._lock:
            case_ids = [cid for cid, registered_apid in self._case_apid.items() if registered_apid == apid]
            results = [self._case_results.get(cid) for cid in case_ids]
            return [result for result in results if result is not None]

    def get_active_case_ids(self) -> list[str]:
        """매칭 결과가 있는(주기적 재계산 대상) 사건 목록."""
        with self._lock:
            return [cid for cid in self._case_results if cid in self._case_voice]

    # ── 정리 · 병상 오버레이 ──────────────────────────────────────────────────

    def _prune_old_cases(self, now: datetime | None = None) -> list[str]:
        """이송이 확정된 지 CASE_RETENTION_MIN이 지난 사건의 **큰 캐시**
        (매칭 결과·voice 요약)를 걷어낸다. 진행 중이거나 아직 확정 전인 사건
        (_case_confirmed_at에 없음)은 건드리지 않는다 — 따라잡기(_send_catchup)·
        다중 사건 격리는 그대로 보장된다.

        `_approval_status`는 **일부러 남긴다.** 여기 있는 `(caseId, hospitalId) ->
        상태`는 `final_approval` 멱등성 가드가 읽는 값인데, 이걸 지우면 같은
        최종 승인이 CASE_RETENTION_MIN 뒤에 중복 도착할 때(네트워크 재시도 등)
        가드가 뚫려 병상이 한 번 더 깎인다. 항목이 작은 튜플뿐이고 액션을 받은
        사건에만 생기므로, 남겨도 누적 부담이 사실상 없다(큰 건 위 두 dict다).

        지운 caseId 목록을 돌려준다(테스트·로그용).
        """
        with self._lock:
            now = now or _utcnow()
            cutoff = now - timedelta(minutes=CASE_RETENTION_MIN)
            stale = [cid for cid, at in self._case_confirmed_at.items() if at <= cutoff]
            for cid in stale:
                self._drop_case_locked(cid)
            if stale:
                self._dirty = True
                print(f"  [정리] 확정된 지 {CASE_RETENTION_MIN}분 지난 사건 {len(stale)}건 캐시에서 제거: {stale}")
            return stale

    def _drop_case_locked(self, case_id: str) -> None:
        """사건 하나의 큰 캐시를 지운다(락을 쥔 채로 호출). `_approval_status`는 남긴다 —
        이유는 _prune_old_cases() 참고."""
        self._case_results.pop(case_id, None)
        self._case_apid.pop(case_id, None)
        self._case_max_zone.pop(case_id, None)
        self._case_voice.pop(case_id, None)
        self._case_group.pop(case_id, None)
        self._case_gps_fallback.pop(case_id, None)
        self._case_confirmed_at.pop(case_id, None)
        for key in [k for k in self._case_overlay if k[0] == case_id]:
            del self._case_overlay[key]

    def close_case(self, case_id: str) -> bool:
        """확정 없이 끝난 사건(방치 정리·현장 종료)을 캐시·따라잡기·주기 재계산에서 뺀다
        (2026-10-01). 예전엔 확정된 사건만 60분 뒤 지워서, 취소·중단된 사건이 병원 대시보드
        따라잡기 목록에 영원히 떴다. 이송 확정된 사건은 여기서 지우지 않는다(병상 차감이 걸려
        있어 기존 60분 정리를 따른다). 지웠으면 True."""
        with self._lock:
            if case_id in self._case_confirmed_at:
                return False
            existed = case_id in self._case_results or case_id in self._case_apid
            self._drop_case_locked(case_id)
            if existed:
                self._dirty = True
            return existed

    def _prune_and_count_overlay(self, hospital_id: str, now: datetime) -> int:
        """만료된 차감 기록을 걷어내고, 아직 유효한 개수를 돌려준다."""
        expirations = self._bed_overlay.get(hospital_id)
        if not expirations:
            return 0
        active = [expires_at for expires_at in expirations if expires_at > now]
        if active:
            self._bed_overlay[hospital_id] = active
        else:
            del self._bed_overlay[hospital_id]
        return len(active)

    def effective_bed_count(self, info: HospitalInfo) -> int:
        """TTL 오버레이가 적용된 실제 표시용 병상 수. 0 미만으로는 안 내려간다
        — 같은 병원에 짧은 시간 안에 여러 사건이 동시에 확정되는 극단적인
        경우에도 dashboard에 음수 병상이 뜨지 않게 한다."""
        with self._lock:
            overlay = self._prune_and_count_overlay(info.hospitalId, _utcnow())
            return max(0, info.availableBedCount - overlay)

    # ── 승인 액션 ─────────────────────────────────────────────────────────────

    def _refresh_match(
        self, case_id: str, match: HospitalMatch, status: HospitalStatus, now: datetime
    ) -> HospitalMatch:
        """캐시된 HospitalMatch 하나를 지금 상태(승인 상태·병상·만실 판정)로 다시 맞춘다."""
        update: dict[str, Any] = {"status": status}
        info = self._hospitals.get(match.hospitalId)
        if info is not None:
            beds = self.effective_bed_count(info)
            unknown = _is_bed_count_unknown(info)
            stale = _is_bed_data_stale(info, now)
            update.update(
                availableBedCount=beds,
                bedCountUnknown=unknown,
                bedDataStale=stale,
                demoteReasons=_demote_reasons(
                    info, self._case_group.get(case_id), status, beds, unknown, stale
                ),
            )
        elif status == "rejected":
            update["demoteReasons"] = ["rejected"]
        return match.model_copy(update=update)

    def _patch_case_result_status(self, case_id: str, hospital_id: str, status: HospitalStatus) -> None:
        """캐시해둔 사건의 매칭 결과에서 해당 병원의 status·병상 정보·내림 이유를 최신 값으로
        다시 맞추고 **재정렬**한다(2026-09-28 — 거절한 병원이 1위 자리에 그대로 남던 문제).

        final_approval로 병상 오버레이가 얹혀도 dashboard로 나가는 이 캐시된 스냅샷엔 반영이
        안 되던 문제가 있어(2026-08-11), 호출 시점의 값으로 병상 필드도 같이 다시 읽어온다.
        아직 process_voice_summary가 호출된 적 없는 caseId면(캐시가 없으면) 조용히 넘어간다.
        """
        with self._lock:
            result = self._case_results.get(case_id)
            if result is None:
                return
            now = _utcnow()
            hospitals = [
                self._refresh_match(case_id, h, status, now) if h.hospitalId == hospital_id else h
                for h in result.hospitals
            ]
            self._case_results[case_id] = result.model_copy(update={"hospitals": _sort_matches(hospitals)})
            self._dirty = True

    def apply_approval_action(self, action: ApprovalAction) -> None:
        """dashboard가 보낸 승인 액션을 반영한다 (dashboard는 이 브랜치와만 직접
        통신하므로 수신은 여기서 한다). hospitals[].status에 반영될 내부 상태를
        갱신하고, 병상이 실제로 줄어드는 경우(final_approval)에는 TTL 오버레이에
        차감 기록을 얹는다.
        """
        with self._lock:
            self._prune_old_cases()
            self._dirty = True

            # 멱등성: 이미 confirmed된 병원에 최종 승인이 중복 도착해도(버튼 중복
            # 클릭, 네트워크 재시도 등) 병상을 두 번 깎지 않는다. 여러 사건이
            # 동시에 진행될 수 있어 (caseId, hospitalId) 조합으로 구분한다.
            status_key = (action.caseId, action.hospital_id)
            current = self._approval_status.get(status_key, "pending")
            if action.action == "final_approval" and current == "confirmed":
                decision_log.log_decision(
                    "approval_action_ignored_duplicate",
                    {"action": action.model_dump(), "reason": "already confirmed"},
                )
                return

            # 순서·권한 검사(2026-09-28). 거부된 액션은 상태를 바꾸지 않고 사유만 남긴다.
            # - 주체 짝: 병원 승인·거절은 병원, 이송 승인은 구급대원
            # - 이송 승인은 병원이 이 사건에 승인(approved)한 병원에만 — "병원의 승인은 후보
            #   등록, 구급대원의 이송 승인이 최종 확정"(CLAUDE.md) 순서를 지킨다
            refuse_reason = None
            if action.actor != _ACTION_ACTOR[action.action]:
                refuse_reason = f"actor mismatch: {action.action} requires {_ACTION_ACTOR[action.action]}"
            elif action.action == "final_approval" and current != "approved":
                refuse_reason = f"final_approval requires hospital approval (current: {current})"
            if refuse_reason is not None:
                decision_log.log_decision(
                    "approval_action_refused", {"action": action.model_dump(), "reason": refuse_reason}
                )
                return

            if action.action == "final_approval":
                # 재선택: 이 사건에서 이미 확정된 다른 병원이 있으면 확정을 풀고(approved로
                # 되돌림 — 병원의 승인 자체는 유효) 그 확정이 얹은 병상 차감을 회수한다.
                # 새 상태값을 만들지 않는 건 dashboard의 HospitalStatus 타입을 그대로 쓰기 위해서다.
                for (cid, hid), status in list(self._approval_status.items()):
                    if cid == action.caseId and hid != action.hospital_id and status == "confirmed":
                        self._release_confirmation(cid, hid, action)

            new_status = _ACTION_TO_STATUS[action.action]
            self._approval_status[status_key] = new_status
            if new_status == "confirmed":
                # 이송 확정 시각을 기록해둔다 — _prune_old_cases()가 이 시각을 기준으로
                # CASE_RETENTION_MIN이 지난 사건을 캐시에서 걷어낸다. 병상이 안 깎인
                # 확정(skip_reason 경로)이어도 사건이 끝난 건 같으므로 여기서 기록한다.
                self._case_confirmed_at[action.caseId] = _utcnow()

            if action.action != "final_approval":
                # 병상은 안 건드리는 액션이라 지금 self._hospitals 값 그대로 패치해도 된다.
                self._patch_case_result_status(action.caseId, action.hospital_id, new_status)
                decision_log.log_decision("approval_action_applied", {"action": action.model_dump(), "bedUpdate": None})
                return

            info = self._hospitals.get(action.hospital_id)
            # 병상을 깎지 않고 넘어가는 경우를 이유별로 남긴다. "미상"과 "확인된 만실"은
            # 결과(차감 안 함)는 같아도 원인이 달라서, 로그에서 섞이면 사후에 데이터 품질
            # 문제인지 실제로 자리가 없었던 건지 구분할 수 없다.
            skip_reason = None
            if info is None:
                skip_reason = "unknown hospital"
            elif _is_bed_count_unknown(info):
                # 모르는 값은 깎을 수 없다. 다만 확정(status) 자체는 막지 않는다 —
                # 미상을 이유로 이송을 막으면 뺑뺑이가 오히려 늘어난다.
                skip_reason = "bed count unknown"
            elif self.effective_bed_count(info) <= 0:
                # 원본 값이 아니라 오버레이가 이미 반영된 값으로 판단한다 — 다른
                # 사건이 방금 이 병원을 확정했다면 그 차감이 아직 안 끝난 것이다.
                skip_reason = "no beds left"

            if skip_reason is not None:
                # 병상은 안 깎였지만 status는 confirmed로 바뀌었으니 캐시에도 반영한다.
                self._patch_case_result_status(action.caseId, action.hospital_id, new_status)
                decision_log.log_decision(
                    "approval_action_ignored_no_bed",
                    {"action": action.model_dump(), "reason": skip_reason},
                )
                return

            expires_at = _utcnow() + timedelta(minutes=BED_OVERLAY_TTL_MIN)
            self._bed_overlay.setdefault(info.hospitalId, []).append(expires_at)
            self._case_overlay[status_key] = expires_at
            # 병상 차감(오버레이)이 실제로 얹힌 뒤에 패치해야 dashboard 캐시에도 새
            # 병상 수가 반영된다 — 얹기 전에 패치하면 status만 바뀌고 병상 배지는
            # 옛날 값 그대로 남는다.
            self._patch_case_result_status(action.caseId, action.hospital_id, new_status)

            decision_log.log_decision(
                "approval_action_applied",
                {
                    "action": action.model_dump(),
                    "bedOverlay": {
                        "hospitalId": info.hospitalId,
                        "effectiveBedCount": self.effective_bed_count(info),
                        "expiresAt": expires_at.isoformat(),
                    },
                },
            )

    def _release_confirmation(self, case_id: str, hospital_id: str, action: ApprovalAction) -> None:
        """재선택으로 밀려난 병원의 확정을 풀고 병상 차감을 회수한다(락 안에서만 호출)."""
        self._approval_status[(case_id, hospital_id)] = "approved"
        expires_at = self._case_overlay.pop((case_id, hospital_id), None)
        overlay = self._bed_overlay.get(hospital_id, [])
        reclaimed = expires_at in overlay  # 이미 만료돼 정리됐으면 회수할 것이 없다
        if reclaimed:
            overlay.remove(expires_at)
            if not overlay:
                del self._bed_overlay[hospital_id]
        self._patch_case_result_status(case_id, hospital_id, "approved")
        decision_log.log_decision(
            "approval_released",
            {
                "caseId": case_id,
                "hospitalId": hospital_id,
                "reason": f"reselected: {action.hospital_id}",
                "bedOverlayReclaimed": reclaimed,
            },
        )

    # ── 존 · 후보 ─────────────────────────────────────────────────────────────

    def reject_ratio(self, case_id: str, ambulance_gps: GpsPoint, max_zone: int) -> float:
        """현재 존(1~max_zone) 안 병원들 중, 명시적으로 응답(approved/rejected/
        confirmed)한 병원 대비 거절(rejected)한 병원의 비율. 아직 아무도 응답하지
        않았으면(전부 pending) 0.0을 반환한다 — 시간 기반이 아닌 거절 비율 기반
        존 확장 판단에 쓴다.
        """
        with self._lock:
            candidates = self._candidates_in_zone(ambulance_gps, max_zone)
            statuses = [self._approval_status.get((case_id, info.hospitalId), "pending") for info, _ in candidates]
        responded = [s for s in statuses if s in ("approved", "rejected", "confirmed")]
        if not responded:
            return 0.0
        rejected = sum(1 for s in responded if s == "rejected")
        return rejected / len(responded)

    def _candidates_in_zone(
        self, ambulance_gps: GpsPoint, max_zone: int
    ) -> list[tuple[HospitalInfo, float]]:
        with self._lock:
            candidates = []
            for info in self._hospitals.values():
                distance = haversine_km(ambulance_gps.lat, ambulance_gps.lng, info.gps.lat, info.gps.lng)
                if zone_of(distance) <= max_zone:
                    candidates.append((info, distance))
            return candidates

    def build_zone_candidates(self, ambulance_gps: GpsPoint, max_zone: int = 1) -> list[dict]:
        """1단계: voice 정보가 도착하기 전, GPS+병원 정보만으로 존 기반 후보 리스트를
        만들어 보관해둔다. 진료과 매칭 없이 거리만으로 정렬한 중간 상태를 반환한다.
        """
        candidates = self._candidates_in_zone(ambulance_gps, max_zone)
        candidates.sort(key=lambda pair: pair[1])
        return [
            {
                "hospitalId": info.hospitalId,
                "name": info.name,
                "distanceKm": round(distance, 2),
                "gps": info.gps.model_dump(),
                "availableBedCount": self.effective_bed_count(info),
                "bedCountUnknown": _is_bed_count_unknown(info),
            }
            for info, distance in candidates
        ]

    # ── 매칭 ──────────────────────────────────────────────────────────────────

    def _compute_result(
        self,
        voice: VoiceCallSummaryMessage,
        ambulance_gps: GpsPoint,
        max_zone: int,
        gps_fallback: bool,
    ) -> tuple[HubMatchResult, str | None]:
        """매칭 결과 하나를 계산한다(저장·로그는 호출자 몫). 임베딩·카카오 호출은 상태 락
        밖에서 하고, 승인 상태·병상을 읽어 조립하는 부분만 락 안에서 한다."""
        expected_diagnosis = voice.summary.mechanism
        candidates = self._candidates_in_zone(ambulance_gps, max_zone)

        # 진료과 매칭 + info-v2 15개 질환군 중 이번 사건에 해당하는 것 하나. 질환군은 병원마다
        # 다른 게 아니라 사건 전체에 하나뿐이라 한 번만 매칭한다(같은 SpecialtyMatcher, 대상
        # 어휘만 다름). 질환군은 finalScore에 안 들어가고 설명·declared_no 판정에만 쓰인다.
        department_lists = [[s.department for s in info.specialties] for info, _ in candidates]
        with self._matcher_lock:
            specialty_results = self._matcher.match_many(expected_diagnosis, department_lists)
            vocabulary = _assessment_vocabulary([info for info, _ in candidates])
            best_group, _ = self._matcher.match_many(expected_diagnosis, [vocabulary])[0]

        # 후보 병원별 도로 기준 소요시간(초). 조회 실패·키 없음·반경 10km 밖이면 그 병원만 빠진다.
        etas = (
            self._router.etas(ambulance_gps, {info.hospitalId: info.gps for info, _ in candidates})
            if self._router is not None and candidates
            else {}
        )
        # 이동 시간(분): ETA가 있으면 그 값, 없으면 직선거리 × 보정 분/km(scoring 참고).
        min_per_km = calibrate_min_per_km(
            [(distance, etas[info.hospitalId][0] / 60.0) for info, distance in candidates if info.hospitalId in etas]
        )

        with self._lock:
            now = _utcnow()
            matches = []
            required = voice.summary.required_department
            for (info, distance), (best_dept, similarity) in zip(candidates, specialty_results):
                eta = etas.get(info.hospitalId)
                travel_min = eta[0] / 60.0 if eta is not None else distance * min_per_km
                # voice가 필요 진료과(심평원 과목 표기)를 알려줬고 병원에 그 과가 있으면 정확 일치,
                # 아니면 임베딩 유사도 그대로(2026-10-01). 일치하지 않아도 후보에서 빼지 않는다.
                by_dept = {s.department: s for s in info.specialties}
                if required and required in by_dept:
                    best_dept, similarity, basis = required, 1.0, "exact"
                else:
                    basis = "embedding" if best_dept is not None else "none"
                matched = by_dept.get(best_dept) if best_dept else None
                doctor_count = matched.doctorCount if matched is not None and matched.doctorCount > 0 else None
                bonus_min, bonus_reasons = expertise_bonus_min(
                    doctor_count, info.emergencyLevel, voice.summary.severity_tag
                )
                status = self._approval_status.get((voice.caseId, info.hospitalId), "pending")
                beds = self.effective_bed_count(info)
                unknown = _is_bed_count_unknown(info)
                stale = _is_bed_data_stale(info, now)
                # 병원의 "현재 정보 확인" 이력 — 현재 claim에 유효한지는
                # evaluate()가 bornAt과 대조해 판단한다.
                confirmed = self._info_confirmations.get(info.hospitalId)
                matches.append(
                    HospitalMatch(
                        hospitalId=info.hospitalId,
                        name=info.name,
                        gps=info.gps,
                        distanceKm=round(distance, 2),
                        specialtyMatch=SpecialtyMatch(
                            department=best_dept, score=round(similarity, 4), basis=basis, doctorCount=doctor_count
                        ),
                        availableBedCount=beds,
                        bedCountUnknown=unknown,
                        status=status,
                        reliability=_reliability_for(info, best_group) if best_group is not None else None,
                        # 병상 숫자 자체의 유효 확률(infosurv 모델, source: "ai"). 설명용 —
                        # 도착 시점(horizon)은 순위에 쓴 이동 시간과 같은 값을 쓴다.
                        bedReliability=bed_reliability.evaluate(
                            info.bedReliability, distance, now=now,
                            horizon_sec=travel_min * 60.0, confirmed_at=confirmed,
                        ),
                        # 매칭된 질환군의 수용가능 신고 신선도(규칙 기반, source: "rule").
                        severeFreshness=_severe_freshness_for(info, best_group),
                        # 수술실·입원실·소아 등 확장 필드의 유효 확률 — 응급실
                        # 일반(bedReliability)과 같은 환산, 같은 horizon.
                        bedReliabilityByType=(
                            {
                                field: bed_reliability.evaluate(
                                    payload, distance, now=now,
                                    horizon_sec=travel_min * 60.0, confirmed_at=confirmed,
                                )
                                for field, payload in info.bedReliabilityByType.items()
                            }
                            if info.bedReliabilityByType
                            else None
                        ),
                        # 도로 기준 도착 예상 시간(분, 올림). 표시용 원값.
                        etaMin=_ceil_minutes(eta[0]) if eta is not None else None,
                        finalScore=round(final_score(similarity, travel_min, bonus_min), 6),
                        emergencyLevel=info.emergencyLevel,
                        travelBonusMin=round(bonus_min, 1),
                        bonusReasons=bonus_reasons,
                        travelMin=round(travel_min, 1),
                        travelBasis="eta" if eta is not None else "estimate",
                        demoteReasons=_demote_reasons(info, best_group, status, beds, unknown, stale),
                        bedDataStale=stale,
                    )
                )

            # 구급차 대시보드 상단바 표시용. 이 사건의 apid를 register_case()로
            # 기억해둔 값에서 찾아, 구급차 레지스트리의 이름을 그대로 붙인다.
            apid = self._case_apid.get(voice.caseId)
            ambulance = self.get_ambulance(apid) if apid else None

        result = HubMatchResult(
            caseId=voice.caseId,
            patientInfo=PatientInfo(
                injuryStatus=voice.summary.symptoms,
                expectedDiagnosis=expected_diagnosis,
                severityTag=voice.summary.severity_tag,
                rawTranscript=voice.transcript.raw_text,
                filteredTranscript=voice.transcript.filtered_text,
            ),
            zoneActive=active_zones(max_zone),
            hospitals=_sort_matches(matches),
            source="rule",
            ambulanceName=ambulance.name if ambulance is not None else None,
            apid=apid,
            ambulanceGps=ambulance_gps,
            ambulanceGpsFallback=gps_fallback,
        )
        return result, best_group

    def process_voice_summary(
        self,
        voice: VoiceCallSummaryMessage,
        ambulance_gps: GpsPoint,
        max_zone: int = 1,
        gps_fallback: bool = False,
    ) -> HubMatchResult:
        """2단계: voice의 의료 정보가 도착하면, 보관해둔 병원 정보와 결합해
        진료과 매칭 + 이동 시간을 가중합한 최종 매칭 결과를 만든다.

        정렬 예외(scoring.rank_key): 이 사건에서 거절한 병원은 맨 뒤, 관련 질환군
        `declared_no`·확인된 만실 병원은 그 앞으로 내린다. finalScore 값 자체는 안 바뀌고
        후보에서 제거하지도 않는다.
        """
        with self._lock:
            self._prune_old_cases()
            self._case_voice[voice.caseId] = voice
            self._case_max_zone[voice.caseId] = max_zone
            self._case_gps_fallback[voice.caseId] = gps_fallback
            self._dirty = True

        result, group = self._compute_result(voice, ambulance_gps, max_zone, gps_fallback)

        with self._lock:
            # 승인 액션이 들어왔을 때 재계산 없이 패치·재브로드캐스트할 수 있게
            # 사건 단위로 최신 결과를 캐시해둔다 (get_case_result() 참고).
            self._case_results[voice.caseId] = result
            self._case_group[voice.caseId] = group
            self._dirty = True
        # CLAUDE.md "모든 의사결정 로그는 타임스탬프 + SHA-256 해시로 저장" 원칙.
        # 통화 전문만 지문으로 치환해 남긴다(_redact_transcript 참고).
        decision_log.log_decision("hub_match_result", _redact_transcript(result.model_dump()))
        return result

    def refresh_case(self, case_id: str, ambulance_gps: GpsPoint) -> HubMatchResult | None:
        """진행 중인 사건을 같은 환자 정보·같은 zone으로 다시 계산한다(2026-09-28, app.py의
        주기적 재계산이 호출). 매칭 시점에 고정돼 있던 병상 수·ETA·병상 신뢰도가 이송 중에도
        갱신된다.

        대시보드에 다시 보낼 만큼 달라졌으면 새 결과를, 아니면 None을 돌려준다. 순위·상태·
        병상이 바뀐 경우에만 의사결정 로그(hub_match_refreshed)를 남긴다.
        """
        with self._lock:
            voice = self._case_voice.get(case_id)
            old = self._case_results.get(case_id)
            max_zone = self._case_max_zone.get(case_id, 1)
            gps_fallback = self._case_gps_fallback.get(case_id, False)
            confirmed = case_id in self._case_confirmed_at
        if voice is None or old is None:
            return None
        # 이송이 확정된 사건은 다시 순위를 매기지 않는다(2026-10-01). 목적지가 정해졌는데 구급차가
        # 움직일 때마다 목록이 뒤섞이고 후보 전체 ETA를 다시 부를 이유가 없다. 남은 도착 시간은
        # 출동 시뮬레이션의 위치 메시지(etaSec)로 따로 나간다. 승인 액션 뒤 패치는 그대로 된다.
        if confirmed:
            return None

        result, group = self._compute_result(voice, ambulance_gps, max_zone, gps_fallback)

        with self._lock:
            if case_id not in self._case_voice:
                return None  # 계산하는 사이 정리됨
            self._case_results[case_id] = result
            self._case_group[case_id] = group
            self._dirty = True

        if _decision_signature(old) != _decision_signature(result):
            decision_log.log_decision("hub_match_refreshed", _redact_transcript(result.model_dump()))
        return result if _display_signature(old) != _display_signature(result) else None

    # ── 존 확장 ───────────────────────────────────────────────────────────────

    def expand_if_needed(self, max_zone: int, reject_ratio: float) -> int:
        """명시적 거절 비율이 임계값을 넘으면 다음 존까지 확장한 max_zone을 반환한다
        (시간 기반 타임아웃이 아닌 거절 비율 기반 — CLAUDE.md 원칙).
        """
        return max_zone + 1 if should_expand_zone(reject_ratio) else max_zone

    def _expand_until_nonempty(self, ambulance_gps: GpsPoint, start_zone: int, cap: int = 10) -> int:
        """start_zone부터 시작해 후보가 하나라도 잡힐 때까지 zone을 넓힌다.

        reject_ratio 기반 확장(expand_if_needed)은 "후보가 있는데 다
        거절당했다"만 감지한다 — 거절할 대상 자체가 없으면(zone 안에 병원이
        0개) reject_ratio가 항상 0.0으로 나와 영원히 확장되지 않는 사각지대가
        생긴다. 그래서 후보 0개는 거절 비율과 별개로 무조건 확장한다.
        cap은 병원 데이터가 거의 없는 등 극단적인 경우 무한 루프를 막는 안전장치다.
        """
        zone = start_zone
        while zone < cap and not self._candidates_in_zone(ambulance_gps, zone):
            zone += 1
        return zone

    def resolve_start_zone(self, ambulance_gps: GpsPoint) -> int:
        """새 사건의 매칭을 시작할 때 쓸 zone을 정한다. zone 1부터 시작해
        후보가 하나라도 잡힐 때까지 넓힌다(_expand_until_nonempty 참고)."""
        return self._expand_until_nonempty(ambulance_gps, start_zone=1)

    def get_case_max_zone(self, case_id: str) -> int:
        with self._lock:
            return self._case_max_zone.get(case_id, 1)

    def maybe_expand_zone(self, case_id: str, ambulance_gps: GpsPoint) -> HubMatchResult | None:
        """거절(hospital_reject) 액션 처리 후에만 호출해야 한다. 지금 zone에
        후보가 아예 없거나(사각지대 보정), 명시적 거절 비율이 임계값을
        넘으면 zone을 확장해 후보를 다시 계산한다. 확장이 실제로 일어났을
        때만 재계산된 HubMatchResult를 반환하고, 안 바뀌었으면 None을
        반환한다(호출자가 굳이 재브로드캐스트 안 하도록).

        reject_ratio는 누적 계산이라 승인(hospital_approve)이나 최종 승인(final_approval)
        뒤에도 부르면 새 거절 없이도 계속 확장된다(실제로 재현·검증됨). 그래서 caller(app.py)가
        action.action == "hospital_reject"일 때만 불러야 한다.
        """
        with self._lock:
            current_max_zone = self._case_max_zone.get(case_id, 1)
            voice = self._case_voice.get(case_id)
            gps_fallback = self._case_gps_fallback.get(case_id, False)
        candidates = self._candidates_in_zone(ambulance_gps, current_max_zone)
        if not candidates:
            new_max_zone = self._expand_until_nonempty(ambulance_gps, current_max_zone)
        else:
            ratio = self.reject_ratio(case_id, ambulance_gps, current_max_zone)
            new_max_zone = self.expand_if_needed(current_max_zone, ratio)

        if new_max_zone == current_max_zone:
            return None

        if voice is None:
            # process_voice_summary가 한 번도 호출된 적 없는 사건 — 승인 액션이
            # 오려면 후보가 먼저 있어야 하므로 이론상 없는 상태지만, 방어적으로
            # 넘어간다.
            return None

        print(f"  [존 확장] case={case_id} zone 1~{current_max_zone} -> 1~{new_max_zone}")
        return self.process_voice_summary(voice, ambulance_gps, max_zone=new_max_zone, gps_fallback=gps_fallback)

    # ── 디스크 저장 · 복구 (2026-09-28) ───────────────────────────────────────

    def take_dirty(self) -> bool:
        """마지막 저장 뒤 변경이 있었는지 돌려주고 표시를 지운다(app.py 저장 루프용)."""
        with self._lock:
            dirty, self._dirty = self._dirty, False
            return dirty

    def export_state(self) -> dict:
        """재시작 뒤 복구할 상태를 JSON으로 직렬화 가능한 dict로 만든다.

        통화 원문은 넣지 않는다(TRANSCRIPT_NOT_PERSISTED로 치환) — 개인정보가 섞일 수 있는
        자유 텍스트를 디스크에 또 남기지 않는 원칙. 나머지(병원·구급차 레지스트리, 승인 상태,
        병상 오버레이, 사건별 구조화 요약·결과)는 그대로 남긴다.
        """
        with self._lock:
            case_ids = set(self._case_apid) | set(self._case_voice) | set(self._case_results)
            cases = {}
            for cid in case_ids:
                voice = self._case_voice.get(cid)
                result = self._case_results.get(cid)
                confirmed_at = self._case_confirmed_at.get(cid)
                cases[cid] = {
                    "apid": self._case_apid.get(cid),
                    "maxZone": self._case_max_zone.get(cid),
                    "group": self._case_group.get(cid),
                    "gpsFallback": self._case_gps_fallback.get(cid, False),
                    "confirmedAt": confirmed_at.isoformat() if confirmed_at else None,
                    "voice": _voice_without_transcript(voice) if voice else None,
                    "result": _result_without_transcript(result) if result else None,
                }
            return {
                "version": STATE_VERSION,
                "savedAt": _utcnow().isoformat(),
                "hospitals": [h.model_dump() for h in self._hospitals.values()],
                "ambulances": [a.model_dump() for a in self._ambulances.values()],
                "approvalStatus": [[cid, hid, status] for (cid, hid), status in self._approval_status.items()],
                "bedOverlay": {hid: [t.isoformat() for t in times] for hid, times in self._bed_overlay.items()},
                "caseOverlay": [[cid, hid, t.isoformat()] for (cid, hid), t in self._case_overlay.items()],
                "infoConfirmations": {hid: t.isoformat() for hid, t in self._info_confirmations.items()},
                "cases": cases,
            }

    def import_state(self, state: dict) -> dict[str, int]:
        """export_state()로 저장한 상태를 복구한다. 항목 하나가 깨져 있어도 나머지는 살린다.
        복구 뒤 만료된 오버레이·오래된 확정 사건은 평소처럼 조회 시점에 정리된다."""
        if state.get("version") != STATE_VERSION:
            print(f"  [상태 복구] 알 수 없는 상태 파일 버전({state.get('version')}) — 복구하지 않음")
            return {}
        counts = {"hospitals": 0, "ambulances": 0, "cases": 0}
        with self._lock:
            for raw in state.get("hospitals", []):
                try:
                    info = HospitalInfo.model_validate(raw)
                except Exception as e:  # noqa: BLE001
                    print(f"  [상태 복구] 병원 항목 건너뜀: {e}")
                    continue
                self._hospitals[info.hospitalId] = info
                counts["hospitals"] += 1
            for raw in state.get("ambulances", []):
                try:
                    amb = AmbulanceInfo.model_validate(raw)
                except Exception as e:  # noqa: BLE001
                    print(f"  [상태 복구] 구급차 항목 건너뜀: {e}")
                    continue
                self._ambulances[amb.apid] = amb
                counts["ambulances"] += 1
            for cid, hid, at in state.get("caseOverlay", []):
                parsed_at = _parse_iso(at)
                if parsed_at is not None:
                    self._case_overlay[(cid, hid)] = parsed_at
            for cid, hid, status in state.get("approvalStatus", []):
                if status in _ACTION_TO_STATUS.values():
                    self._approval_status[(cid, hid)] = status
            for hid, times in state.get("bedOverlay", {}).items():
                parsed = [t for t in (_parse_iso(x) for x in times) if t is not None]
                if parsed:
                    self._bed_overlay[hid] = parsed
            for hid, raw_ts in state.get("infoConfirmations", {}).items():
                ts = _parse_iso(raw_ts)
                if ts is not None:
                    self._info_confirmations[hid] = ts
            for cid, case in state.get("cases", {}).items():
                try:
                    if case.get("apid"):
                        self._case_apid[cid] = case["apid"]
                    if case.get("maxZone") is not None:
                        self._case_max_zone[cid] = int(case["maxZone"])
                    if case.get("voice"):
                        self._case_voice[cid] = VoiceCallSummaryMessage.model_validate(case["voice"])
                    if case.get("result"):
                        self._case_results[cid] = HubMatchResult.model_validate(case["result"])
                    self._case_group[cid] = case.get("group")
                    self._case_gps_fallback[cid] = bool(case.get("gpsFallback"))
                    confirmed_at = _parse_iso(case["confirmedAt"]) if case.get("confirmedAt") else None
                    if confirmed_at is not None:
                        self._case_confirmed_at[cid] = confirmed_at
                except Exception as e:  # noqa: BLE001
                    print(f"  [상태 복구] 사건 {cid} 건너뜀: {e}")
                    continue
                counts["cases"] += 1
            self._prune_old_cases()
            self._dirty = False
        return counts
