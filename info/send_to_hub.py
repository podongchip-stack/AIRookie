"""병원 정보(HospitalInfo)를 feature/hub로 전송한다.

E-Gen 공개 API 연동(Hospital_inform/info/)은 서비스키 승인 대기 중이라 아직
실제 데이터를 받아올 수 없다 (Hospital_inform/README.md "미해결 항목" 참고).
그래서 E-Gen 서비스키가 나오기 전까지, Hospital_inform/이 이미 갖춘 Supabase
대체 DB 연동(SupabaseEgenClient + mapper.py)을 그대로 재사용해 실제 서울
권역응급의료센터 데이터를 가져와 hub로 보낸다 (Hospital_inform/supabase/schema.sql,
egen/client.py 참고). 매퍼 로직은 여기서 새로 만들지 않고 그대로 가져다 쓴다 —
나중에 HttpEgenClient로 바꿀 때도 이 파일은 손댈 필요가 없다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

HOSPITAL_INFORM_INFO_DIR = Path(__file__).resolve().parent / "Hospital_inform" / "info"
sys.path.insert(0, str(HOSPITAL_INFORM_INFO_DIR))

from egen.client import SupabaseEgenClient  # noqa: E402
from egen.mapper import map_all  # noqa: E402
from schema import HospitalInfo  # noqa: E402

HUB_HOSPITALS_URL = os.environ.get("HUB_HOSPITALS_URL", "http://127.0.0.1:5001/info/hospitals")


def fetch_hospitals() -> list[HospitalInfo]:
    """Supabase 대체 DB에서 병원 정보를 가져와 HospitalInfo로 변환한다."""
    client = SupabaseEgenClient()
    hospitals, report = map_all(
        client.get_realtime_beds(),
        client.get_list_info(),
        client.get_severe_illness(),
    )
    print("=== Supabase에서 병원 정보 조회 ===")
    print(report.summary())
    return hospitals


def send_to_hub(hospital: HospitalInfo) -> None:
    response = requests.post(
        HUB_HOSPITALS_URL,
        data=hospital.to_hub_json(),
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()
    print(f"  [통신] {hospital.hospitalId} {hospital.name} 전송 완료 -> {HUB_HOSPITALS_URL}")


def main() -> None:
    hospitals = fetch_hospitals()
    print(f"\n=== 병원 정보 {len(hospitals)}건을 feature/hub로 전송 ===")
    for hospital in hospitals:
        send_to_hub(hospital)


if __name__ == "__main__":
    main()
