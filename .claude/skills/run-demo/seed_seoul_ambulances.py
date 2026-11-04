"""시연 hub에 서울 119안전센터 구급차 162대를 넣는다(2026-11-04) — "[시연] 구급 N호차" 같은 가짜 이름 대신 실제 센터·위치.

자료: info/ambulance_registry/result/seoul_ambulances.csv(소방청 공공데이터 → 센터 주소 좌표, 커밋됨). 운영에서 info가
Supabase ambulances 테이블에서 읽어 hub로 보내는 것과 같은 내용·형식(이름 "<센터명> 구급 N")이다. 묶음 전송 뒤 목록 동기화로
목록에 없는 구급차(예전 시드의 A0000001~ 등)는 hub가 지운다 — 진행 중 사건이 있는 구급차는 hub가 남긴다.
위치·대수만 실데이터이고 출동·이동은 시뮬레이션이다.

실행:  python seed_seoul_ambulances.py   (hub가 127.0.0.1:5001에 떠 있어야 한다)
"""
import csv
from datetime import datetime, timezone
from pathlib import Path

import requests

HUB = "http://127.0.0.1:5001"
CSV = Path(__file__).resolve().parents[3] / "info" / "ambulance_registry" / "result" / "seoul_ambulances.csv"

now = datetime.now(timezone.utc).isoformat(timespec="seconds")
with CSV.open(encoding="utf-8") as f:
    rows = list(csv.DictReader(f))
ambulances = [{
    "apid": r["apid"], "name": r["name"],
    "gps": {"lat": float(r["wgs84_lat"]), "lng": float(r["wgs84_lon"])},
    "voicePort": int(r["voice_port"] or 6000), "updatedAt": now,
} for r in rows]
res = requests.post(f"{HUB}/info/ambulances/batch", json={"ambulances": ambulances}, timeout=30)
res.raise_for_status()
roster = requests.post(f"{HUB}/info/ambulances/roster", json={"apids": [a["apid"] for a in ambulances]}, timeout=30)
roster.raise_for_status()
print(f"서울 119안전센터 구급차 {len(ambulances)}대 주입 — {res.json()} / 목록 동기화 {roster.json()}")
