"""병원 정보(HospitalInfo)를 feature/hub로 전송한다.

E-Gen 서비스키가 승인(2026-08-10)되어 병원 목록·좌표·중증질환 수용가능정보는
실제 E-Gen API(`HttpEgenClient`)에서 가져온다. 단, 실시간 병상 수(hvec)는
지금도 Supabase 대체 DB(`SupabaseEgenClient`)에서 가져온다 — E-Gen은 조회
전용 공개 API라 hub가 이송 확정(final_approval) 시 차감한 병상 수를 되돌려
쓸 방법이 없다(`egen/client.py`의 `HttpEgenClient.update_bed_count()` 참고).
병상까지 실 API로 읽으면 이 스크립트가 재조회할 때마다(기본 30분) hub가 이미
차감해둔 값이 차감 안 된 원래 값으로 되돌아가버려(`hub_engine.py`의
`update_hospital_info()`는 feature/info 전송 재시도 대기열에 걸린 경우만
덮어쓰기를 막고 이 경우는 막지 않는다) 뺑뺑이 방지라는 목적과 정반대로 간다.
그래서 병상만 우리가 직접 쓸 수 있는 Supabase에 남겨, hub의 차감이 다음
재조회에도 그대로 유지되게 한다(`fetch_hospitals()` 참고). 매퍼 로직
(`egen/mapper.py`)은 소스가 섞여도 hpid 기준으로 그대로 합쳐지므로 손대지
않았다.

Supabase/실 API 어느 쪽이든 병원 정보는 계속 바뀌는데 hub는 한 번 받은 값을
메모리에 들고 있을 뿐 스스로 재조회하지 않는다. 그래서 이 스크립트는 한 번
실행하고 끝나는 게 아니라 REFETCH_INTERVAL_SEC마다 계속 재조회·재전송하는
상시 프로세스로 돈다 (팀 논의 결과 — Supabase realtime 구독 대신 주기적
재조회 방식을 택함). 그 주기 사이에 생기는 병상 변동은 hub가 이송 확정
(final_approval) 시 보내는 HospitalBedUpdate로 보정한다 (info/app.py,
info/README.md "hub → info" 참고).

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

from egen.client import HttpEgenClient, SupabaseEgenClient  # noqa: E402
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

# Supabase 대체 DB는 E-Gen 서비스키 승인 전에 만들어져 실제 hpid를 몰랐고,
# 자체 식별자(S0000001~7)를 붙였다 — 실 API의 hpid(A11...)와 전혀 다른 값이라
# 그대로는 hpid 기준으로 join(map_all)할 수 없다. 두 소스의 좌표를 대조해
# (전부 최근접 병원까지 거리 1.2km 이내로 확인됨) 수기로 검증한 대응표.
# 이 7개 병원 구성이 바뀌면(추가/교체) 같이 갱신해야 한다.
SUPABASE_TO_EGEN_HPID = {
    "S0000001": "A1100017",  # 서울대학교병원
    "S0000002": "A1100008",  # 고려대학교안암병원 (실 API명: 학교법인고려중앙학원고려대학교의과대학부속병원(안암병원))
    "S0000003": "A1100035",  # 서울의료원 (실 API명: 서울특별시서울의료원)
    "S0000004": "A1100014",  # 고려대학교구로병원 (실 API명: 고려대학교의과대학부속구로병원)
    "S0000005": "A1100005",  # 이화여자대학교목동병원 (실 API명: 이화여자대학교의과대학부속목동병원)
    "S0000006": "A1100013",  # 한양대학교병원
    "S0000007": "A1100043",  # 강동경희대학교병원
}
_EGEN_TO_SUPABASE_HPID = {egen: supabase for supabase, egen in SUPABASE_TO_EGEN_HPID.items()}


def _remap_to_supabase_hpid(rows: list[dict]) -> list[dict]:
    """실 API 응답의 hpid를 Supabase hpid로 바꿔 bed_rows와 join되게 한다.
    대응표 밖의 기관(서울 전체 74곳 중 우리가 다루는 7곳이 아닌 나머지)은
    이번 매칭 대상이 아니므로 제외한다."""
    remapped = []
    for row in rows:
        supabase_hpid = _EGEN_TO_SUPABASE_HPID.get(row.get("hpid"))
        if supabase_hpid is None:
            continue
        remapped.append({**row, "hpid": supabase_hpid})
    return remapped


def fetch_hospitals() -> list[HospitalInfo]:
    """병상 수는 Supabase에서, 목록·좌표·중증질환 수용가능정보는 실 E-Gen API에서
    가져와 합친다 (모듈 docstring의 이유 참고).

    실 API 호출이 실패하면(서비스키 미설정, 일일 트래픽 한도 초과, 일시 장애 등)
    이번 주기는 목록·중증질환 정보도 Supabase 값으로 대체해 계속 돈다 — 외부
    API 장애가 상시 프로세스 전체를 멈추면 안 된다는 기존 방어 원칙과 동일하다.
    """
    supabase = SupabaseEgenClient()
    bed_rows = supabase.get_realtime_beds()

    try:
        http = HttpEgenClient()
        location_rows = _remap_to_supabase_hpid(http.get_list_info())
        severe_rows = _remap_to_supabase_hpid(http.get_severe_illness())
        print("=== E-Gen 실 API에서 목록·중증질환 정보 조회 (병상은 Supabase 유지) ===")
    except Exception as e:  # noqa: BLE001 — 실 API 장애가 상시 프로세스를 죽이면 안 됨
        print(f"  [E-Gen] 실 API 조회 실패, 이번 주기는 목록·중증질환도 Supabase 값으로 대체: {e}")
        location_rows = supabase.get_list_info()
        severe_rows = supabase.get_severe_illness()

    hospitals, report = map_all(bed_rows, location_rows, severe_rows)
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
