"""병원 정보(HospitalInfo)를 feature/hub로 전송한다.

E-Gen 공개 API 연동(Hospital_inform/info/)은 서비스키 승인 대기 중이라 아직
실제 데이터를 받아올 수 없다 (Hospital_inform/README.md "미해결 항목" 참고).
그래서 E-Gen 서비스키가 나오기 전까지, Hospital_inform/이 이미 갖춘 Supabase
대체 DB 연동(SupabaseEgenClient + mapper.py)을 그대로 재사용해 실제 서울
권역응급의료센터 데이터를 가져와 hub로 보낸다 (Hospital_inform/supabase/schema.sql,
egen/client.py 참고). 매퍼 로직은 여기서 새로 만들지 않고 그대로 가져다 쓴다 —
나중에 HttpEgenClient로 바꿀 때도 이 파일은 손댈 필요가 없다.

Supabase의 병상 데이터는 계속 바뀌는데 hub는 한 번 받은 값을 메모리에 들고
있을 뿐 스스로 재조회하지 않는다. 그래서 이 스크립트는 한 번 실행하고 끝나는
게 아니라 REFETCH_INTERVAL_SEC마다 계속 재조회·재전송하는 상시 프로세스로
돈다 (팀 논의 결과 — Supabase realtime 구독 대신 주기적 재조회 방식을 택함).
그 주기 사이에 생기는 병상 변동은 hub가 이송 확정(final_approval) 시 보내는
HospitalBedUpdate로 보정한다 (info/app.py, info/README.md "hub → info" 참고).

같은 주기로 구급차 레지스트리(Supabase `ambulances` 테이블 — 병원용과는
별도의 Supabase 프로젝트)도 읽어 hub에 보낸다. `AMBULANCE_SUPABASE_URL`/
`AMBULANCE_SUPABASE_KEY` 환경변수가 없으면(아직 그 프로젝트 credential을
안 받은 팀원 등) 조용히 건너뛴다 — 병원 정보 동기화는 그것과 무관하게
계속 돈다.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

HOSPITAL_INFORM_INFO_DIR = Path(__file__).resolve().parent / "Hospital_inform" / "info"
sys.path.insert(0, str(HOSPITAL_INFORM_INFO_DIR))

from egen.client import SupabaseEgenClient  # noqa: E402
from egen.mapper import map_all  # noqa: E402
from schema import AmbulanceInfo, HospitalInfo  # noqa: E402

# SupabaseEgenClient.__init__()도 같은 .env를 로드하지만, 그건 fetch_hospitals()가
# 호출될 때(즉 이 파일이 이미 import되고 난 뒤)에만 실행된다. 아래
# AMBULANCE_SUPABASE_URL/KEY는 모듈 로드 시점(=import 시점, SupabaseEgenClient가
# 아직 한 번도 안 만들어졌을 수 있는 시점)에 바로 읽으므로, 여기서 미리 명시적으로
# 로드해두지 않으면 .env에 값이 있어도 항상 빈 값으로 읽힌다.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(HOSPITAL_INFORM_INFO_DIR.parent / ".env")

HUB_HOSPITALS_URL = os.environ.get("HUB_HOSPITALS_URL", "http://127.0.0.1:5001/info/hospitals")
HUB_AMBULANCES_URL = os.environ.get("HUB_AMBULANCES_URL", "http://127.0.0.1:5001/info/ambulances")

AMBULANCE_SUPABASE_URL = os.environ.get("AMBULANCE_SUPABASE_URL")
AMBULANCE_SUPABASE_KEY = os.environ.get("AMBULANCE_SUPABASE_KEY")
AMBULANCE_TABLE = "ambulances"

# 재조회 주기 기본값 30분. 운영 중 주기를 바꿔야 하면 코드 수정 없이
# INFO_REFETCH_INTERVAL_SEC 환경변수로 덮어쓴다.
DEFAULT_REFETCH_INTERVAL_SEC = 30 * 60
REFETCH_INTERVAL_SEC = int(os.environ.get("INFO_REFETCH_INTERVAL_SEC", DEFAULT_REFETCH_INTERVAL_SEC))


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


def fetch_ambulances() -> list[AmbulanceInfo]:
    """구급차 Supabase(병원용과 별도 프로젝트, ambulances 테이블)에서 조회한다.
    credential이 없으면 빈 목록을 돌려준다 — 이 기능 없이도 병원 정보
    동기화는 계속 돌아야 한다."""
    if not AMBULANCE_SUPABASE_URL or not AMBULANCE_SUPABASE_KEY:
        print("=== AMBULANCE_SUPABASE_URL/KEY 미설정 — 구급차 정보 동기화 건너뜀 ===")
        return []

    from supabase import create_client

    client = create_client(AMBULANCE_SUPABASE_URL, AMBULANCE_SUPABASE_KEY)
    rows = client.table(AMBULANCE_TABLE).select("apid,name,wgs84_lat,wgs84_lon,voice_port,updated_at").execute().data
    ambulances = [
        AmbulanceInfo(
            apid=row["apid"],
            name=row["name"],
            gps={"lat": row["wgs84_lat"], "lng": row["wgs84_lon"]},
            voicePort=row["voice_port"],
            updatedAt=str(row["updated_at"]),
        )
        for row in rows or []
    ]
    print(f"=== 구급차 Supabase에서 {len(ambulances)}건 조회 ===")
    return ambulances


def send_to_hub(hospital: HospitalInfo) -> None:
    response = requests.post(
        HUB_HOSPITALS_URL,
        data=hospital.to_hub_json(),
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()
    print(f"  [통신] {hospital.hospitalId} {hospital.name} 전송 완료 -> {HUB_HOSPITALS_URL}")


def send_ambulance_to_hub(ambulance: AmbulanceInfo) -> None:
    response = requests.post(
        HUB_AMBULANCES_URL,
        data=ambulance.model_dump_json(),
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()
    print(f"  [통신] {ambulance.apid} {ambulance.name} 전송 완료 -> {HUB_AMBULANCES_URL}")


def sync_once() -> None:
    hospitals = fetch_hospitals()
    print(f"\n=== 병원 정보 {len(hospitals)}건을 feature/hub로 전송 ===")
    for hospital in hospitals:
        send_to_hub(hospital)

    ambulances = fetch_ambulances()
    if ambulances:
        print(f"\n=== 구급차 정보 {len(ambulances)}건을 feature/hub로 전송 ===")
        for ambulance in ambulances:
            send_ambulance_to_hub(ambulance)


def main() -> None:
    """REFETCH_INTERVAL_SEC마다 계속 재조회·재전송한다. hub가 잠깐 안 떠 있어도
    (재시작 등) 이 프로세스 자체는 죽지 않고 다음 주기에 다시 시도한다 —
    voice/hub가 서로의 부재를 조용히 흡수하는 것과 같은 방어 패턴이다.
    """
    while True:
        try:
            sync_once()
        except Exception as e:  # noqa: BLE001 — 한 주기 실패가 상시 프로세스 전체를 죽이면 안 됨
            print(f"  [통신] 이번 주기 갱신 실패, 다음 주기에 재시도: {e}")
        print(f"\n다음 재조회까지 {REFETCH_INTERVAL_SEC}초 대기 (INFO_REFETCH_INTERVAL_SEC 환경변수로 조절 가능)...\n")
        time.sleep(REFETCH_INTERVAL_SEC)


if __name__ == "__main__":
    main()
