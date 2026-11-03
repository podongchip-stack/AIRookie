"""테스트 병원에 실제 병원의 역량을 채우는 공용 값(2026-11-04).

테스트 병원이 등급·응급의학과 전문의·장비 운영을 비워 두면 거미줄 역량(spider_rule.hospital_z)이 바닥이라 줄이 없고
(spiderBlocked), 전달 필터(hospital_dispatch.can_receive)가 그 병원의 수용 회신·이송 승인을 거부한다 — 오래된 테스트 8개가
이 때문에 깨져 있었다. 지어낸 값 대신 실제 서울 병원 값을 쓴다. 좌표·병상·병원 ID는 각 테스트의 것을 그대로 둔다.

출처: E-Gen 목록 dutyEmclsName(등급) · E-Gen 실시간 병상 hvctayn/hvangioayn(장비 운영, 2026-10-04 스냅샷) ·
심평원 전문과목별 전문의 수(info data/hira/specialists.json, 응급의학과). 실제 값이 바뀌어도 테스트는 이 고정값을 쓴다.
"""
from __future__ import annotations

from schema import Specialty

REAL_PROFILES = {
    # 지역응급의료센터 · 응급의학과 전문의 9명 · CT·혈관조영 운영
    "강북삼성병원": {"hpid": "A1100006", "emergencyLevel": "지역응급의료센터", "emDoctors": 9,
                     "equipmentOperating": {"CT": "Y", "ANGIO": "Y"}},
    # 권역응급의료센터 · 응급의학과 전문의 23명 · CT·혈관조영 운영
    "서울대학교병원": {"hpid": "A1100017", "emergencyLevel": "권역응급의료센터", "emDoctors": 23,
                       "equipmentOperating": {"CT": "Y", "ANGIO": "Y"}},
}


def real_capability(name: str = "강북삼성병원", specialties: list[Specialty] | None = None) -> dict:
    """HospitalInfo(...)에 펼쳐 넣을 등급·전문의·장비 운영. specialties는 테스트가 원래 쓰던 진료과(응급의학과를 덧붙인다)."""
    p = REAL_PROFILES[name]
    return {
        "emergencyLevel": p["emergencyLevel"],
        "specialties": [*(specialties or []), Specialty(department="응급의학과", doctorCount=p["emDoctors"])],
        "equipmentOperating": dict(p["equipmentOperating"]),
    }
