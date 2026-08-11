"""GPS+병원 정보로 먼저 존 기반 후보 리스트를 만들어두고, voice 정보가 도착하면
이를 반영해 재처리하는 2단계 매칭 엔진. CLAUDE.md "feature/hub 담당자 참고사항" 참고.

모델/API 호출부(SpecialtyMatcher)와 비즈니스 로직(존 분류, 스코어링)을 분리해뒀기
때문에, 나중에 매칭 모델을 바꿔도 이 엔진의 흐름은 바뀌지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import decision_log
import delivery
from geo import active_zones, haversine_km, should_expand_zone, zone_of
from schema import (
    AmbulanceInfo,
    ApprovalAction,
    GpsPoint,
    HospitalBedUpdate,
    HospitalInfo,
    HospitalMatch,
    HospitalStatus,
    HubMatchResult,
    PatientInfo,
    SpecialtyMatch,
    VoiceCallSummaryMessage,
)
from scoring import final_score, rank
from specialty_matcher import SpecialtyMatcher

# dashboard의 ApprovalAction.action -> 매칭 결과에 반영할 상태.
# hospital_approve/hospital_reject는 "병원의 승인은 후보 등록일 뿐"(CLAUDE.md)이라
# 상태만 바뀌고 병상은 안 줄어든다. final_approval(구급대원의 이송 승인)만 실제
# 확정이라 병상을 차감하고 feature/info에도 알린다.
_ACTION_TO_STATUS: dict[str, HospitalStatus] = {
    "hospital_approve": "approved",
    "hospital_reject": "rejected",
    "final_approval": "confirmed",
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


class HubEngine:
    def __init__(self, specialty_matcher: SpecialtyMatcher | None = None) -> None:
        self._hospitals: dict[str, HospitalInfo] = {}
        self._matcher = specialty_matcher or SpecialtyMatcher()
        # dashboard가 보낸 승인 액션 결과. 여러 사건이 동시에 진행될 수 있어
        # (caseId, hospitalId) 조합을 키로 쓴다 — hospitalId만 쓰면 서로 다른
        # 사건이 같은 병원을 후보로 둘 때 승인 상태가 섞인다.
        self._approval_status: dict[tuple[str, str], HospitalStatus] = {}
        # 구급차 레지스트리(feature/info가 Supabase ambulances 테이블에서
        # 읽어 보내줌). GPS·voicePort 조회에 쓴다.
        self._ambulances: dict[str, AmbulanceInfo] = {}
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
        # 사건별 마지막 VoiceCallSummaryMessage. 존이 확장되면 같은 환자
        # 정보로 매칭을 다시 계산해야 하는데(process_voice_summary는 voice
        # 요약이 있어야 호출 가능), 확장은 dashboard의 승인 액션이 트리거라
        # 그 시점엔 voice 데이터가 다시 오지 않는다 — 그래서 마지막 값을
        # 들고 있다가 재사용한다.
        self._case_voice: dict[str, VoiceCallSummaryMessage] = {}

    def update_hospital_info(self, info: HospitalInfo) -> None:
        """feature/info로부터 받은 병원 정보를 hospitalId 기준으로 upsert한다.

        단, 이 병원의 병상 갱신이 feature/info 전송 재시도 대기열
        (delivery.has_pending_bed_update())에 아직 남아있으면 건너뛴다. hub가
        승인 처리로 이미 깎아둔 값을, 그 차감을 아직 모르는 info의 낡은 값이
        되돌려버리는 걸 막기 위해서다 — 재시도가 성공해 대기열에서 빠진
        뒤에야 다음 갱신이 정상 반영된다.
        """
        if delivery.has_pending_bed_update(info.hospitalId):
            print(f"  [병상 갱신 보류] {info.hospitalId}는 feature/info 전송 재시도 대기 중이라 이번 갱신을 건너뜀")
            return
        self._hospitals[info.hospitalId] = info

    def get_hospital(self, hospital_id: str) -> HospitalInfo | None:
        return self._hospitals.get(hospital_id)

    def update_ambulance_info(self, info: AmbulanceInfo) -> None:
        """feature/info로부터 받은 구급차 정보를 apid 기준으로 upsert한다.
        병원과 달리 hub가 이 값을 직접 바꿀 일이 없어 재시도 대기열 같은
        보정이 필요 없다."""
        self._ambulances[info.apid] = info

    def get_ambulance(self, apid: str) -> AmbulanceInfo | None:
        return self._ambulances.get(apid)

    def register_case(self, case_id: str, apid: str) -> None:
        """통화 시작(CallSignal) 시점에 이 사건이 어느 구급차 것인지 기억해둔다."""
        self._case_apid[case_id] = apid

    def get_case_apid(self, case_id: str) -> str | None:
        return self._case_apid.get(case_id)

    def get_case_result(self, case_id: str) -> HubMatchResult | None:
        """app.py가 승인 액션 처리 후 캐시된 최신 결과를 꺼내 dashboard에
        재브로드캐스트할 때 쓴다."""
        return self._case_results.get(case_id)

    def get_cases_for_hospital(self, hospital_id: str) -> list[HubMatchResult]:
        """이 hospitalId가 후보로 들어있는 사건 전부를 돌려준다. 병원
        대시보드 소켓이 연결 시점에 자기소개(DashboardIdentify)를 보내면,
        연결 전에 이미 방송된 사건들을 놓치지 않도록 따라잡기 용도로 쓴다
        (app.py의 `_send_catchup()` 참고)."""
        return [result for result in self._case_results.values() if any(h.hospitalId == hospital_id for h in result.hospitals)]

    def get_cases_for_apid(self, apid: str) -> list[HubMatchResult]:
        """이 apid(구급차)가 등록한 사건 전부를 돌려준다. 구급차는 실제로는
        한 번에 사건 하나만 진행하지만(voice 마이크가 한 대뿐이라), 같은
        방식으로 여러 건이 나와도 안전하게 동작하도록 리스트로 반환한다."""
        case_ids = [cid for cid, registered_apid in self._case_apid.items() if registered_apid == apid]
        results = [self._case_results.get(cid) for cid in case_ids]
        return [result for result in results if result is not None]

    def _patch_case_result_status(self, case_id: str, hospital_id: str, status: HospitalStatus) -> None:
        """캐시해둔 사건의 매칭 결과에서 해당 병원의 status와 병상 정보를
        최신 self._hospitals 값으로 다시 맞춰 캐시를 갱신한다.

        예전엔 status만 패치했는데, final_approval로 `apply_approval_action()`이
        `self._hospitals`의 병상 수를 실제로 깎아도 dashboard로 나가는 이
        캐시된 스냅샷(HospitalMatch)엔 반영이 안 됐다 — 승인 상태는
        "이송 확정"으로 바뀌는데 병상 배지는 깎이기 전 값 그대로 보이는
        문제가 실제로 재현됐다. 그래서 호출 시점의 `self._hospitals` 값으로
        병상 필드도 같이 다시 읽어온다. 아직 process_voice_summary가 호출된
        적 없는 caseId면(캐시가 없으면) 조용히 넘어간다.
        """
        result = self._case_results.get(case_id)
        if result is None:
            return

        def _patch(h: HospitalMatch) -> HospitalMatch:
            if h.hospitalId != hospital_id:
                return h
            update: dict = {"status": status}
            info = self._hospitals.get(hospital_id)
            if info is not None:
                update["availableBedCount"] = info.availableBedCount
                update["bedCountUnknown"] = _is_bed_count_unknown(info)
            return h.model_copy(update=update)

        updated_hospitals = [_patch(h) for h in result.hospitals]
        self._case_results[case_id] = result.model_copy(update={"hospitals": updated_hospitals})

    def apply_approval_action(self, action: ApprovalAction) -> HospitalBedUpdate | None:
        """dashboard가 보낸 승인 액션을 반영한다 (dashboard는 이 브랜치와만 직접
        통신하므로 수신은 여기서 한다). hospitals[].status에 반영될 내부 상태를
        갱신하고, 병상이 실제로 줄어드는 경우(final_approval)에만 feature/info로
        보낼 HospitalBedUpdate를 만들어 반환한다 — 그 외에는 None을 반환한다.
        """
        # 멱등성: 이미 confirmed된 병원에 최종 승인이 중복 도착해도(버튼 중복
        # 클릭, 네트워크 재시도 등) 병상을 두 번 깎지 않는다. 여러 사건이
        # 동시에 진행될 수 있어 (caseId, hospitalId) 조합으로 구분한다.
        status_key = (action.caseId, action.hospital_id)
        if action.action == "final_approval" and self._approval_status.get(status_key) == "confirmed":
            decision_log.log_decision(
                "approval_action_ignored_duplicate",
                {"action": action.model_dump(), "reason": "already confirmed"},
            )
            return None

        new_status = _ACTION_TO_STATUS[action.action]
        self._approval_status[status_key] = new_status

        if action.action != "final_approval":
            # 병상은 안 건드리는 액션이라 지금 self._hospitals 값 그대로 패치해도 된다.
            self._patch_case_result_status(action.caseId, action.hospital_id, new_status)
            decision_log.log_decision("approval_action_applied", {"action": action.model_dump(), "bedUpdate": None})
            return None

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
        elif info.availableBedCount <= 0:
            skip_reason = "no beds left"

        if skip_reason is not None:
            # 병상은 안 깎였지만 status는 confirmed로 바뀌었으니 캐시에도 반영한다.
            self._patch_case_result_status(action.caseId, action.hospital_id, new_status)
            decision_log.log_decision(
                "approval_action_ignored_no_bed",
                {"action": action.model_dump(), "reason": skip_reason},
            )
            return None

        info.availableBedCount -= 1
        info.updatedAt = _utcnow_iso()
        # 병상이 실제로 줄어든 뒤에 패치해야 dashboard 캐시에도 새 병상 수가
        # 반영된다 — 감소 전에 패치하면 status만 바뀌고 병상 배지는 옛날 값
        # 그대로 남는다(실제로 재현됐던 문제).
        self._patch_case_result_status(action.caseId, action.hospital_id, new_status)

        bed_update = HospitalBedUpdate(
            hospitalId=info.hospitalId,
            availableBedCount=info.availableBedCount,
            status="confirmed",
            updatedAt=info.updatedAt,
        )
        decision_log.log_decision(
            "approval_action_applied",
            {"action": action.model_dump(), "bedUpdate": bed_update.model_dump()},
        )
        return bed_update

    def reject_ratio(self, case_id: str, ambulance_gps: GpsPoint, max_zone: int) -> float:
        """현재 존(1~max_zone) 안 병원들 중, 명시적으로 응답(approved/rejected/
        confirmed)한 병원 대비 거절(rejected)한 병원의 비율. 아직 아무도 응답하지
        않았으면(전부 pending) 0.0을 반환한다 — expand_if_needed()에 그대로 넘기면
        시간 기반이 아닌 거절 비율 기반 존 확장 판단에 쓸 수 있다.
        """
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
            {"hospitalId": info.hospitalId, "name": info.name, "distanceKm": round(distance, 2)}
            for info, distance in candidates
        ]

    def process_voice_summary(
        self,
        voice: VoiceCallSummaryMessage,
        ambulance_gps: GpsPoint,
        max_zone: int = 1,
    ) -> HubMatchResult:
        """2단계: voice의 의료 정보가 도착하면, 보관해둔 병원 정보와 결합해
        진료과 매칭 + 거리를 가중합한 최종 매칭 결과를 만든다.
        """
        self._case_voice[voice.caseId] = voice
        self._case_max_zone[voice.caseId] = max_zone

        expected_diagnosis = voice.summary.mechanism
        injury_status = voice.summary.symptoms
        severity_tag = voice.summary.severity_tag

        candidates = self._candidates_in_zone(ambulance_gps, max_zone)
        department_lists = [[s.department for s in info.specialties] for info, _ in candidates]
        specialty_results = self._matcher.match_many(expected_diagnosis, department_lists)

        scored = []
        for (info, distance), (best_dept, similarity) in zip(candidates, specialty_results):
            scored.append(
                {
                    "hospitalId": info.hospitalId,
                    "finalScore": final_score(similarity, distance),
                    "distanceKm": round(distance, 2),
                    "info": info,
                    "specialtyMatch": SpecialtyMatch(department=best_dept, score=round(similarity, 4)),
                }
            )

        hospital_matches = [
            HospitalMatch(
                hospitalId=item["info"].hospitalId,
                name=item["info"].name,
                gps=item["info"].gps,
                distanceKm=item["distanceKm"],
                specialtyMatch=item["specialtyMatch"],
                availableBedCount=item["info"].availableBedCount,
                bedCountUnknown=_is_bed_count_unknown(item["info"]),
                status=self._approval_status.get((voice.caseId, item["hospitalId"]), "pending"),
            )
            for item in rank(scored)
        ]

        # 구급차 대시보드 상단바 표시용. 이 사건의 apid를 register_case()로
        # 기억해둔 값에서 찾아, 구급차 레지스트리(self._ambulances)의 이름을
        # 그대로 붙인다 — app.py의 _resolve_ambulance_gps()와 동일한 조회 패턴.
        apid = self._case_apid.get(voice.caseId)
        ambulance = self._ambulances.get(apid) if apid else None

        result = HubMatchResult(
            caseId=voice.caseId,
            patientInfo=PatientInfo(
                injuryStatus=injury_status,
                expectedDiagnosis=expected_diagnosis,
                severityTag=severity_tag,
                rawTranscript=voice.transcript.raw_text,
                filteredTranscript=voice.transcript.filtered_text,
            ),
            zoneActive=active_zones(max_zone),
            hospitals=hospital_matches,
            source="rule",
            ambulanceName=ambulance.name if ambulance is not None else None,
        )
        # 승인 액션이 들어왔을 때 재계산 없이 패치·재브로드캐스트할 수 있게
        # 사건 단위로 최신 결과를 캐시해둔다 (get_case_result() 참고).
        self._case_results[voice.caseId] = result
        # CLAUDE.md "모든 의사결정 로그는 타임스탬프 + SHA-256 해시로 저장" 원칙.
        # "어떤 환자 정보로 어떤 병원 순위가 나왔는지"가 이 브랜치의 핵심 의사결정이다.
        decision_log.log_decision("hub_match_result", result.model_dump())
        return result

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
        생긴다. 병원 7곳이 서울 전역에 흩어져 있는 지금 데이터에서 실제로
        재현된 문제라, 후보 0개는 거절 비율과 별개로 무조건 확장한다.
        cap은 병원 데이터가 거의 없는 등 극단적인 경우 무한 루프를 막는
        안전장치다(병원 수가 늘어 zone 10 안에도 후보가 없을 일은 없다고
        본다).
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
        return self._case_max_zone.get(case_id, 1)

    def maybe_expand_zone(self, case_id: str, ambulance_gps: GpsPoint) -> HubMatchResult | None:
        """거절(hospital_reject) 액션 처리 후에만 호출해야 한다. 지금 zone에
        후보가 아예 없거나(사각지대 보정), 명시적 거절 비율이 임계값을
        넘으면 zone을 확장해 후보를 다시 계산한다. 확장이 실제로 일어났을
        때만 재계산된 HubMatchResult를 반환하고, 안 바뀌었으면 None을
        반환한다(호출자가 굳이 재브로드캐스트 안 하도록).

        reject_ratio는 현재 zone 안에서 "응답한" 병원 전체 대비 거절 비율을
        누적으로 계산한다 — 한 번 거절이 쌓여 비율이 임계값을 넘으면, 그
        뒤에 다른 병원이 승인만 해도 비율이 여전히 임계값 이상으로 남는다.
        그래서 승인(hospital_approve)이나 최종 승인(final_approval) 뒤에도
        이 메서드를 부르면, 새로 거절이 하나도 없었는데도 계속 확장되는
        문제가 생긴다(실제로 재현·검증됨). 그래서 caller(app.py)가
        action.action == "hospital_reject"일 때만 불러야 한다.
        """
        current_max_zone = self._case_max_zone.get(case_id, 1)
        candidates = self._candidates_in_zone(ambulance_gps, current_max_zone)
        if not candidates:
            new_max_zone = self._expand_until_nonempty(ambulance_gps, current_max_zone)
        else:
            ratio = self.reject_ratio(case_id, ambulance_gps, current_max_zone)
            new_max_zone = self.expand_if_needed(current_max_zone, ratio)

        if new_max_zone == current_max_zone:
            return None

        voice = self._case_voice.get(case_id)
        if voice is None:
            # process_voice_summary가 한 번도 호출된 적 없는 사건 — 승인 액션이
            # 오려면 후보가 먼저 있어야 하므로 이론상 없는 상태지만, 방어적으로
            # 넘어간다.
            return None

        print(f"  [존 확장] case={case_id} zone 1~{current_max_zone} -> 1~{new_max_zone}")
        return self.process_voice_summary(voice, ambulance_gps, max_zone=new_max_zone)
