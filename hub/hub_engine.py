"""GPS+병원 정보로 먼저 존 기반 후보 리스트를 만들어두고, voice 정보가 도착하면
이를 반영해 재처리하는 2단계 매칭 엔진. CLAUDE.md "feature/hub 담당자 참고사항" 참고.

모델/API 호출부(SpecialtyMatcher)와 비즈니스 로직(존 분류, 스코어링)을 분리해뒀기
때문에, 나중에 매칭 모델을 바꿔도 이 엔진의 흐름은 바뀌지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import decision_log
from geo import active_zones, haversine_km, should_expand_zone, zone_of
from schema import (
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


class HubEngine:
    def __init__(self, specialty_matcher: SpecialtyMatcher | None = None) -> None:
        self._hospitals: dict[str, HospitalInfo] = {}
        self._matcher = specialty_matcher or SpecialtyMatcher()
        # dashboard가 보낸 승인 액션 결과. hospitalId 기준으로 보관해뒀다가
        # 다음 매칭 결과의 hospitals[].status에 반영한다.
        self._approval_status: dict[str, HospitalStatus] = {}

    def update_hospital_info(self, info: HospitalInfo) -> None:
        """feature/info로부터 받은 병원 정보를 hospitalId 기준으로 upsert한다."""
        self._hospitals[info.hospitalId] = info

    def apply_approval_action(self, action: ApprovalAction) -> HospitalBedUpdate | None:
        """dashboard가 보낸 승인 액션을 반영한다 (dashboard는 이 브랜치와만 직접
        통신하므로 수신은 여기서 한다). hospitals[].status에 반영될 내부 상태를
        갱신하고, 병상이 실제로 줄어드는 경우(final_approval)에만 feature/info로
        보낼 HospitalBedUpdate를 만들어 반환한다 — 그 외에는 None을 반환한다.
        """
        # 멱등성: 이미 confirmed된 병원에 최종 승인이 중복 도착해도(버튼 중복
        # 클릭, 네트워크 재시도 등) 병상을 두 번 깎지 않는다.
        if action.action == "final_approval" and self._approval_status.get(action.hospital_id) == "confirmed":
            decision_log.log_decision(
                "approval_action_ignored_duplicate",
                {"action": action.model_dump(), "reason": "already confirmed"},
            )
            return None

        new_status = _ACTION_TO_STATUS[action.action]
        self._approval_status[action.hospital_id] = new_status

        if action.action != "final_approval":
            decision_log.log_decision("approval_action_applied", {"action": action.model_dump(), "bedUpdate": None})
            return None

        info = self._hospitals.get(action.hospital_id)
        if info is None or info.availableBedCount <= 0:
            # 모르는 병원이거나 이미 병상이 없으면 더 깎지 않는다 (음수 방지)
            decision_log.log_decision(
                "approval_action_ignored_no_bed",
                {"action": action.model_dump(), "reason": "unknown hospital or no beds left"},
            )
            return None

        info.availableBedCount -= 1
        info.updatedAt = _utcnow_iso()

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

    def reject_ratio(self, ambulance_gps: GpsPoint, max_zone: int) -> float:
        """현재 존(1~max_zone) 안 병원들 중, 명시적으로 응답(approved/rejected/
        confirmed)한 병원 대비 거절(rejected)한 병원의 비율. 아직 아무도 응답하지
        않았으면(전부 pending) 0.0을 반환한다 — expand_if_needed()에 그대로 넘기면
        시간 기반이 아닌 거절 비율 기반 존 확장 판단에 쓸 수 있다.
        """
        candidates = self._candidates_in_zone(ambulance_gps, max_zone)
        statuses = [self._approval_status.get(info.hospitalId, "pending") for info, _ in candidates]
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
                status=self._approval_status.get(item["hospitalId"], "pending"),
            )
            for item in rank(scored)
        ]

        result = HubMatchResult(
            patientInfo=PatientInfo(
                injuryStatus=injury_status,
                expectedDiagnosis=expected_diagnosis,
                severityTag=severity_tag,
            ),
            zoneActive=active_zones(max_zone),
            hospitals=hospital_matches,
            source="rule",
        )
        # CLAUDE.md "모든 의사결정 로그는 타임스탬프 + SHA-256 해시로 저장" 원칙.
        # "어떤 환자 정보로 어떤 병원 순위가 나왔는지"가 이 브랜치의 핵심 의사결정이다.
        decision_log.log_decision("hub_match_result", result.model_dump())
        return result

    def expand_if_needed(self, max_zone: int, reject_ratio: float) -> int:
        """명시적 거절 비율이 임계값을 넘으면 다음 존까지 확장한 max_zone을 반환한다
        (시간 기반 타임아웃이 아닌 거절 비율 기반 — CLAUDE.md 원칙).
        """
        return max_zone + 1 if should_expand_zone(reject_ratio) else max_zone
