"""병원 정보(HospitalInfo)를 feature/hub로 전송한다.

E-Gen 공개 API 연동(Hospital_inform/info/)은 서비스키 승인 대기 중이라 아직
실제 데이터를 받아올 수 없다 (Hospital_inform/README.md "미해결 항목" 참고).
그래서 이번 hub 연동 검증 단계에서는 고정된 목업 HospitalInfo 목록을 대신
사용한다 — 스키마는 feature/hub README.md "입출력 데이터 포맷"과 동일하다.
서비스키가 나오면 이 파일의 MOCK_HOSPITALS 자리를
Hospital_inform/info/build_hospitals.py의 결과로 바꿔 끼우면 된다.
"""
from __future__ import annotations

import os

import requests

HUB_HOSPITALS_URL = os.environ.get("HUB_HOSPITALS_URL", "http://127.0.0.1:5001/info/hospitals")

MOCK_HOSPITALS: list[dict] = [
    {
        "hospitalId": "H001",
        "name": "동남병원",
        "gps": {"lat": 35.1980, "lng": 128.1080},
        "availableBedCount": 12,
        "nightDutyAvailable": True,
        "specialties": [
            {"department": "흉부외과", "doctorCount": 2, "recentProcedureTags": ["개흉술"]},
            {"department": "정형외과", "doctorCount": 3, "recentProcedureTags": []},
        ],
        "source": "rule",
        "updatedAt": "2026-08-05T12:00:00Z",
    },
    {
        "hospitalId": "H002",
        "name": "중앙병원",
        "gps": {"lat": 35.1600, "lng": 128.1400},
        "availableBedCount": 0,
        "nightDutyAvailable": False,
        "specialties": [],
        "source": "rule",
        "updatedAt": "2026-08-05T12:00:00Z",
    },
    {
        "hospitalId": "H004",
        "name": "북부병원",
        "gps": {"lat": 35.1850, "lng": 128.1200},
        "availableBedCount": 4,
        "nightDutyAvailable": True,
        "specialties": [
            {"department": "외상외과", "doctorCount": 1, "recentProcedureTags": ["응급개복술"]},
            {"department": "신경외과", "doctorCount": 2, "recentProcedureTags": []},
        ],
        "source": "rule",
        "updatedAt": "2026-08-05T12:00:00Z",
    },
]


def send_to_hub(hospital: dict) -> None:
    response = requests.post(HUB_HOSPITALS_URL, json=hospital, timeout=10)
    response.raise_for_status()
    print(f"  [통신] {hospital['hospitalId']} {hospital['name']} 전송 완료 -> {HUB_HOSPITALS_URL}")


def main() -> None:
    print(f"=== 병원 정보 {len(MOCK_HOSPITALS)}건을 feature/hub로 전송 ===")
    for hospital in MOCK_HOSPITALS:
        send_to_hub(hospital)


if __name__ == "__main__":
    main()
