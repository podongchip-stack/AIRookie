"""GPS+병원 정보로 먼저 존 기반 후보 리스트를 만들어두고, voice 정보가 도착하면
이를 반영해 재처리하는 2단계 매칭 엔진. CLAUDE.md "feature/hub 담당자 참고사항" 참고.

모델/API 호출부(SpecialtyMatcher)와 비즈니스 로직(존 분류, 스코어링)을 분리해뒀기
때문에, 나중에 매칭 모델을 바꿔도 이 엔진의 흐름은 바뀌지 않는다.
"""
from __future__ import annotations

from geo import active_zones, haversine_km, should_expand_zone, zone_of
from schema import (
    GpsPoint,
    HospitalInfo,
    HospitalMatch,
    HubMatchResult,
    PatientInfo,
    SpecialtyMatch,
    VoiceCallSummaryMessage,
)
from scoring import final_score, rank
from specialty_matcher import SpecialtyMatcher


class HubEngine:
    def __init__(self, specialty_matcher: SpecialtyMatcher | None = None) -> None:
        self._hospitals: dict[str, HospitalInfo] = {}
        self._matcher = specialty_matcher or SpecialtyMatcher()

    def update_hospital_info(self, info: HospitalInfo) -> None:
        """feature/info로부터 받은 병원 정보를 hospitalId 기준으로 upsert한다."""
        self._hospitals[info.hospitalId] = info

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
                # 승인 액션(hospital_approve/hospital_reject/final_approval) 수신은
                # 아직 미연동이라(CLAUDE.md "잠정 보류" 참고) 항상 pending으로 둔다.
                status="pending",
            )
            for item in rank(scored)
        ]

        return HubMatchResult(
            patientInfo=PatientInfo(
                injuryStatus=injury_status,
                expectedDiagnosis=expected_diagnosis,
                severityTag=severity_tag,
            ),
            zoneActive=active_zones(max_zone),
            hospitals=hospital_matches,
            source="rule",
        )

    def expand_if_needed(self, max_zone: int, reject_ratio: float) -> int:
        """명시적 거절 비율이 임계값을 넘으면 다음 존까지 확장한 max_zone을 반환한다
        (시간 기반 타임아웃이 아닌 거절 비율 기반 — CLAUDE.md 원칙).
        """
        return max_zone + 1 if should_expand_zone(reject_ratio) else max_zone
