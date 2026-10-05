"""[demo 브랜치] 병원 정보 고정 스냅샷 — 저장(save)과 시연용 hub에 넣기(load).

녹화마다 병원 후보·병상이 같게 나오도록, 어느 한 시점의 hub 병원 레지스트리(E-Gen·심평원 기반 HospitalInfo
415곳 + 구급차 3대)를 파일 하나로 얼려 둔다. 넣을 때는 모든 시각(updatedAt·bornAt·assessedAt …)을 "지금"으로
같은 만큼 옮긴다 — 정보 나이가 스냅샷 당시 그대로라 병상 신뢰도 확률·"1일 넘은 값" 판정도 그때와 같다.

    python demo/snapshot.py save                    # 실서버 hub 상태 파일(hub/data/state/hub_state.json)에서 저장
    python demo/snapshot.py load http://127.0.0.1:5101   # 시연용 hub에 넣기

⚠ develop에 병합하지 않는다(demo 브랜치 규칙).
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "hub" / "data" / "state" / "hub_state.json"
SNAPSHOT = Path(__file__).resolve().parent / "data" / "hospital_snapshot.json"
SEOUL_AMBULANCES = ROOT / "info" / "ambulance_registry" / "result" / "seoul_ambulances.csv"  # 실서비스가 쓰는 서울 119 구급차 162대
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)$")


def save() -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    snap = {"takenAt": state["savedAt"], "hospitals": state["hospitals"], "ambulances": state["ambulances"]}
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    print(f"저장: {SNAPSHOT} — 병원 {len(snap['hospitals'])}곳, 구급차 {len(snap['ambulances'])}대 (기준 {snap['takenAt']})")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _shift(value, delta):
    if isinstance(value, dict):
        return {k: _shift(v, delta) for k, v in value.items()}
    if isinstance(value, list):
        return [_shift(v, delta) for v in value]
    if isinstance(value, str) and ISO.match(value):
        return (_parse(value) + delta).isoformat()
    return value


def _seoul_ambulances() -> list[dict]:
    """실제 화면의 구급차 목록(서울 119안전센터 구급차 162대). 파일이 없으면 빈 목록 — 스냅샷의 3대로 대신한다."""
    if not SEOUL_AMBULANCES.exists():
        return []
    now = datetime.now(timezone.utc).isoformat()
    out = []
    with SEOUL_AMBULANCES.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            name = r["name"].replace("119안전센터", "")  # 화면에는 "신수 구급 1"처럼 줄여 쓴다
            out.append({"apid": r["apid"], "name": r["name"], "gps": {"lat": float(r["wgs84_lat"]), "lng": float(r["wgs84_lon"])},
                        "voicePort": int(r["voice_port"] or 6000), "source": "rule", "updatedAt": now})
    return out


def load(hub: str) -> None:
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    delta = datetime.now(timezone.utc) - _parse(snap["takenAt"])
    session = requests.Session()
    ambulances = _seoul_ambulances() or [_shift(a, delta) for a in snap["ambulances"]]
    session.post(f"{hub}/info/ambulances/batch", json={"ambulances": ambulances}, timeout=60).raise_for_status()
    session.post(f"{hub}/info/ambulances/roster", json={"apids": [a["apid"] for a in ambulances]}, timeout=30)
    for i, hospital in enumerate(snap["hospitals"], 1):
        session.post(f"{hub}/info/hospitals", json=_shift(hospital, delta), timeout=30).raise_for_status()
        if i % 100 == 0:
            print(f"  병원 {i}/{len(snap['hospitals'])}")
    session.post(f"{hub}/info/hospitals/roster", json={"hospitalIds": [h["hospitalId"] for h in snap["hospitals"]]}, timeout=30)
    print(f"넣음: {hub} — 병원 {len(snap['hospitals'])}곳, 구급차 {len(ambulances)}대 (시각 {delta} 이동)")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "save":
        save()
    elif len(sys.argv) >= 3 and sys.argv[1] == "load":
        load(sys.argv[2].rstrip("/"))
    else:
        print(__doc__)
        sys.exit(1)
