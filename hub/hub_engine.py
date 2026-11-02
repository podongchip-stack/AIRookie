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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import bed_reliability
import decision_log
import spider_rule
from hospital_dispatch import can_receive
from disease_group import match_group
from geo import active_zones, haversine_km, should_expand_zone, zone_of
from schema import (
    AcceptanceMessage,
    AcceptanceMessageMatch,
    AmbulanceInfo,
    ApprovalAction,
    ArrivalResult,
    BackupBedRow,
    BackupEquipmentRow,
    GpsPoint,
    HospitalBackupView,
    HospitalInfo,
    HospitalMatch,
    HospitalStatus,
    HubMatchResult,
    ExtraNote,
    OverrideRecord,
    PatientInfo,
    PatientOverride,
    PatientUpdate,
    ReliabilityInfo,
    SevereFreshness,
    SpecialtyMatch,
    VoiceCallSummaryMessage,
)
from scoring import (
    calibrate_min_per_km,
    final_score,
    load_penalty_min,
    occupancy_penalty_min,
    rank_key,
)
from specialty_matcher import SpecialtyMatcher
from voice_v2 import KTAS_TO_SEVERITY

if TYPE_CHECKING:
    from routing import KakaoRouting

# 병상 차감을 지속시키는 방식(2026-08-13 변경). 예전엔 hub가 깎은 값을
# feature/info의 Supabase에 써서 다음 재조회 때도 유지시켰는데, info가 이제
# Supabase 없이 E-Gen 실 API만 쓰면서(조회 전용이라 쓰기 자체가 불가능) 그
# 경로가 사라졌다. 대신 hub가 자기 메모리에 차감분을 얹어 보여주는 오버레이로 대체한다.
#
# 언제 푸는가(2026-10-08 재설계 — 예전엔 확정 뒤 고정 15분). 15분의 근거였던 "hvidate 갱신 간격
# 중앙값 5분"은 병원 입력 주기가 아니라 E-Gen 시스템의 5분 묶음 주기였다. hub가 "병원이 우리 환자를
# 반영한 값"을 보려면 이송 + 병원 입력 + E-Gen 묶음(≤5분) + info 수집(≤5분)이 지나야 해서, 15분이면
# 구급차가 도착하기도 전에 차감이 풀려 같은 병상이 다시 비어 보이고 부하 페널티도 꺼졌다.
# 반대로 무작정 길게 두면 병원이 이미 고친 뒤 이중 차감이 돼 작은 응급실이 "확인된 만실"로 떨어진다.
#   1) 최소 유지: 확정 + 예상 이동시간 + BED_HOLD_GRACE_MIN까지는 무조건 유지
#   2) 조기 해제: 그 뒤 E-Gen 응급실 원값이 확정 당시(baseline)보다 줄었으면 병원이 반영한 것으로 보고 해제
#   3) 상한: 끝까지 안 줄어도 도착 예상 + BED_HOLD_MAX_AFTER_ARRIVAL_MIN에 해제
#   4) 병원이 수용 완료(arrival_accepted)를 누르면 1)·3)의 기준을 예상 도착이 아니라 실제 도착 시각으로 다시 잡는다
# 2)는 다른 환자의 입원으로 값이 줄어도 해제되는 근사다 — 그때는 E-Gen 값 자체가 현실에 가까워진 뒤라 받아들인다.
# 숫자는 정답 데이터 없이 정한 초기값이다(도착 결과 로그가 쌓이면 다시 맞춘다).
BED_HOLD_GRACE_MIN = 20  # E-Gen 묶음 5 + info 수집 5 + 병원 입력 여유 10
BED_HOLD_MAX_AFTER_ARRIVAL_MIN = 60
BED_HOLD_DEFAULT_TRAVEL_MIN = 15  # 확정 병원의 이동시간을 모를 때


@dataclass(eq=False)
class BedHold:
    """이송 확정 하나가 얹은 병상 차감(eq=False — 같은 값의 두 확정을 서로 다른 차감으로 센다)."""

    case_id: str | None
    confirmed_at: datetime
    hold_until: datetime  # 이때까지는 무조건 유지
    expires_at: datetime  # 이때는 무조건 해제(상한)
    baseline: int | None  # 확정 순간 E-Gen 응급실 원값(info.availableBedCount). None이면 조기 해제 안 함

    def to_json(self) -> dict:
        return {
            "caseId": self.case_id,
            "confirmedAt": self.confirmed_at.isoformat(),
            "holdUntil": self.hold_until.isoformat(),
            "expiresAt": self.expires_at.isoformat(),
            "baseline": self.baseline,
        }


def _bed_hold_window(anchor: datetime, travel_min: float) -> tuple[datetime, datetime]:
    """(최소 유지 끝, 상한). anchor는 확정 시각(travel_min = 예상 이동시간) 또는 실제 도착 시각(travel_min = 0)."""
    arrival = anchor + timedelta(minutes=max(travel_min, 0.0))
    return (
        arrival + timedelta(minutes=BED_HOLD_GRACE_MIN),
        arrival + timedelta(minutes=BED_HOLD_MAX_AFTER_ARRIVAL_MIN),
    )

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


def _override_to_json(override: dict | None) -> dict | None:
    """구급대원 확인 상태(_case_override 항목) -> 상태 파일용 dict."""
    if override is None:
        return None
    return {"confirmedAt": override["confirmedAt"],
            "records": [r.model_dump() for r in override["records"].values()]}


def _override_from_json(raw: dict | None) -> dict | None:
    if not raw or not raw.get("confirmedAt"):
        return None
    records = {}
    for item in raw.get("records") or []:
        try:
            record = OverrideRecord.model_validate(item)
        except Exception:  # noqa: BLE001 — 항목 하나가 깨져도 나머지는 살린다
            continue
        records[record.field] = record
    return {"confirmedAt": raw["confirmedAt"], "records": records}


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
    "arrival_accepted": "confirmed",
    "arrival_refused": "rejected",
    "transport_withdraw": "rejected",
}

# 액션마다 보낼 수 있는 주체(2026-09-28). 병원 승인·거절은 병원만, 이송 승인은 구급대원만.
# dashboard는 이미 이 짝으로만 보낸다(병원 화면 role="hospital", 구급차 화면 이송 승인) —
# 여기서는 짝이 어긋난 요청(조작·버그)을 막는 방어선이다.
_ACTION_ACTOR: dict[str, str] = {
    "hospital_approve": "hospital",
    "hospital_reject": "hospital",
    "final_approval": "paramedic",
    "arrival_accepted": "hospital",
    "arrival_refused": "hospital",
    "transport_withdraw": "hospital",
}

# 확정을 풀면서 그 병원을 이 사건에서 제외하는 원인(2026-10-05). 병원이 직접 "못 받는다"고 한 경우라, 같은 사건에서
# 다시 승인·이송 승인되지 않게 막는다(다른 사건에는 영향 없음). 구급대원의 재선택(paramedic_reselect)은 제외가 아니다.
_EXCLUDING_CAUSES = ("arrival_refused", "transport_withdraw")


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


def _er_capacity(info: HospitalInfo, effective_beds: int, bed_unknown: bool, bed_stale: bool) -> tuple[int | None, int | None]:
    """응급실 일반 정원과 포화도(%). 가용은 이송 확정 차감(TTL 오버레이)까지 반영한 값을 쓴다. info가 과밀(음수)을
    0으로 보내므로 포화도는 100%가 상한이다. 정원이 없거나 병상이 미상·오래된 값이면 포화도를 내지 않는다."""
    capacity = (info.bedCapacityByType or {}).get("ER_ADULT")
    if capacity is None or capacity <= 0 or bed_unknown or bed_stale:
        return capacity, None
    occupied = capacity - max(effective_beds, 0)
    return capacity, max(0, min(100, round(100 * occupied / capacity)))


#: [배후역량] 장비 줄(2026-10-08): E-Gen 운영 코드 → (화면 이름, 심평원 장비명 또는 None, 설명). 심평원 장비명이 None인
#: 줄은 심평원에 그 항목이 없다는 뜻이다(혈관조영장치는 전국 어디에도 항목이 없었다 — info hira.py 주석).
BACKUP_EQUIPMENT: tuple[tuple[str, str, str | None, str | None], ...] = (
    ("ECMO", "ECMO", "ECMO", None),
    ("VENTILATOR", "인공호흡기", "인공호흡기", None),
    ("CRRT", "CRRT(지속 투석)", None, "심평원은 일반 혈액투석기 대수만 있다(아래 줄)"),
    ("HD", "혈액투석기", "혈액투석을위한인공신장기", None),
    ("ANGIO", "혈관조영", None, "심평원 장비 목록에 항목이 없다"),
    ("CT", "CT", "CT", None),
    ("MRI", "MRI", "MRI", None),
    ("HYPOTHERMIA", "저체온 치료기", None, None),
    ("INCUBATOR", "인큐베이터", "인큐베이터", None),
    ("FETAL_MONITOR", "분만감시기", "분만감시기", "E-Gen에는 운영 항목이 없다"),
    ("VENTILATOR_PRETERM", "조산아 인공호흡기", None, None),
    ("HYPERBARIC", "고압산소", None, None),
)


def _hold_from_state(raw: Any) -> BedHold | None:
    """상태 파일의 병상 차감 하나. 예전 형식(만료 시각 문자열 하나, 고정 15분 TTL 시절)은 그 시각에 풀리는
    차감으로 옮긴다(확정 당시 값을 몰라 조기 해제는 안 함)."""
    if isinstance(raw, str):
        expires = _parse_iso(raw)
        return None if expires is None else BedHold(None, expires - timedelta(minutes=15), expires, expires, None)
    if not isinstance(raw, dict):
        return None
    times = [_parse_iso(raw.get(k) or "") for k in ("confirmedAt", "holdUntil", "expiresAt")]
    if any(t is None for t in times):
        return None
    baseline = raw.get("baseline")
    return BedHold(raw.get("caseId"), *times, baseline if isinstance(baseline, int) else None)


def _active_messages(info: HospitalInfo, now: datetime) -> list[AcceptanceMessage]:
    """E-Gen 수용 제한 메시지 중 지금 유효한 것(시작 ≤ 지금 < 종료). info는 30분마다 보내므로 그 사이에
    끝나거나 시작되는 메시지를 여기서 다시 거른다. 시각이 없거나 깨진 쪽은 열린 구간으로 본다."""
    active = []
    for msg in info.acceptanceMessages or []:
        start = _parse_iso(msg.startAt) if msg.startAt else None
        end = _parse_iso(msg.endAt) if msg.endAt else None
        if (start is None or start <= now) and (end is None or now < end):
            active.append(msg)
    return active


def _severe_blocked(info: HospitalInfo, group: str | None, now: datetime) -> bool:
    """사건 질환군에 대해 병원이 지금 유효한 중증질환 차단 메시지를 걸어뒀는지(2026-10-07). declared_no와
    같은 원칙으로 순서만 내린다 — 병원이 미리 밝힌 "못 받는다"라서 근거 강도는 신고와 같다."""
    if group is None:
        return False
    return any(m.kind == "severe" and m.diseaseGroup == group for m in _active_messages(info, now))


def _acceptance_messages_for(
    info: HospitalInfo, group: str | None, required_department: str | None, now: datetime
) -> list[AcceptanceMessageMatch] | None:
    """매칭 결과에 실을 메시지. 이 환자에 해당하는 것(matched)을 앞에 둔다. 응급실 메시지는 진료과가
    필요 진료과와 같거나 응급실 전체 공지("문의 후 이송")일 때 해당한다."""
    out = []
    for msg in _active_messages(info, now):
        if msg.kind == "severe":
            matched = group is not None and msg.diseaseGroup == group
        else:
            matched = msg.department == "응급실" or (
                required_department is not None and msg.department == required_department
            )
        out.append(AcceptanceMessageMatch(**msg.model_dump(), matched=matched))
    out.sort(key=lambda m: not m.matched)
    return out or None


def _demote_reasons(
    info: HospitalInfo,
    group: str | None,
    status: HospitalStatus,
    effective_beds: int,
    bed_unknown: bool,
    bed_stale: bool,
    now: datetime,
) -> list[str]:
    """이 병원을 순위 뒤쪽으로 내릴 이유들(2026-09-28). 비면 finalScore 순서 그대로다.

    - 이 사건에 대해 병원이 거절했으면 rejected 하나로 맨 뒤.
    - 병원이 이 사건에 승인·확정 응답을 했으면 내리지 않는다 — 그 병원의 명시적 응답이
      미리 해둔 신고(declared_no)·차단 메시지(severe_blocked)나 병상 숫자보다 우선이다. 특히 확정 직후 오버레이로 병상이
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
    if _severe_blocked(info, group, now):
        reasons.append("severe_blocked")
    if not bed_unknown and not bed_stale and effective_beds <= 0:
        reasons.append("beds_full")
    return reasons


def _unavailable_reason(status: HospitalStatus, demote_reasons: list[str]) -> str | None:
    """병원이 아직 답하지 않았지만(판단 대기) 지금 수용할 수 없는 이유(2026-10-03). 응급실 병상 0이 확인되면
    "beds_full" — 병원 승인도 막혀 있는 상태라(_is_confirmed_full) 화면에서 "판단 대기"로 두면 오해를 산다.
    매칭·재계산 때마다 E-Gen 값으로 다시 정하므로 병상이 생기면 저절로 사라진다."""
    return "beds_full" if status == "pending" and "beds_full" in demote_reasons else None


def _mark_not_selected(matches: list[HospitalMatch]) -> list[HospitalMatch]:
    """이송이 확정된 사건에서 "승인했지만 선택되지 않은" 병원에 깃발을 세운다(2026-10-22).

    임상 자문 요구 — 수용 승낙은 빈 병상 확인이 아니라 처치 공간 확보·기존 진료 조정·신규 수용 제한 같은
    **자원 선배정**이라, 선택되지 않았음을 알려 주지 않으면 그 준비가 계속 묶여 있다. status(approved)는
    건드리지 않는다: 승인 자체는 유효하고 이동 중 재선택의 대상으로 남아야 한다(뺑뺑이 방지 원칙).
    확정이 풀리면(재선택·도착 후 수용 불가·철회) 다음 계산에서 자동으로 False로 돌아간다.
    """
    if not any(m.status == "confirmed" for m in matches):
        return [m.model_copy(update={"notSelected": False}) if m.notSelected else m for m in matches]
    return [
        m.model_copy(update={"notSelected": True}) if m.status == "approved" and not m.notSelected else m
        for m in matches
    ]


def _sort_matches(matches: list[HospitalMatch]) -> list[HospitalMatch]:
    return sorted(
        _mark_not_selected(matches),
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
                h.spiderBlocked,
                h.ktasSuitability,
                h.etaMin,
                tuple(h.demoteReasons),
                len(h.acceptanceMessages or ()),
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
            (h.hospitalId, h.status, h.availableBedCount, h.bedCountUnknown, tuple(h.demoteReasons), h.spiderBlocked)
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
        # (caseId, hospitalId) -> 병원이 [불가] 때 고른 사유(2026-10-03). 화면의 사유 선택칸 표시용.
        self._reject_reason: dict[tuple[str, str], str] = {}
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
        # spider 매칭 규칙(2026-10-15): 이송 확정 전 사건마다 지금 잡은 줄(병원·도착 예정·KTAS) — 다른 사건의 τ 창 충돌 판정용
        self._spider_pick: dict[str, dict] = {}
        # 사건별로 구급차 좌표가 기본 좌표로 대체됐는지. 재계산 결과에도 같은 표시를 싣는다.
        self._case_gps_fallback: dict[str, bool] = {}
        # (caseId, hospitalId) -> 그 확정이 얹은 병상 차감. 이송 병원을 다시 고르면 이전 병원의
        # 차감을 이것으로 찾아 회수하고(2026-09-28), 수용 완료 때 기준 시각을 다시 잡는다(2026-10-08).
        self._case_overlay: dict[tuple[str, str], BedHold] = {}
        # hospitalId -> 아직 유효한 병상 차감 목록. final_approval마다 하나씩 추가되고,
        # _prune_and_count_overlay()가 조회 시점에 풀 것을 걸러낸다(BED_HOLD_* 규칙).
        self._bed_overlay: dict[str, list[BedHold]] = {}
        # caseId -> 이송이 확정된 시각(UTC). 위 dict들과 달리 이건 정리용이다 —
        # process_voice_summary()/apply_approval_action() 진입 때마다 여기서
        # CASE_RETENTION_MIN이 지난 사건을 골라 모든 사건 dict에서 걷어낸다
        # (_prune_old_cases). _bed_overlay와 같은 "조회 시점 lazy 정리" 패턴이다.
        self._case_confirmed_at: dict[str, datetime] = {}
        # 확정 병원 도착 뒤 병원이 기록한 수용 결과(caseId -> ArrivalResult, 2026-10-01). 수용만 들어간다.
        self._case_arrival: dict[str, ArrivalResult] = {}
        # (caseId, hospitalId) — 이 사건에서 제외된 병원(도착 후 수용 불가·이송 중 수용 철회, 2026-10-05)
        self._case_excluded: set[tuple[str, str]] = set()
        # caseId -> 앞선 통화 요약들(2026-10-05, 덧붙이기) — 새 통화 요약이 오면 직전 patientInfo를 여기 쌓는다
        self._case_prev_calls: dict[str, list[PatientUpdate]] = {}
        # caseId -> 구급대원 확인 상태(2026-10-13, Override): {"confirmedAt": iso, "records": {field: OverrideRecord}}.
        # 고친 값 자체는 _case_voice의 요약에 반영돼 이후 재계산(60초 주기·존 확장)에도 유지되고, 여기는 "누가·언제·
        # 무엇을 고쳤나"만 둔다. 새 통화 회차가 오면 지운다(새 AI 요약은 아직 확인 전).
        self._case_override: dict[str, dict] = {}
        # caseId -> 구급대원이 적어 보낸 추가 정보 목록(2026-10-26, patient_override의 extraNote). 덮어쓰지 않고 쌓는다.
        self._case_extra_notes: dict[str, list[ExtraNote]] = {}
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

    def clear_bed_overlay(self) -> None:
        """[시연 초기화] 전용(2026-10-04) — 이송 중 병상 차감을 비운다.
        실운영 경로에서는 부르지 않는다(차감은 BED_HOLD_* 규칙으로만 풀리는 게 원칙)."""
        with self._lock:
            self._bed_overlay.clear()
            self._case_overlay.clear()
            self._dirty = True

    def get_hospital(self, hospital_id: str) -> HospitalInfo | None:
        with self._lock:
            return self._hospitals.get(hospital_id)

    def build_backup_view(self, hospital_id: str) -> HospitalBackupView | None:
        """대시보드 [배후역량] 버튼(GET /hospital-backup, 2026-10-08) — 한 병원의 배후진료를 세 층으로 모은다.
        보유(심평원, 월 단위) · 운영/정원(E-Gen) · 지금 가용(E-Gen 5분, 이송 확정 차감 반영)과 그 숫자의 지금 유효
        확률(AI). 장비는 지금 남은 대수가 공개 정보에 없어 보유·운영만 싣는다. 순위와 무관한 열람용이다."""
        with self._lock:
            info = self._hospitals.get(hospital_id)
            if info is None:
                return None
            now = _utcnow()
            confirmed = self._info_confirmations.get(hospital_id)
            hira = info.backupCapacity
            capacity = info.bedCapacityByType or {}
            beds_by_type = info.bedsByType or {}
            by_field = info.bedReliabilityByType or {}

            def authority(payload: Any) -> float | None:
                match = bed_reliability.evaluate(payload, 0.0, now=now, horizon_sec=0.0, confirmed_at=confirmed)
                return round(match.authority, 3) if match is not None else None

            unknown = _is_bed_count_unknown(info)
            beds = [
                BackupBedRow(key="ER_ADULT", label="응급실(일반)", egenCapacity=capacity.get("ER_ADULT"),
                             available=None if unknown else self.effective_bed_count(info),
                             authority=authority(info.bedReliability)),
                BackupBedRow(key="ER_PEDIATRIC", label="응급실(소아)", egenCapacity=capacity.get("ER_PEDIATRIC"),
                             available=beds_by_type.get("ER_PEDIATRIC"), authority=authority(by_field.get("hv28"))),
                BackupBedRow(key="OR", label="수술실", hiraCapacity=hira.operatingRooms if hira else None,
                             egenCapacity=capacity.get("OR"), available=beds_by_type.get("OR"),
                             authority=authority(by_field.get("hvoc"))),
                BackupBedRow(key="ICU", label="중환자실", hiraCapacity=hira.icuTotal if hira else None,
                             egenCapacity=capacity.get("ICU"), available=beds_by_type.get("ICU"),
                             note="심평원 값은 중환자실 총량, E-Gen은 일반 중환자실만"),
                BackupBedRow(key="NICU", label="신생아 중환자실", hiraCapacity=hira.nicu if hira else None),
                BackupBedRow(key="WARD", label="입원실", hiraCapacity=hira.generalWard if hira else None,
                             authority=authority(by_field.get("hvgc"))),
            ]
            operating = info.equipmentOperating or {}
            owned = hira.equipment if hira else {}
            equipment = [
                BackupEquipmentRow(key=key, label=label, hiraCount=owned.get(hira_name) if hira_name else None,
                                   egenOperating=operating.get(key), note=note)
                for key, label, hira_name, note in BACKUP_EQUIPMENT
            ]
            return HospitalBackupView(
                hospitalId=hospital_id,
                name=info.name,
                emergencyLevel=info.emergencyLevel,
                beds=[row for row in beds if row.hiraCapacity is not None or row.egenCapacity is not None
                      or row.available is not None],
                equipment=[row for row in equipment if row.hiraCount is not None or row.egenOperating is not None],
                specialties=[s for s in info.specialties if s.doctorCount > 0],
                nursingGrade=hira.nursingGrade if hira else None,
                severeDeclarations=info.severeDeclarations,
                acceptanceMessages=_active_messages(info, now),
                inFlightCount=self._prune_and_count_overlay(hospital_id, now),
                egenUpdatedAt=info.updatedAt,
                hiraCollectedAt=hira.collectedAt if hira else None,
            )

    def case_group(self, case_id: str) -> str | None:
        """사건의 15개 중증질환군(예상 병명 → 키워드 규칙, disease_group.py). 매칭 전이거나 해당 없으면 None."""
        with self._lock:
            return self._case_group.get(case_id)

    def spider_features(self) -> list[dict]:
        """spider 거미줄 제안(GET /hospital-features, 2026-10-15)이 hub와 같은 병원 정보로 계산하도록 병원마다 넘기는 값.

        spider 엔진은 수집 시점 스냅샷(hospitals_xyz.json)으로 돌아 hub가 이미 만실로 아는 병원을 제안하곤 했다. 여기서
        hub가 순위에 쓰는 재료를 그대로 준다 — 응급실 가용(이송 확정 차감 반영)·미상·1일 넘은 값·정원·이송 중 건수(E-Gen),
        등급, 응급의학과 전문의 수(심평원), CT·혈관조영 운영(E-Gen), 질환군 "불가능" 신고(assessment declared_no)와 지금 유효한
        중증질환 차단 공지, 병상 정보 신뢰도 곡선(정보 생존 모델 — spider가 도착 시점 유효 확률로 병상 용량을 깎는 데 쓴다.
        hub 순위엔 여전히 안 쓴다). 순위·상태는 바꾸지 않는 읽기 전용이다."""
        with self._lock:
            now = _utcnow()
            out = []
            for info in self._hospitals.values():
                beds = self.effective_bed_count(info)
                unknown = _is_bed_count_unknown(info)
                stale = _is_bed_data_stale(info, now)
                em = next((s.doctorCount for s in info.specialties if s.department == "응급의학과"), None)
                equip = info.equipmentOperating or {}
                no_groups = sorted(
                    {g for g, sc in (info.assessment.groups.items() if info.assessment else []) if sc.tier == "declared_no"}
                    | {m.diseaseGroup for m in _active_messages(info, now) if m.kind == "severe" and m.diseaseGroup}
                )
                rel = None
                if info.bedReliability is not None:
                    confirmed = self._info_confirmations.get(info.hospitalId)
                    rel = {"predictedSurvivalSec": info.bedReliability.predictedSurvivalSec,
                           "bornAt": info.bedReliability.bornAt, "sigma": info.bedReliability.sigma,
                           "confirmedAt": confirmed.isoformat() if confirmed else None}
                out.append({
                    "hospitalId": info.hospitalId, "emergencyLevel": info.emergencyLevel,
                    "beds": None if (unknown or stale) else beds, "bedCountUnknown": unknown, "bedDataStale": stale,
                    "erCapacity": (info.bedCapacityByType or {}).get(_ER_ADULT), "inFlight": self.in_flight_count(info.hospitalId),
                    "emSpecialists": em, "ct": equip.get("CT"), "angio": equip.get("ANGIO"),
                    "noGroups": no_groups, "bedReliability": rel,
                })
            return out

    def list_hospitals(self) -> list[HospitalInfo]:
        """관제 지도(2026-10-03)에 병원 마커를 찍기 위한 전체 목록."""
        with self._lock:
            return list(self._hospitals.values())

    def list_case_results(self) -> list[HubMatchResult]:
        """진행 중 사건 전부(관제 지도 따라잡기, 2026-10-03). get_cases_for_hospital()과 같이 환자 수용이
        끝난 사건은 뺀다."""
        with self._lock:
            return [result for cid, result in self._case_results.items() if cid not in self._case_arrival]

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

    def apply_ambulance_roster(self, apids: list[str], busy: set[str] | None = None) -> tuple[list[str], list[str]]:
        """feature/info가 한 주기에 보낸 구급차 전체 목록(2026-10-04). 여기 없는 구급차를 레지스트리에서 뺀다 —
        Supabase ambulances 테이블을 통째로 바꿔도(시연용 3대 → 서울 119 구급차) 옛 구급차가 hub 메모리·상태
        파일에 계속 남던 문제. apply_hospital_roster와 같은 방어: 목록이 비었거나 지금의 절반 미만이면 아무것도
        안 빼고(조회 실패·일부만 온 경우), 진행 중 사건이 있거나 busy(출동 시뮬레이션 중)인 구급차는 남긴다.
        돌려주는 값은 (뺀 apid, 남긴 apid)."""
        roster = set(apids)
        busy = busy or set()
        with self._lock:
            missing = [apid for apid in self._ambulances if apid not in roster]
            if not missing or not roster or len(roster) < len(self._ambulances) / 2:
                return [], missing
            in_use = {apid for cid, apid in self._case_apid.items() if cid not in self._case_arrival} | busy
            removed = [apid for apid in missing if apid not in in_use]
            kept = [apid for apid in missing if apid in in_use]
            for apid in removed:
                del self._ambulances[apid]
                self._gps_override.pop(apid, None)
            if removed:
                self._dirty = True
            return removed, kept

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
        """이 hospitalId가 후보로 들어있는 진행 중 사건(따라잡기용, app.py `_send_catchup()`). 환자 수용이 끝난
        사건(도착 결과 accepted)은 뺀다 — 화면에서는 이미 지웠다(case_closed). 기록·병상 차감 때문에 엔진에는
        확정 60분 동안 남는다."""
        with self._lock:
            return [
                result
                for cid, result in self._case_results.items()
                if cid not in self._case_arrival and any(h.hospitalId == hospital_id and can_receive(h) for h in result.hospitals)
            ]

    def get_cases_for_apid(self, apid: str) -> list[HubMatchResult]:
        """이 apid(구급차)가 등록한 사건 전부를 돌려준다. 구급차는 실제로는
        한 번에 사건 하나만 진행하지만(voice 마이크가 한 대뿐이라), 같은
        방식으로 여러 건이 나와도 안전하게 동작하도록 리스트로 반환한다."""
        with self._lock:
            case_ids = [
                cid for cid, registered_apid in self._case_apid.items()
                if registered_apid == apid and cid not in self._case_arrival  # 수용이 끝난 사건은 뺀다
            ]
            results = [self._case_results.get(cid) for cid in case_ids]
            return [result for result in results if result is not None]

    def get_case_ids_for_apid(self, apid: str) -> list[str]:
        """이 구급차의 진행 중 사건 id — 매칭 결과가 아직 없는(출동·통화 중) 사건도 포함, 수용이 끝난 사건은 뺀다."""
        with self._lock:
            return [cid for cid, a in self._case_apid.items() if a == apid and cid not in self._case_arrival]

    def list_case_ids(self) -> list[str]:
        """엔진이 들고 있는 사건 전부(확정·미확정·결과 전 사건 포함)."""
        with self._lock:
            return list(set(self._case_results) | set(self._case_apid))

    def list_open_case_ids(self) -> list[str]:
        """아직 끝나지 않은 사건(환자 수용으로 끝난 사건 제외 — 그건 화면에서 이미 지웠고 기록용으로만 60분 남는다)."""
        with self._lock:
            return [cid for cid in set(self._case_results) | set(self._case_apid) if cid not in self._case_arrival]

    def get_unconfirmed_case_ids(self) -> list[str]:
        """확정 전 사건(재시작 뒤 정리용)."""
        with self._lock:
            return [cid for cid in self._case_results if cid not in self._case_confirmed_at]

    def get_active_case_ids(self) -> list[str]:
        """매칭 결과가 있는(주기적 재계산 대상) 사건 목록."""
        with self._lock:
            return [cid for cid in self._case_results if cid in self._case_voice]

    # ── 정리 · 병상 오버레이 ──────────────────────────────────────────────────

    def prune_expired_cases(self) -> list[str]:
        """주기 루프가 부른다(2026-10-01). 예전엔 새 통화 요약·승인 액션이 들어올 때만 정리해서,
        새 사건이 없으면 확정된 지 60분 넘은 사건이 따라잡기로 계속 화면에 떴다."""
        return self._prune_old_cases()

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
        self._spider_pick.pop(case_id, None)
        self._case_gps_fallback.pop(case_id, None)
        self._case_confirmed_at.pop(case_id, None)
        self._case_arrival.pop(case_id, None)
        self._case_prev_calls.pop(case_id, None)
        self._case_override.pop(case_id, None)
        self._case_extra_notes.pop(case_id, None)
        self._case_excluded = {k for k in self._case_excluded if k[0] != case_id}
        for key in [k for k in self._reject_reason if k[0] == case_id]:
            del self._reject_reason[key]
        for key in [k for k in self._case_overlay if k[0] == case_id]:
            del self._case_overlay[key]

    def close_case(self, case_id: str, include_confirmed: bool = False) -> bool:
        """확정 없이 끝난 사건(방치 정리·현장 종료)을 캐시·따라잡기·주기 재계산에서 뺀다
        (2026-10-01). 예전엔 확정된 사건만 60분 뒤 지워서, 취소·중단된 사건이 병원 대시보드
        따라잡기 목록에 영원히 떴다. 이송 확정된 사건은 기본적으로 지우지 않는다(기존 60분 정리를
        따른다). include_confirmed=True면 확정 사건도 지운다(출동 시뮬레이션 재시작, 2026-10-03) —
        병상 차감(_bed_overlay)은 병원 단위로 따로 남아 BED_HOLD_* 규칙대로 풀리므로 사건을 지워도 그대로다.
        지웠으면 True."""
        with self._lock:
            if case_id in self._case_confirmed_at and not include_confirmed:
                return False
            existed = case_id in self._case_results or case_id in self._case_apid
            self._drop_case_locked(case_id)
            if existed:
                self._dirty = True
            return existed

    def _prune_and_count_overlay(self, hospital_id: str, now: datetime) -> int:
        """풀 차감을 걷어내고 아직 유효한 개수를 돌려준다(락 안에서만 호출). 상한이 지났거나, 최소 유지가 끝났고
        E-Gen 응급실 원값이 확정 당시(baseline)보다 줄어 있으면 푼다. 줄어든 만큼만 푼다 — 먼저 확정된 것부터 풀고,
        풀 때마다 그 1석을 "써 버린" 것으로 남은 차감들의 baseline을 1 낮춘다(다음 조회 때 같은 감소로 또 풀리지
        않게). 단 지금 E-Gen 값 아래로는 낮추지 않는다 — 이미 줄어든 값으로 확정된 차감까지 깎으면 그 환자가
        반영돼도 풀리지 않는다."""
        holds = self._bed_overlay.get(hospital_id)
        if not holds:
            return 0
        info = self._hospitals.get(hospital_id)
        current = None if info is None or _is_bed_count_unknown(info) else info.availableBedCount
        kept: list[BedHold] = []
        ordered = sorted(holds, key=lambda h: h.confirmed_at)
        for i, hold in enumerate(ordered):
            if now >= hold.expires_at:
                self._log_hold_released(hospital_id, hold, "max_age", current)
            elif (
                current is not None and hold.baseline is not None and now >= hold.hold_until
                and hold.baseline - current >= 1
            ):
                self._log_hold_released(hospital_id, hold, "egen_reflected", current)
                for later in ordered[i + 1:]:
                    if later.baseline is not None:
                        later.baseline = max(current, later.baseline - 1)
            else:
                kept.append(hold)
                continue
            for key in [k for k, v in self._case_overlay.items() if v is hold]:
                del self._case_overlay[key]
            self._dirty = True
        if kept:
            self._bed_overlay[hospital_id] = kept
        else:
            del self._bed_overlay[hospital_id]
        return len(kept)

    @staticmethod
    def _log_hold_released(hospital_id: str, hold: BedHold, cause: str, current: int | None) -> None:
        """차감이 풀린 이유를 남긴다 — 유지 시간 상수를 도착 결과 로그와 대조해 다시 맞출 재료다."""
        decision_log.log_decision("bed_hold_released", {
            "hospitalId": hospital_id, "cause": cause, "egenNow": current, "hold": hold.to_json(),
        })

    def effective_bed_count(self, info: HospitalInfo) -> int:
        """TTL 오버레이가 적용된 실제 표시용 병상 수. 0 미만으로는 안 내려간다
        — 같은 병원에 짧은 시간 안에 여러 사건이 동시에 확정되는 극단적인
        경우에도 dashboard에 음수 병상이 뜨지 않게 한다."""
        with self._lock:
            overlay = self._prune_and_count_overlay(info.hospitalId, _utcnow())
            return max(0, info.availableBedCount - overlay)

    def in_flight_count(self, hospital_id: str) -> int:
        """이 병원으로 확정돼 아직 TTL 안에 있는 이송 건수(병원 단위 — 사건 무관).
        부하 페널티(scoring.load_penalty_min)와 관제 지도 표시가 쓴다(2026-10-03)."""
        with self._lock:
            return self._prune_and_count_overlay(hospital_id, _utcnow())

    # ── 승인 액션 ─────────────────────────────────────────────────────────────

    def _refresh_match(
        self, case_id: str, match: HospitalMatch, status: HospitalStatus, now: datetime
    ) -> HospitalMatch:
        """캐시된 HospitalMatch 하나를 지금 상태(승인 상태·병상·만실 판정)로 다시 맞춘다."""
        update: dict[str, Any] = {"status": status, "rejectReason": self._reject_reason_for(case_id, match.hospitalId, status),
                                  "excluded": (case_id, match.hospitalId) in self._case_excluded}
        info = self._hospitals.get(match.hospitalId)
        if info is not None:
            beds = self.effective_bed_count(info)
            unknown = _is_bed_count_unknown(info)
            stale = _is_bed_data_stale(info, now)
            capacity, occupancy = _er_capacity(info, beds, unknown, stale)
            update.update(
                availableBedCount=beds,
                bedCountUnknown=unknown,
                bedDataStale=stale,
                erBedCapacity=capacity,
                erOccupancyPct=occupancy,
                demoteReasons=_demote_reasons(
                    info, self._case_group.get(case_id), status, beds, unknown, stale, now
                ),
            )
            update["unavailableReason"] = _unavailable_reason(status, update["demoteReasons"])
        elif status == "rejected":
            update["demoteReasons"] = ["rejected"]
        return match.model_copy(update=update)

    def _reject_reason_for(self, case_id: str, hospital_id: str, status: HospitalStatus) -> str | None:
        return self._reject_reason.get((case_id, hospital_id)) if status == "rejected" else None

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

    def apply_approval_action(self, action: ApprovalAction) -> bool:
        """dashboard가 보낸 승인 액션을 반영한다 (dashboard는 이 브랜치와만 직접
        통신하므로 수신은 여기서 한다). hospitals[].status에 반영될 내부 상태를
        갱신하고, 병상이 실제로 줄어드는 경우(final_approval)에는 TTL 오버레이에
        차감 기록을 얹는다. 실제로 반영했으면 True, 거부·중복이면 False.
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
                return False

            # 순서·권한 검사(2026-09-28). 거부된 액션은 상태를 바꾸지 않고 사유만 남긴다.
            # - 주체 짝: 병원 승인·거절은 병원, 이송 승인은 구급대원
            # - 이송 승인은 병원이 이 사건에 승인(approved)한 병원에만 — "병원의 승인은 후보
            #   등록, 구급대원의 이송 승인이 최종 확정"(CLAUDE.md) 순서를 지킨다
            refuse_reason = None
            # 관제 대행(2026-11-01): 이송 승인은 관제(dispatcher)도 보낼 수 있다. 소켓이 관제인지는 app이 확인한다.
            if action.actor != _ACTION_ACTOR[action.action] and not (
                    action.action == "final_approval" and action.actor == "dispatcher"):
                refuse_reason = f"actor mismatch: {action.action} requires {_ACTION_ACTOR[action.action]}"
            elif action.action in ("hospital_approve", "hospital_reject", "final_approval") and (
                (result := self._case_results.get(action.caseId)) is not None
                and not any(h.hospitalId == action.hospital_id and can_receive(h) for h in result.hospitals)
            ):
                refuse_reason = "hospital is not a KTAS-compatible dispatch target"
            elif action.action == "final_approval" and current != "approved":
                refuse_reason = f"final_approval requires hospital approval (current: {current})"
            elif action.action == "hospital_approve" and self._is_confirmed_full(action.hospital_id):
                # 응급실 병상 0이 확인된 병원은 승인을 받지 않는다(2026-10-01). 화면에서만 막으면 승인이 통과해
                # 구급차 화면에 이송 승인이 열렸다. 미상·오래된 값은 막지 않는다(미상으로 막으면 뺑뺑이가 는다).
                refuse_reason = "hospital_approve refused: ER beds confirmed 0 (E-Gen)"
            elif action.action.startswith("arrival_") and current != "confirmed":
                refuse_reason = f"{action.action} requires this hospital to be the confirmed destination (current: {current})"
            elif action.action.startswith("arrival_") and action.caseId in self._case_arrival:
                refuse_reason = "arrival result already recorded"
            elif action.action == "transport_withdraw" and current != "confirmed":
                refuse_reason = f"transport_withdraw requires this hospital to be the confirmed destination (current: {current})"
            elif action.action == "transport_withdraw" and action.caseId in self._case_arrival:
                refuse_reason = "already arrived and accepted"
            elif action.action in ("hospital_approve", "final_approval") and status_key in self._case_excluded:
                # 도착 후 수용 불가·이송 중 철회로 이 사건에서 빠진 병원 — 같은 사건엔 다시 붙이지 않는다(2026-10-05)
                refuse_reason = f"{action.action} refused: hospital excluded from this case"
            if refuse_reason is not None:
                decision_log.log_decision(
                    "approval_action_refused", {"action": action.model_dump(), "reason": refuse_reason}
                )
                return False

            if action.action == "arrival_accepted":
                # 실제 수용 — 이송이 끝났다. status는 confirmed 그대로, 결과만 기록한다.
                arrival = ArrivalResult(hospitalId=action.hospital_id, result="accepted", at=action.timestamp)
                self._case_arrival[action.caseId] = arrival
                # 병상 차감의 기준을 예상 도착에서 실제 도착(지금)으로 다시 잡는다 — 병원은 이제부터 입력한다
                hold = self._case_overlay.get(status_key)
                if hold is not None:
                    hold.hold_until, hold.expires_at = _bed_hold_window(_utcnow(), 0.0)
                    self._dirty = True
                cached = self._case_results.get(action.caseId)
                if cached is not None:
                    self._case_results[action.caseId] = cached.model_copy(update={"arrival": arrival})
                decision_log.log_decision("arrival_accepted", {"action": action.model_dump()})
                return True
            if action.action in _EXCLUDING_CAUSES:
                # 도착 후 수용 불가 — 가장 강한 "정보가 틀렸다" 관측. 이송 중 수용 철회(2026-10-05)도 같은 처리:
                # 확정을 풀고(거절로) 병상 차감을 회수하며, 사건은 다시 미확정이 된다(재선택·재계산 대상).
                # 그 병원은 이 사건에서 제외한다. 도착 결과는 "수용"만 최종이라 _case_arrival엔 넣지 않는다.
                self._reject_reason[status_key] = action.reason or "UNSPECIFIED"
                self._case_excluded.add(status_key)
                self._release_confirmation(action.caseId, action.hospital_id, action, action.action)
                self._case_confirmed_at.pop(action.caseId, None)
                return True

            if action.action == "final_approval":
                # 재선택: 이 사건에서 이미 확정된 다른 병원이 있으면 확정을 풀고(approved로
                # 되돌림 — 병원의 승인 자체는 유효) 그 확정이 얹은 병상 차감을 회수한다.
                # 새 상태값을 만들지 않는 건 dashboard의 HospitalStatus 타입을 그대로 쓰기 위해서다.
                for (cid, hid), status in list(self._approval_status.items()):
                    if cid == action.caseId and hid != action.hospital_id and status == "confirmed":
                        self._release_confirmation(cid, hid, action, "paramedic_reselect")

            new_status = _ACTION_TO_STATUS[action.action]
            self._approval_status[status_key] = new_status
            if action.action == "hospital_reject":
                self._reject_reason[status_key] = action.reason or "UNSPECIFIED"
            else:
                self._reject_reason.pop(status_key, None)
            if new_status == "confirmed":
                # 이송 확정 시각을 기록해둔다 — _prune_old_cases()가 이 시각을 기준으로
                # CASE_RETENTION_MIN이 지난 사건을 캐시에서 걷어낸다. 병상이 안 깎인
                # 확정(skip_reason 경로)이어도 사건이 끝난 건 같으므로 여기서 기록한다.
                self._case_confirmed_at[action.caseId] = _utcnow()

            if action.action != "final_approval":
                # 병상은 안 건드리는 액션이라 지금 self._hospitals 값 그대로 패치해도 된다.
                self._patch_case_result_status(action.caseId, action.hospital_id, new_status)
                decision_log.log_decision("approval_action_applied", {"action": action.model_dump(), "bedUpdate": None})
                return True

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
                return True

            now = _utcnow()
            cached = self._case_results.get(action.caseId)
            match = next((h for h in cached.hospitals if h.hospitalId == info.hospitalId), None) if cached else None
            travel_min = match.travelMin if match is not None and match.travelMin is not None else BED_HOLD_DEFAULT_TRAVEL_MIN
            hold_until, expires_at = _bed_hold_window(now, travel_min)
            hold = BedHold(action.caseId, now, hold_until, expires_at, info.availableBedCount)
            self._bed_overlay.setdefault(info.hospitalId, []).append(hold)
            self._case_overlay[status_key] = hold
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
                        "travelMin": travel_min,
                        **hold.to_json(),
                    },
                },
            )
            return True

    def _release_confirmation(self, case_id: str, hospital_id: str, action: ApprovalAction, cause: str) -> None:
        """확정을 풀고 병상 차감을 회수한다(락 안에서만 호출).

        cause별 의미가 다르다 — 신뢰도 라벨을 만들 때 섞으면 안 된다(2026-10-01):
        - paramedic_reselect: 더 나은 병원이 승인해 구급대원이 바꿨다. 이 병원은 받겠다고 했으므로
          **병상 정보가 맞았다는 근거**다(실패 아님). 상태는 approved로 되돌린다.
        - arrival_refused: 도착했는데 병원이 못 받았다. **정보가 틀렸다는 가장 강한 독립 관측.**
          상태는 rejected.
        """
        new_status = "rejected" if cause in _EXCLUDING_CAUSES else "approved"
        self._approval_status[(case_id, hospital_id)] = new_status
        hold = self._case_overlay.pop((case_id, hospital_id), None)
        overlay = self._bed_overlay.get(hospital_id, [])
        reclaimed = hold is not None and hold in overlay  # 이미 풀려 정리됐으면 회수할 것이 없다
        if reclaimed:
            overlay.remove(hold)
            if not overlay:
                del self._bed_overlay[hospital_id]
        result = self._case_results.get(case_id)
        snapshot = {
            h.hospitalId: {"travelMin": h.travelMin, "finalScore": h.finalScore}
            for h in (result.hospitals if result else [])
            if h.hospitalId in (hospital_id, action.hospital_id)
        }
        self._patch_case_result_status(case_id, hospital_id, new_status)
        decision_log.log_decision(
            cause if cause in _EXCLUDING_CAUSES else "approval_released",
            {
                "caseId": case_id,
                "hospitalId": hospital_id,
                "cause": cause,
                "newHospitalId": action.hospital_id if cause == "paramedic_reselect" else None,
                "reason": action.reason,
                "atDecision": snapshot,
                "bedOverlayReclaimed": reclaimed,
            },
        )

    # ── 존 · 후보 ─────────────────────────────────────────────────────────────

    def reject_ratio(self, case_id: str, ambulance_gps: GpsPoint, max_zone: int) -> float:
        """현재 존(1~max_zone) 안 **KTAS 전달 대상 전체** 대비 명시적으로 거절(rejected)한 병원의 비율.
        시간 기반이 아닌 거절 비율 기반 존 확장 판단에 쓴다. 후보가 없으면 0.0(빈 존은 따로 넓힌다).

        2026-10-01: 분모를 "응답한 병원"에서 "존 안 후보 전체"로 바꿨다. 예전엔 첫 응답이 거절이면 1/1 = 100%라
        후보가 10곳이어도 한 곳의 거절로 바로 넓어졌다. 지금은 10곳 중 4곳(40%)이 거절해야 넓어진다.
        """
        with self._lock:
            candidates = self._dispatch_candidates(case_id, ambulance_gps, max_zone)
            statuses = [self._approval_status.get((case_id, info.hospitalId), "pending") for info, _ in candidates]
        if not statuses:
            return 0.0
        return sum(1 for s in statuses if s == "rejected") / len(statuses)

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

    def _dispatch_candidates(self, case_id: str, ambulance_gps: GpsPoint, max_zone: int,
                             voice: VoiceCallSummaryMessage | None = None) -> list[tuple[HospitalInfo, float]]:
        """첫 매칭·재계산·존 확장에 같은 KTAS/질환군 규칙을 쓴다. 병원의 명시적 승인이 우선이다."""
        with self._lock:
            voice = voice or self._case_voice.get(case_id)
            candidates = self._candidates_in_zone(ambulance_gps, max_zone)
            if voice is None:
                return candidates  # 통화 전에는 KTAS가 없어 지리 후보를 유지한다.
            k, cond = spider_rule.patient_of(voice.summary.ktas_level, voice.summary.severity_tag,
                                           voice.summary.mechanism, voice.summary.trauma)
            hour = spider_rule.local_hour(_utcnow())
            return [(info, distance) for info, distance in candidates
                    if self._approval_status.get((case_id, info.hospitalId)) in ("approved", "confirmed")
                    or spider_rule.ktas_suitability(k, cond, info, hour)["eligible"]]

    def _dispatch_zone(self, voice: VoiceCallSummaryMessage, gps: GpsPoint, start: int, cap: int = 10) -> int:
        """현재 존에 맞는 병원이 없으면 최대 50km까지 검색. 부적합 병원으로 우회 전달하지 않는다."""
        candidates = self._dispatch_candidates(voice.caseId, gps, max(start, cap), voice)
        needed = min((zone_of(distance) for _, distance in candidates), default=max(start, cap))
        zone = max(start, needed)
        if zone > start:
            decision_log.log_decision("zone_expanded", {"caseId": voice.caseId, "from": start, "to": zone,
                                                       "cause": "ktas_no_eligible", "source": "rule"})
        return zone

    def build_zone_candidates(self, ambulance_gps: GpsPoint, max_zone: int = 1) -> list[dict]:
        """1단계: voice 정보가 도착하기 전, GPS+병원 정보만으로 존 기반 후보 리스트를
        만들어 보관해둔다. 진료과 매칭 없이 거리만으로 정렬한 중간 상태를 반환한다.

        2026-10-03: 후보마다 병상 신뢰도(bedReliability, AI)를 얹고 "첫 연락 추천"
        (firstCallRecommended) 한 곳을 고른다 — 빈 병상이 실제로 확인됐고(미상·확인된
        만실·1일 넘은 묵은 값 제외) 도착 시점 유효 확률(rArrive)이 가장 높은 병원,
        동률이면 가까운 쪽. 신뢰도를 finalScore에 안 쓴다는 원칙은 그대로다 — 첫 통화
        상대 제안은 틀려도 통화 뒤 존 전체 동시 전달이 뒤를 받치는 비용 낮은 결정이라,
        검증 전의 확률을 써도 되는 유일한 자리다. 거리순 정렬 자체는 바꾸지 않는다.
        """
        now = _utcnow()
        candidates = self._candidates_in_zone(ambulance_gps, max_zone)
        # 2026-10-03: 직선거리 대신 카카오 내비 기준(도로 거리·소요 시간)으로 정렬·표시한다. ETA를 못 받은
        # 병원(키 없음·반경 10km 밖·조회 실패)만 직선거리 × 같은 사건의 분/km 보정으로 추정한다(매칭과 같은 규칙).
        etas = (
            self._router.etas(ambulance_gps, {info.hospitalId: info.gps for info, _ in candidates})
            if self._router is not None and candidates
            else {}
        )
        min_per_km = calibrate_min_per_km(
            [(distance, etas[info.hospitalId][0] / 60.0) for info, distance in candidates if info.hospitalId in etas]
        )

        def travel_min_of(pair: tuple) -> float:
            info, distance = pair
            eta = etas.get(info.hospitalId)
            return eta[0] / 60.0 if eta is not None else distance * min_per_km

        candidates.sort(key=travel_min_of)
        rows: list[dict] = []
        best_index: int | None = None
        best_r_arrive = 0.0
        for info, distance in candidates:
            beds = self.effective_bed_count(info)
            unknown = _is_bed_count_unknown(info)
            eta = etas.get(info.hospitalId)
            travel_min = travel_min_of((info, distance))
            # 도착 시점(horizon)은 정렬에 쓴 이동 시간과 같은 값(매칭과 같은 규칙)
            rel = bed_reliability.evaluate(
                info.bedReliability, distance, now=now, horizon_sec=travel_min * 60.0,
                confirmed_at=self.get_info_confirmation(info.hospitalId),
            )
            rows.append(
                {
                    "hospitalId": info.hospitalId,
                    "name": info.name,
                    "distanceKm": round(distance, 2),
                    # 내비 기준(2026-10-03). 못 받았으면 None — 화면은 직선거리를 "추정"으로 표시한다.
                    "roadDistanceKm": round(eta[1] / 1000.0, 2) if eta is not None else None,
                    "etaMin": _ceil_minutes(eta[0]) if eta is not None else None,
                    "travelMin": round(travel_min, 1),
                    "travelBasis": "eta" if eta is not None else "estimate",
                    "gps": info.gps.model_dump(),
                    "availableBedCount": beds,
                    "bedCountUnknown": unknown,
                    "bedReliability": rel.model_dump() if rel is not None else None,
                    "firstCallRecommended": False,
                    # 통화 전에는 질환군 미확정: 일반 조건의 KTAS 적합도만 전달한다.
                    "supportedKtas": spider_rule.ktas_suitability(3, "general", info, spider_rule.local_hour(now))["supportedKtas"],
                    "ktasSource": "rule",
                    "ktasClinicallyValidated": False,
                    # 구급대가 전화 상대를 고를 때 바로 보는 정보(2026-10-04) — 등급·진료과
                    "emergencyLevel": info.emergencyLevel,
                    "specialties": [
                        {"department": s.department, "doctorCount": s.doctorCount} for s in info.specialties
                    ],
                }
            )
            if rel is not None and beds >= 1 and not unknown and not _is_bed_data_stale(info, now):
                if rel.rArrive > best_r_arrive:  # 동률이면 먼저 담긴(더 빨리 닿는) 쪽 유지
                    best_r_arrive, best_index = rel.rArrive, len(rows) - 1
        if best_index is not None:
            rows[best_index]["firstCallRecommended"] = True
        return rows

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

        # 진료과 매칭(임베딩) + info-v2 15개 질환군 중 이번 사건에 해당하는 것 하나(키워드 규칙, 없으면 None —
        # disease_group.py). 질환군은 사건 전체에 하나뿐이고 finalScore에 안 들어가며 설명·declared_no 판정에만
        # 쓰인다. 예전엔 질환군도 임베딩으로 골라 어떤 환자든 엉뚱한 질환군이 붙었다(2026-10-02).
        department_lists = [[s.department for s in info.specialties] for info, _ in candidates]
        with self._matcher_lock:
            specialty_results = self._matcher.match_many(expected_diagnosis, department_lists)
        best_group = match_group(expected_diagnosis, _assessment_vocabulary([info for info, _ in candidates]))

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
            # spider 매칭 규칙(2026-10-15, spider_rule.py): 환자 = (KTAS, 질환군), 시각(야간 감점), 이송 중 중증 수(μ 감쇠)
            sp_k, sp_cond = spider_rule.patient_of(
                voice.summary.ktas_level, voice.summary.severity_tag, expected_diagnosis, voice.summary.trauma
            )
            sp_hour = spider_rule.local_hour(now)
            sp_severe = self._spider_inflight_severe(voice.caseId)
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
                status = self._approval_status.get((voice.caseId, info.hospitalId), "pending")
                beds = self.effective_bed_count(info)
                unknown = _is_bed_count_unknown(info)
                stale = _is_bed_data_stale(info, now)
                # 이송 중 부하 페널티(2026-10-03): 이 병원으로 확정돼 아직 TTL 안에 있는
                # 건수(병원 단위 — 다른 사건 포함)만큼 이동시간에 분을 더한다. 평시엔 0.
                in_flight = self._prune_and_count_overlay(info.hospitalId, now)
                load_min, load_reason = load_penalty_min(in_flight, beds, unknown)
                # 응급실 포화도 페널티(2026-10-07): 차감 전 E-Gen 값 기준 — 이송 중 환자는 위 부하 페널티가 센다.
                occupancy_min, occupancy_reason = occupancy_penalty_min(
                    _er_capacity(info, info.availableBedCount, unknown, stale)[1]
                )
                # 병원의 "현재 정보 확인" 이력 — 현재 claim에 유효한지는
                # evaluate()가 bornAt과 대조해 판단한다.
                confirmed = self._info_confirmations.get(info.hospitalId)
                er_capacity, er_occupancy = _er_capacity(info, beds, unknown, stale)
                # spider 줄 길이 = 도로 분 − μ×이득(또는 + ν×모자람) + 부하. 진료과 임베딩 점수는 이 모델에 없어 순위에 안 쓴다
                sp = spider_rule.line(sp_k, sp_cond, info, travel_min, load_min + occupancy_min, sp_severe, sp_hour)
                sp_window = (
                    self._spider_window(voice.caseId, info.hospitalId, now + timedelta(minutes=travel_min), sp_k)
                    if sp["len"] is not None and status == "pending" else []
                )
                bonus_min = round(sp["gain_min"], 1)
                bonus_reasons = [f"거미줄 {spider_rule.COND_LABEL[sp_cond]} K{sp_k} · {sp['parts']}"] + spider_rule.gain_reasons(sp, sp_k) + (
                    [f"줄 없음({sp['blocked']}) — 뒤로"] if sp["blocked"] else
                    [f"줄 길이 {sp['len']:.1f}분 (도로 {travel_min:.1f} − 이득 {sp['gain_min']:.1f} + 부하 {load_min + occupancy_min:.1f})"]
                ) + (
                    # τ 창은 사실만 알린다(2026-10-22) — 순위를 내리지도, 병원을 건너뛰지도 않는다. 수용 판단은 병원이.
                    [f"같은 10분 안에 도착 예정인 다른 사건 {len(sp_window)}건 — 순위 영향 없음, 수용 판단은 병원"]
                    if sp_window else []
                )
                matches.append(
                    HospitalMatch(
                        hospitalId=info.hospitalId,
                        name=info.name,
                        gps=info.gps,
                        distanceKm=round(distance, 2),
                        zone=zone_of(distance),
                        specialtyMatch=SpecialtyMatch(
                            department=best_dept, score=round(similarity, 4), basis=basis, doctorCount=doctor_count
                        ),
                        availableBedCount=beds,
                        bedCountUnknown=unknown,
                        erBedCapacity=er_capacity,
                        erOccupancyPct=er_occupancy,
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
                        roadDistanceKm=round(eta[1] / 1000.0, 2) if eta is not None else None,
                        finalScore=spider_rule.score(sp["len"], travel_min, load_min + occupancy_min),
                        spiderLen=round(sp["len"], 1) if sp["len"] is not None else None,
                        spiderGap=round(sp["gap"], 2),
                        spiderBlocked=sp["blocked"],
                        ktasSuitability=spider_rule.ktas_suitability(sp_k, sp_cond, info, sp_hour),
                        spiderWindow=sp_window or None,
                        emergencyLevel=info.emergencyLevel,
                        travelBonusMin=round(bonus_min, 1),
                        bonusReasons=bonus_reasons,
                        inFlightCount=in_flight,
                        loadPenaltyMin=load_min,
                        loadReason=load_reason,
                        occupancyPenaltyMin=occupancy_min,
                        occupancyReason=occupancy_reason,
                        travelMin=round(travel_min, 1),
                        travelBasis="eta" if eta is not None else "estimate",
                        acceptanceMessages=_acceptance_messages_for(info, best_group, required, now),
                        demoteReasons=(demote := _demote_reasons(info, best_group, status, beds, unknown, stale, now)),
                        rejectReason=self._reject_reason_for(voice.caseId, info.hospitalId, status),
                        unavailableReason=_unavailable_reason(status, demote),
                        bedDataStale=stale,
                        excluded=(voice.caseId, info.hospitalId) in self._case_excluded,
                    )
                )

            # 구급차 대시보드 상단바 표시용. 이 사건의 apid를 register_case()로
            # 기억해둔 값에서 찾아, 구급차 레지스트리의 이름을 그대로 붙인다.
            apid = self._case_apid.get(voice.caseId)
            ambulance = self.get_ambulance(apid) if apid else None

        result = HubMatchResult(
            caseId=voice.caseId,
            patientInfo=self._patient_info(voice),
            zoneActive=active_zones(max_zone),
            hospitals=_sort_matches(matches),
            source="rule",
            ambulanceName=ambulance.name if ambulance is not None else None,
            apid=apid,
            ambulanceGps=ambulance_gps,
            ambulanceGpsFallback=gps_fallback,
            arrival=self._case_arrival.get(voice.caseId),
        )
        self._spider_record_pick(voice.caseId, result, sp_k, now)
        return result, best_group

    # ── spider 매칭 규칙: τ 창 표시(2026-10-15 충돌·양보 → 2026-10-22 표시만) ─────────────────
    # 사건마다 지금 잡은 줄(가장 앞 병원)을 기억해 두고, 다른 사건을 계산할 때 그 병원의 같은 τ 창에 (a) 이미 이송
    # 확정된 사건과 (b) 우선하는(KTAS 낮은 숫자, 같으면 먼저 닿는) 사건이 있으면 `spiderWindow`에 적는다.
    # ⚠ **순위에는 쓰지 않는다**(2026-10-22) — 예전엔 한도(2)가 차면 그 병원을 건너뛰고 밀린 사건이 다음 병원으로
    # 줄을 옮겼다(spider의 "양보"). 실측(창 켜면 거절 46→51·56→65)과 임상 자문("둘 다 받으려 노력한다")이 같은
    # 방향이라 걷어냈다 — spider_rule.py 모듈 설명 ⚠ · poc/CLINICAL_CONVERGENCE.md §3.
    def _spider_ktas(self, case_id: str) -> int:
        voice = self._case_voice.get(case_id)
        if voice is None:
            return 3
        k, _ = spider_rule.patient_of(voice.summary.ktas_level, voice.summary.severity_tag, voice.summary.mechanism, None)
        return k

    def _spider_confirmed(self, case_id: str) -> tuple[str, datetime] | None:
        """이송 확정 사건의 (병원, 도착 예정 시각)."""
        at = self._case_confirmed_at.get(case_id)
        result = self._case_results.get(case_id)
        if at is None or result is None:
            return None
        match = next((h for h in result.hospitals if h.status == "confirmed"), None)
        if match is None:
            return None
        return match.hospitalId, at + timedelta(minutes=match.travelMin or 0.0)

    def _spider_inflight_severe(self, case_id: str) -> int:
        """이송 중(확정됨) 중증(KTAS 1·2) 사건 수 — μ 감쇠(중증이 몰리면 센터를 아낀다)."""
        return sum(1 for other in list(self._case_results) if other != case_id
                   and self._spider_confirmed(other) is not None and self._spider_ktas(other) <= 2)

    def _spider_window(self, case_id: str, hospital_id: str, arrival: datetime, k: int) -> list[str]:
        """이 병원의 같은 τ 창(도착 시각 ±τ)에 먼저 자리를 가진 다른 사건들 — 확정 사건 전부 + 우선하는 사건의 줄."""
        me = (k, arrival, case_id)
        members = []
        for other in list(self._case_results):
            if other == case_id:
                continue
            fixed = self._spider_confirmed(other)
            if fixed is not None:
                hid, arr = fixed
            else:
                pick = self._spider_pick.get(other)
                if pick is None or not spider_rule.outranks((pick["k"], pick["arrival"], other), me):
                    continue
                hid, arr = pick["hospitalId"], pick["arrival"]
            if hid == hospital_id and abs((arr - arrival).total_seconds()) <= spider_rule.TAU_MIN * 60:
                members.append(other)
        return members

    def _spider_record_pick(self, case_id: str, result: HubMatchResult, k: int, now: datetime) -> None:
        """이 사건이 지금 잡은 줄 = 정렬 맨 앞의 받을 수 있는 병원(판단 대기·승인, 내림·벽·제외 없음).
        창이 찼는지는 보지 않는다(2026-10-22) — 창은 표시용이라 줄 선택을 바꾸지 않는다."""
        with self._lock:
            if any(h.status == "confirmed" for h in result.hospitals):
                self._spider_pick.pop(case_id, None)
                return
            for h in result.hospitals:
                if (h.status in ("pending", "approved") and not h.demoteReasons and h.spiderBlocked is None
                        and not h.excluded):
                    self._spider_pick[case_id] = {"hospitalId": h.hospitalId, "k": k,
                                                  "arrival": now + timedelta(minutes=h.travelMin or 0.0)}
                    return
            self._spider_pick.pop(case_id, None)

    def spider_priority_order(self, case_ids: list[str]) -> list[str]:
        """재계산 순서 — 우선하는 사건(KTAS 낮은 숫자, 같으면 먼저 닿는)부터. 앞 사건의 줄이 정해진 뒤 뒷 사건이
        계산돼야 τ 창 표시(`spiderWindow`)가 한 번에 맞는다. 순위 자체는 이 순서에 영향받지 않는다(2026-10-22)."""
        far = datetime.max.replace(tzinfo=timezone.utc)
        with self._lock:
            def key(cid: str) -> tuple:
                pick = self._spider_pick.get(cid)
                return (self._spider_ktas(cid), pick["arrival"] if pick else far, cid)
            return sorted(case_ids, key=key)

    def _patient_info(self, voice: VoiceCallSummaryMessage) -> PatientInfo:
        """통화 요약 → 대시보드의 환자 정보. 앞선 통화가 있으면(2026-10-05 덧붙이기) 회차와 앞선 요약을 함께 싣는다."""
        with self._lock:
            previous = list(self._case_prev_calls.get(voice.caseId, []))
            override = self._case_override.get(voice.caseId)
            extra_notes = list(self._case_extra_notes.get(voice.caseId, []))
        confirmation = {} if override is None else {
            "confirmedBy": "paramedic", "confirmedAt": override["confirmedAt"],
            "overrides": list(override["records"].values()),
        }
        return PatientInfo(
            injuryStatus=voice.summary.symptoms,
            expectedDiagnosis=voice.summary.mechanism,
            severityTag=voice.summary.severity_tag,
            rawTranscript=voice.transcript.raw_text,
            filteredTranscript=voice.transcript.filtered_text,
            patient=voice.summary.patient,
            treatment=voice.summary.treatment,
            ktasLevel=voice.summary.ktas_level,
            vitals=voice.summary.vitals,
            consciousness=voice.summary.consciousness,
            onset=voice.summary.onset,
            chiefComplaint=voice.summary.chief_complaint,
            requiredDepartment=voice.summary.required_department,
            callRound=len(previous) + 1,
            previousCalls=previous,
            extraNotes=extra_notes,
            **confirmation,
        )

    # 순위에 쓰이는 칸 — 바뀌면(이송 확정 전) 다시 매칭한다. 주 호소·증상은 표시용이라 환자 정보만 갈아 끼운다.
    _OVERRIDE_RANKING_FIELDS = frozenset({"expectedDiagnosis", "ktasLevel", "requiredDepartment"})
    # PatientOverride 칸 -> VoiceSummary 칸
    _OVERRIDE_SUMMARY_FIELD = {
        "expectedDiagnosis": "mechanism", "injuryStatus": "symptoms", "ktasLevel": "ktas_level",
        "requiredDepartment": "required_department", "chiefComplaint": "chief_complaint",
    }

    def apply_patient_override(
        self, override: PatientOverride, ambulance_gps: GpsPoint
    ) -> tuple[HubMatchResult, dict] | None:
        """구급대원의 통화 요약 확인·수정(2026-10-13, Override)을 사건에 반영한다.

        보낸 칸만 사건의 통화 요약(_case_voice)에 덮어쓴다 — 이후 60초 재계산·존 확장도 고친 값으로 돈다. KTAS를
        바꾸면 중증도도 따라 바뀐다. 순위 칸(예상 병명·KTAS·필요 진료과)이 실제로 바뀌었고 이송 확정 전이면 다시
        매칭한다(넓힌 존 유지 — process_voice_summary가 승인 상태를 그대로 읽어 병원 승인은 유지된다). 확정 사건이거나
        표시용 칸만 바뀌었으면 병원 목록·순서는 그대로 두고 환자 정보만 바꾼다. 아무 칸도 안 보내면 "수정 없이 확인"이다.

        사건이 없으면 None. 반환: (새 결과, 의사결정 로그에 남긴 요약)."""
        case_id = override.caseId
        now = _utcnow().isoformat(timespec="seconds")
        with self._lock:
            voice = self._case_voice.get(case_id)
            old = self._case_results.get(case_id)
            if voice is None or old is None:
                return None
            confirmed = case_id in self._case_confirmed_at
            max_zone = self._case_max_zone.get(case_id, 1)
            gps_fallback = self._case_gps_fallback.get(case_id, False)
            # 추가 정보만 보낸 것은 "요약 확인"이 아니다(2026-10-26) — 확인 도장(confirmedBy)은 요약 칸을 보낸
            # 경우에만 찍는다. 아니면 추가 정보 한 줄로 "구급대원 확인"이 돼 버린다.
            touches_summary = bool(override.model_fields_set & set(self._OVERRIDE_SUMMARY_FIELD)) or not (
                override.extraNote or "").strip()
            if touches_summary:
                state = self._case_override.setdefault(case_id, {"confirmedAt": now, "records": {}})
                state["confirmedAt"] = now
            else:
                state = self._case_override.get(case_id) or {"confirmedAt": now, "records": {}}
            summary_updates: dict = {}
            changes = []
            for field in sorted(override.model_fields_set & set(self._OVERRIDE_SUMMARY_FIELD)):
                value = getattr(override, field)
                if field == "injuryStatus":
                    value = [v.strip() for v in (value or []) if v and v.strip()]
                elif isinstance(value, str):
                    value = value.strip() or None
                if field in ("expectedDiagnosis", "ktasLevel") and value is None:
                    continue  # 예상 병명·KTAS는 비울 수 없다(매칭 입력)
                summary_key = self._OVERRIDE_SUMMARY_FIELD[field]
                before = getattr(voice.summary, summary_key)
                if before == value:
                    continue
                summary_updates[summary_key] = value
                if field == "ktasLevel":
                    summary_updates["severity_tag"] = KTAS_TO_SEVERITY[value]
                record = state["records"].get(field)
                ai_value = record.ai if record is not None else before
                if ai_value == value:
                    state["records"].pop(field, None)  # AI 값으로 되돌렸다 — 고친 칸이 아니다
                else:
                    state["records"][field] = OverrideRecord(field=field, ai=ai_value, value=value, at=now)
                changes.append({"field": field, "before": before, "after": value})
            # 추가 정보는 칸을 덮어쓰지 않고 쌓는다(2026-10-26) — 순위 칸이 아니라 재매칭을 일으키지 않는다
            note = (override.extraNote or "").strip() if "extraNote" in override.model_fields_set else ""
            if note:
                self._case_extra_notes.setdefault(case_id, []).append(ExtraNote(text=note, at=now))
                changes.append({"field": "extraNote", "before": None, "after": note})
            if summary_updates:
                voice = voice.model_copy(update={"summary": voice.summary.model_copy(update=summary_updates)})
                self._case_voice[case_id] = voice
            self._dirty = True

        ranking_changed = any(c["field"] in self._OVERRIDE_RANKING_FIELDS for c in changes)
        rematched = ranking_changed and not confirmed
        if rematched:
            result = self.process_voice_summary(voice, ambulance_gps, max_zone=max_zone, gps_fallback=gps_fallback)
        else:
            patient = self._patient_info(voice)
            with self._lock:
                result = self._case_results[case_id].model_copy(update={"patientInfo": patient})
                self._case_results[case_id] = result
                self._dirty = True
        log = {"caseId": case_id, "confirmedOnly": not changes, "rematched": rematched,
               "caseConfirmed": confirmed, "changes": changes}
        decision_log.log_decision("patient_override", log)
        return result, log

    def add_call_summary(
        self,
        voice: VoiceCallSummaryMessage,
        ambulance_gps: GpsPoint,
        max_zone: int = 1,
        gps_fallback: bool = False,
    ) -> HubMatchResult:
        """voice가 보낸 통화 요약 한 건을 사건에 반영한다(app.py의 /voice/summary 경로, 2026-10-05).

        첫 통화면 process_voice_summary()와 같다. 같은 사건의 **추가 통화**(환자 상태 변화로 다시 건 통화 —
        이송 중 목적지 병원과의 통화 등)면 덧붙인다: 직전 환자 정보를 previousCalls에 쌓고, 통화 전문은 앞뒤로
        이어 붙이며, 최신 요약이 지금 환자 상태가 된다.
        - 이송이 확정된 사건: 목적지가 정해졌으니 병원 목록·순위는 그대로 두고 환자 정보만 바꾼다(움직이는 구급차
          위치로 후보를 다시 뽑으면 확정 병원이 목록에서 빠질 수 있다).
        - 미확정 사건: 새 환자 정보로 다시 매칭한다(넓혀 둔 존은 유지)."""
        with self._lock:
            old_voice = self._case_voice.get(voice.caseId)
            old_result = self._case_results.get(voice.caseId)
        if old_voice is None or old_result is None:
            return self.process_voice_summary(voice, ambulance_gps, max_zone=max_zone, gps_fallback=gps_fallback)

        old_patient = old_result.patientInfo
        with self._lock:
            prev = self._case_prev_calls.setdefault(voice.caseId, [])
            prev.append(PatientUpdate(
                callRound=old_patient.callRound, receivedAt=_utcnow().isoformat(),
                expectedDiagnosis=old_patient.expectedDiagnosis, severityTag=old_patient.severityTag,
                injuryStatus=old_patient.injuryStatus, ktasLevel=old_patient.ktasLevel,
                vitals=old_patient.vitals, consciousness=old_patient.consciousness,
            ))
            round_no = len(prev) + 1
            confirmed = voice.caseId in self._case_confirmed_at
            self._case_override.pop(voice.caseId, None)  # 새 AI 요약은 아직 구급대원 확인 전
            current_zone = self._case_max_zone.get(voice.caseId, 1)
        marker = f"\n\n── {round_no}차 통화 ──\n"
        merged = voice.model_copy(update={"transcript": voice.transcript.model_copy(update={
            "raw_text": old_voice.transcript.raw_text + marker + voice.transcript.raw_text,
            "filtered_text": old_voice.transcript.filtered_text + marker + voice.transcript.filtered_text,
        })})
        decision_log.log_decision("patient_info_appended", {
            "caseId": voice.caseId, "callRound": round_no, "confirmed": confirmed,
            "severityTag": voice.summary.severity_tag, "ktasLevel": voice.summary.ktas_level,
        })
        if not confirmed:
            return self.process_voice_summary(merged, ambulance_gps, max_zone=max(max_zone, current_zone),
                                              gps_fallback=gps_fallback)
        patient = self._patient_info(merged)
        with self._lock:
            self._case_voice[voice.caseId] = merged
            result = self._case_results[voice.caseId].model_copy(update={"patientInfo": patient})
            self._case_results[voice.caseId] = result
            self._dirty = True
        decision_log.log_decision("hub_match_result", _redact_transcript(result.model_dump()))
        return result

    def plan_mci(self, case_ids: list[str]) -> list[dict]:
        """대량사고 자동 분배 계획(2026-10-05) — 승인 병원들 사이에 사상자를 나눈다. 콘솔 ③의 미리 보기와 [분배 확정]이
        같은 계획을 쓴다(보이는 대로 확정된다).

        규칙은 평시 순위 그대로(규칙 기반): 중증 → 중등증 → 경증 순으로, 사상자마다 그 사건에서 **승인한** 병원(제외 병원
        빼고) 중 finalScore 최고 — 진료과 적합도 0.6 + 이동시간 0.4, 중증 센터 가산·경증 센터 역가산(travelBonusMin).
        앞 사상자를 배정할 때마다 그 병원의 이송 중 건수를 하나 늘리고 병상을 하나 줄여 부하 페널티를 다시 매긴다 —
        한 병원에 몰리지 않고 다음 병원으로 퍼진다. 병상 신뢰도는 쓰지 않는다(순위 원칙)."""
        # spider 매칭 규칙(2026-10-15) — KTAS 낮은 숫자부터(같으면 먼저 닿는 쪽), 사상자마다 승인 병원 중
        # 줄 길이(spiderLen — 도로 분 − μ×이득 + 부하)가 가장 짧은 곳. 앞 배정마다 이송 중 +1·병상 −1로 부하를 다시 매겨
        # 분산시킨다(τ 창 한도는 2026-10-22에 걷어냈다 — spider_rule.py 모듈 설명 ⚠). 줄 없는 병원은 마지막 수단.
        now = _utcnow()
        with self._lock:
            items = []
            for index, case_id in enumerate(dict.fromkeys(case_ids)):
                result = self._case_results.get(case_id)
                if result is None:
                    continue
                items.append((self._spider_ktas(case_id), index, case_id, result))
            extra: dict[str, int] = {}
            plan = []
            for _, _, case_id, result in sorted(items, key=lambda x: (x[0], x[1])):
                best = None
                for rank, h in enumerate(result.hospitals):
                    if h.status != "approved" or (case_id, h.hospitalId) in self._case_excluded:
                        continue
                    info = self._hospitals.get(h.hospitalId)
                    added = extra.get(h.hospitalId, 0)
                    if info is not None:
                        in_flight = self._prune_and_count_overlay(h.hospitalId, now) + added
                        beds = self.effective_bed_count(info) - added
                        load_min, _ = load_penalty_min(in_flight, beds, _is_bed_count_unknown(info))
                    else:
                        load_min = 0.0
                    travel = h.travelMin if h.travelMin is not None else h.distanceKm * 3.0
                    if h.spiderLen is not None:
                        key = (0, h.spiderLen - (h.loadPenaltyMin or 0.0) + load_min, rank)
                    else:
                        key = (1, travel + load_min, rank)
                    if best is None or key < best[0]:
                        best = (key, rank, h, load_min)
                if best is None:
                    plan.append({"caseId": case_id, "hospitalId": None, "severityTag": result.patientInfo.severityTag})
                    continue
                _, _, h, load_min = best
                extra[h.hospitalId] = extra.get(h.hospitalId, 0) + 1
                plan.append({"caseId": case_id, "hospitalId": h.hospitalId, "hospitalName": h.name,
                             "severityTag": result.patientInfo.severityTag, "loadPenaltyMin": round(load_min, 1)})
            return plan

    def is_excluded(self, case_id: str, hospital_id: str) -> bool:
        with self._lock:
            return (case_id, hospital_id) in self._case_excluded

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
        max_zone = self._dispatch_zone(voice, ambulance_gps, max_zone)
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

        max_zone = self._dispatch_zone(voice, ambulance_gps, max_zone)
        result, group = self._compute_result(voice, ambulance_gps, max_zone, gps_fallback)

        with self._lock:
            if case_id not in self._case_voice:
                return None  # 계산하는 사이 정리됨
            self._case_results[case_id] = result
            self._case_max_zone[case_id] = max_zone
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

    def next_zone_with_new(self, ambulance_gps: GpsPoint, current: int, cap: int = 10,
                           case_id: str | None = None) -> int | None:
        """current 바깥에서 새 병원이 처음 들어오는 존(2026-10-04, 시간 기반 확장). 없으면 None —
        _expand_until_nonempty는 "후보가 하나라도 있으면"이라 이미 있는 병원만으로도 멈춰, 시간 확장이
        병원 없는 빈 존으로 계속 넓어졌다."""
        def candidates(zone: int) -> list[tuple[HospitalInfo, float]]:
            if case_id:
                return self._dispatch_candidates(case_id, ambulance_gps, zone)
            return self._candidates_in_zone(ambulance_gps, zone)
        known = len(candidates(current))
        for zone in range(current + 1, cap + 1):
            if len(candidates(zone)) > known:
                return zone
        return None

    def force_expand_zone(self, case_id: str, ambulance_gps: GpsPoint, cause: str = "arrival_refused",
                          to_zone: int | None = None) -> HubMatchResult | None:
        """존을 한 단계 넓혀 **기존 환자 정보(통화 요약) 그대로** 다시 매칭한다(2026-10-01).
        도착 후 수용 불가로 갈 곳이 없어졌을 때 — 다시 통화하지 않고 넓어진 존의 병원들에게 같은
        요청을 보내려는 것이다(역할별 전송이 새 후보 병원 탭에도 보낸다). 새 존이 비면 후보가 잡힐
        때까지 넓힌다. 확장할 수 없으면 None."""
        with self._lock:
            current = self._case_max_zone.get(case_id, 1)
            voice = self._case_voice.get(case_id)
            gps_fallback = self._case_gps_fallback.get(case_id, False)
        if voice is None:
            return None
        new_max = to_zone if to_zone is not None else self._expand_until_nonempty(ambulance_gps, current + 1)
        if new_max <= current:
            return None
        print(f"  [존 확장] case={case_id} {cause} — zone 1~{current} -> 1~{new_max}")
        decision_log.log_decision("zone_expanded", {"caseId": case_id, "from": current, "to": new_max,
                                                    "cause": cause})
        return self.process_voice_summary(voice, ambulance_gps, max_zone=new_max, gps_fallback=gps_fallback)

    def _is_confirmed_full(self, hospital_id: str) -> bool:
        """응급실 병상 0이 '확인된' 만실인지 — 미상·오래된 값(1일 초과·피드 누락)은 아니다. beds_full 내림과 같은 기준."""
        with self._lock:
            info = self._hospitals.get(hospital_id)
            if info is None:
                return False
            return (not _is_bed_count_unknown(info) and not _is_bed_data_stale(info, _utcnow())
                    and self.effective_bed_count(info) <= 0)

    def get_case_status(self, case_id: str, hospital_id: str) -> str:
        with self._lock:
            return self._approval_status.get((case_id, hospital_id), "pending")

    def has_other_approved(self, case_id: str, except_hospital: str) -> bool:
        with self._lock:
            return any(
                cid == case_id and hid != except_hospital and status == "approved"
                for (cid, hid), status in self._approval_status.items()
            )

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
                    "override": _override_to_json(self._case_override.get(cid)),
                    "extraNotes": [n.model_dump() for n in self._case_extra_notes.get(cid, [])],
                }
            return {
                "version": STATE_VERSION,
                "savedAt": _utcnow().isoformat(),
                "hospitals": [h.model_dump() for h in self._hospitals.values()],
                "ambulances": [a.model_dump() for a in self._ambulances.values()],
                "approvalStatus": [[cid, hid, status] for (cid, hid), status in self._approval_status.items()],
                "bedOverlay": {hid: [h.to_json() for h in holds] for hid, holds in self._bed_overlay.items()},
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
            for cid, hid, status in state.get("approvalStatus", []):
                if status in _ACTION_TO_STATUS.values():
                    self._approval_status[(cid, hid)] = status
            for hid, raws in state.get("bedOverlay", {}).items():
                holds = [h for h in (_hold_from_state(raw) for raw in raws) if h is not None]
                if holds:
                    self._bed_overlay[hid] = holds
                    for hold in holds:
                        if hold.case_id is not None:
                            self._case_overlay[(hold.case_id, hid)] = hold
            for cid, hid, at in state.get("caseOverlay", []):  # 예전 형식: 사건 ↔ 차감을 만료 시각으로 이었다
                expires = _parse_iso(at)
                hold = next((h for h in self._bed_overlay.get(hid, []) if h.expires_at == expires), None)
                if hold is not None:
                    hold.case_id = cid
                    self._case_overlay[(cid, hid)] = hold
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
                        # 수용이 끝난 사건 표시도 되살린다 — 안 하면 재시작 뒤 따라잡기로 다시 화면에 뜬다(2026-10-01).
                        arrival = self._case_results[cid].arrival
                        if arrival is not None and arrival.result == "accepted":
                            self._case_arrival[cid] = arrival
                    self._case_group[cid] = case.get("group")
                    self._case_gps_fallback[cid] = bool(case.get("gpsFallback"))
                    notes = []
                    for item in case.get("extraNotes") or []:
                        try:
                            notes.append(ExtraNote.model_validate(item))
                        except Exception:  # noqa: BLE001 — 한 줄이 깨져도 나머지는 살린다
                            continue
                    if notes:
                        self._case_extra_notes[cid] = notes
                    override = _override_from_json(case.get("override"))
                    if override is not None:
                        self._case_override[cid] = override
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
