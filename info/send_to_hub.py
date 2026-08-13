"""병원 정보(HospitalInfo)를 feature/hub로 전송한다.

**2026-08-13부로 병원 Supabase 의존을 완전히 제거했다.** 목록·병상·중증질환
수용가능정보 전부 실 E-Gen API(`HttpEgenClient`)에서 가져온다. 예전엔 병상만
Supabase 대체 DB에 남겨뒀었다 — E-Gen이 조회 전용이라 hub의 이송 확정
(final_approval) 차감을 되돌려 쓸 방법이 없어서였다. 그 문제는 이제 hub
쪽 **TTL 병상 오버레이**(`hub_engine.py`의 `_bed_overlay`, 15분)로 대신
푼다 — hub가 차감분을 짧게만 자기 메모리에 얹어 보여주고, 그 사이 E-Gen이
직접 갱신되는 값(`hvidate` 갱신 중앙값 5분 실측)으로 자연히 맞춰진다. 이
전환으로 Supabase의 7개 병원 대응표(`SUPABASE_TO_EGEN_HPID`, 이제 삭제)
병목이 없어져 E-Gen이 주는 병원 전체가 hub로 흘러간다.

**2026-08-13 지역 범위도 서울에서 전국으로 확장했다.** `HttpEgenClient`의
`stage1`/`q0` 기본값을 `"서울특별시"`에서 빈 문자열로 바꿨다(`egen/client.py`) —
빈 문자열은 시도 전체(전국)를 뜻하고, 호출 횟수는 서울만 받을 때와 같다(같은
근거로 `snapshot_nationwide.bat`이 이미 전국을 그렇게 받고 있었다). 따라서 이제
기본 실행 시 전국 500여 곳이 매 주기 hub로 흘러간다.

목록·병상·중증질환 셋 다 이제 실 API 하나에서 나오므로, 실 API 호출이
실패하면(서비스키 문제, 트래픽 한도, 일시 장애) 대체할 소스가 없다 — 이번
주기는 그냥 건너뛰고 다음 주기에 재시도한다(외부 API 장애가 상시 프로세스
자체를 죽이면 안 된다는 기존 방어 원칙은 그대로 유지).

같은 사이클에서 병원마다 info-v2(`hospital_score/`) 신뢰도 진단도 붙인다
(`_attach_assessments()`). 심평원 조인·전문의 수 캐시(`hira.py --build-join`)가
없거나 낡았어도, 혹은 어떤 이유로든 판정에 실패해도 `assessment` 없이
원래 병원 정보 그대로 전송한다 — `hospital_score/`가 죽어도 기존 경로가
안 죽는다는 그 폴더 자체의 원칙과 같다.

병원 정보는 계속 바뀌는데 hub는 한 번 받은 값을 메모리에 들고 있을 뿐
스스로 재조회하지 않는다. 그래서 이 스크립트는 한 번 실행하고 끝나는 게
아니라 REFETCH_INTERVAL_SEC마다 계속 재조회·재전송하는 상시 프로세스로
돈다 (팀 논의 결과 — Supabase realtime 구독 대신 주기적 재조회 방식을 택함).

같은 주기로 구급차 레지스트리(Supabase `ambulances` 테이블 — 병원용과는
**별도의** Supabase 프로젝트, 이번 변경과 무관)도 읽어 hub에 보낸다.
`AMBULANCE_SUPABASE_URL`/`AMBULANCE_SUPABASE_KEY` 환경변수가 없으면(아직
그 프로젝트 credential을 안 받은 팀원 등) 조용히 건너뛴다 — 병원 정보
동기화는 그것과 무관하게 계속 돈다.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

#: `hospital_score.dataset.parse_hvidate()`가 hvidate를 naive KST로 돌려주므로
#: (E-Gen이 한국 현지 시각을 그대로 주기 때문), staleness 계산에 쓰는 "지금"도
#: naive UTC가 아니라 naive KST로 맞춰야 한다 — 안 맞추면 9시간(KST-UTC) 차이만큼
#: feedAgeMinutes가 음수로 나온다(egen/mapper.py의 KST 상수와 같은 값).
KST = timezone(timedelta(hours=9))

HOSPITAL_INFORM_INFO_DIR = Path(__file__).resolve().parent / "Hospital_inform" / "info"
sys.path.insert(0, str(HOSPITAL_INFORM_INFO_DIR))

from egen.client import HttpEgenClient  # noqa: E402
from egen.mapper import map_all  # noqa: E402
from schema import AmbulanceInfo, HospitalInfo  # noqa: E402
from hospital_score import dataset as hs_dataset  # noqa: E402
from hospital_score import scoring as hs_scoring  # noqa: E402
from hospital_score import vocabulary as hs_vocab  # noqa: E402

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

def _to_float(raw: object) -> float | None:
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        return None


def _build_score_inputs(
    location_rows: list[dict], severe_rows: list[dict], bed_rows: list[dict]
) -> tuple[dict[str, hs_dataset.Hospital], hs_dataset.Frame]:
    """이번 사이클에 실 API에서 받은 raw rows로 hospital_score가 요구하는
    D.Hospital/D.Frame을 그 자리에서 만든다.

    hospital_score.dataset의 load_hospitals()/load_frames()와 완전히 같은
    변환이지만, 스냅샷 JSONL 파일이 아니라 이번 사이클의 메모리 상 rows에
    적용한다 — snapshot_nationwide.bat 같은 별도 상시 수집 프로세스가 떠
    있어야만 신뢰도 판정이 되는 숨은 의존을 만들지 않기 위해서다.
    """
    hospitals: dict[str, hs_dataset.Hospital] = {}
    for row in location_rows:
        hpid = (row.get("hpid") or "").strip()
        if not hpid:
            continue
        hospitals[hpid] = hs_dataset.Hospital(
            hpid=hpid,
            name=(row.get("dutyName") or "").strip(),
            emcls=(row.get("dutyEmclsName") or "").strip() or None,
            lat=_to_float(row.get("wgs84Lat")),
            lon=_to_float(row.get("wgs84Lon")),
        )

    frame = hs_dataset.Frame(ts=datetime.now(KST).replace(tzinfo=None))
    for row in bed_rows:
        hpid = (row.get("hpid") or "").strip()
        if hpid:
            frame.beds[hpid] = row
    for row in severe_rows:
        hpid = (row.get("hpid") or "").strip()
        if not hpid:
            continue
        values: dict[int, str] = {}
        messages: dict[int, str] = {}
        for item in hs_vocab.ITEMS:
            value = hs_vocab.normalize_accept(row.get(item.field))
            if value is not None:
                values[item.no] = value
            if item.msg_field:
                text = (row.get(item.msg_field) or "").strip()
                if text:
                    messages[item.no] = text
        frame.accept[hpid] = values
        if messages:
            frame.accept_msg[hpid] = messages

    return hospitals, frame


def _attach_assessments(
    hospitals: list[HospitalInfo],
    location_rows: list[dict],
    severe_rows: list[dict],
    bed_rows: list[dict],
) -> list[HospitalInfo]:
    """병원마다 info-v2(hospital_score) 신뢰도 진단을 붙인다.

    심평원 조인·전문의 수 캐시가 없거나(`hira.py --build-join`을 아직 한 번도
    안 돌렸으면), 특정 병원 판정에 실패해도 원래 HospitalInfo를 그대로 돌려준다
    — hospital_score/ 쪽 문제가 병원 목록 전송 자체를 막으면 안 된다는
    원칙(hospital_score/README.md)을 그대로 따른다.
    """
    try:
        score_hospitals, frame = _build_score_inputs(location_rows, severe_rows, bed_rows)
        now = frame.ts.replace(tzinfo=None)
        specialists = hs_scoring.load_specialists()
        designations = hs_scoring.load_designations()
    except Exception as e:  # noqa: BLE001 — 신뢰도 판정 실패가 병원 목록 전송을 막으면 안 됨
        print(f"  [hospital_score] 채점 입력 구성 실패, 이번 주기는 신뢰도 판정 없이 전송: {e}")
        return hospitals

    assessed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    enriched: list[HospitalInfo] = []
    attached = 0
    for info in hospitals:
        score_hospital_obj = score_hospitals.get(info.hospitalId)
        if score_hospital_obj is None:
            enriched.append(info)
            continue
        try:
            score = hs_scoring.score_hospital(score_hospital_obj, frame, now, specialists, designations)
            merged = hs_scoring.build_payload(info.model_dump(mode="json"), score, assessed_at)
            enriched.append(HospitalInfo.model_validate(merged))
            attached += 1
        except Exception as e:  # noqa: BLE001 — 병원 1곳 판정 실패가 나머지를 막으면 안 됨
            print(f"  [hospital_score] {info.hospitalId} 신뢰도 판정 실패, 원본 그대로 전송: {e}")
            enriched.append(info)

    print(f"  [hospital_score] {attached}/{len(hospitals)}곳에 신뢰도 진단 첨부"
          f"{' (심평원 캐시 없으면 0건 — hira.py --build-join 필요)' if attached == 0 else ''}")
    return enriched


def fetch_hospitals() -> list[HospitalInfo]:
    """목록·병상·중증질환 수용가능정보를 전부 실 E-Gen API에서 가져와 합치고,
    병원마다 info-v2 신뢰도 진단을 붙인다.

    실 API 호출이 실패하면(서비스키 문제, 일일 트래픽 한도 초과, 일시 장애 등)
    대체할 소스가 없으므로 이번 주기는 건너뛰고 빈 목록을 돌려준다 — 외부 API
    장애가 상시 프로세스 전체를 멈추면 안 된다는 기존 방어 원칙은 유지하되,
    Supabase 폴백은 더 이상 존재하지 않는다(모듈 docstring 참고).
    """
    try:
        http = HttpEgenClient()
        bed_rows = http.get_realtime_beds()
        location_rows = http.get_list_info()
        severe_rows = http.get_severe_illness()
        print("=== E-Gen 실 API에서 목록·병상·중증질환 정보 조회 ===")
    except Exception as e:  # noqa: BLE001 — 실 API 장애가 상시 프로세스를 죽이면 안 됨
        print(f"  [E-Gen] 실 API 조회 실패, 이번 주기는 건너뛰고 다음 주기에 재시도: {e}")
        return []

    hospitals, report = map_all(bed_rows, location_rows, severe_rows)
    print(report.summary())

    hospitals = _attach_assessments(hospitals, location_rows, severe_rows, bed_rows)
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
