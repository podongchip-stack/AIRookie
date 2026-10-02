"""시뮬레이션 입력 로더 — 전부 이 저장소 안의 실측 데이터만 쓴다 (API 호출 0회).

- 병원 좌표: info/Hospital_inform/info/data/output/<hpid>.json (E-Gen 좌표 캐시)
- 가용 병상: info/Hospital_inform/info/data/snapshots_nationwide/<날짜>.jsonl 에서
  병상 오퍼레이션(getEmrrmRltmUsefulSckbdInfoInqire) 기록 중 목표 시각에 가장 가까운 것.
  스냅샷 파일에는 중증질환 등 다른 오퍼레이션 기록도 섞여 있어 반드시 operation으로 거른다.
- hvec 해석은 egen/mapper.py 의 2026-10-01 합의와 동일: 음수는 미입력이 아니라
  과밀(가용 0), 키가 없으면 미상이라 후보에서 제외한다.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: 이태원역 1번 출구 앞 — 2022-10-29 참사 현장과 같은 블록.
SCENE_LAT, SCENE_LNG = 37.53465, 126.99418

REPO_ROOT = Path(__file__).resolve().parent.parent
INFO_DATA = REPO_ROOT / "info" / "Hospital_inform" / "info" / "data"
COORDS_DIR = INFO_DATA / "output"
SNAPSHOT_DIR = INFO_DATA / "snapshots_nationwide"

BED_OPERATION = "getEmrrmRltmUsefulSckbdInfoInqire"


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


@dataclass
class Hospital:
    hpid: str
    name: str
    lat: float
    lng: float
    capacity: int          # 스냅샷 시점 가용 병상(hvec, 음수는 0으로)
    distance_km: float     # 현장에서 직선거리


def load_coords(coords_dir: Path = COORDS_DIR) -> dict[str, tuple[str, float, float]]:
    coords: dict[str, tuple[str, float, float]] = {}
    for path in sorted(coords_dir.glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        gps = d.get("gps") or {}
        if "lat" in gps and "lng" in gps:
            coords[d["hospitalId"]] = (d["name"], gps["lat"], gps["lng"])
    if not coords:
        raise SystemExit(f"병원 좌표 캐시가 비어 있다: {coords_dir}")
    return coords


def load_beds(snapshot_date: str, target_hhmm: str, snapshot_dir: Path = SNAPSHOT_DIR) -> tuple[str, dict[str, int]]:
    """해당 날짜 스냅샷에서 목표 시각(HH:MM)에 가장 가까운 병상 기록을 고른다.

    반환: (기록의 실제 ts, {hpid: 가용 병상 수}). hvec가 없거나 숫자가 아니면 그 병원은 뺀다.
    """
    path = snapshot_dir / f"{snapshot_date}.jsonl"
    if not path.exists():
        available = sorted(p.stem for p in snapshot_dir.glob("*.jsonl"))
        raise SystemExit(f"스냅샷 없음: {path}\n있는 날짜: {available}")
    target = datetime.fromisoformat(f"{snapshot_date}T{target_hhmm}:00+09:00")
    best_ts, best_items, best_gap = None, None, None
    with path.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("operation") != BED_OPERATION:
                continue
            items = rec.get("items")
            if not items:
                continue  # 수집 실패·빈 응답 폴링은 건너뛴다
            ts = datetime.fromisoformat(rec["ts"])
            gap = abs((ts - target).total_seconds())
            if best_gap is None or gap < best_gap:
                best_ts, best_items, best_gap = rec["ts"], items, gap
    if best_items is None:
        raise SystemExit(f"{path}에 병상 오퍼레이션 기록이 없다")
    beds: dict[str, int] = {}
    for item in best_items:
        raw = item.get("hvec")
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        # 음수(-1 등)는 과밀 — 미상이 아니라 "가용 0이 확인됨" (egen/mapper.py와 동일 해석)
        beds[item["hpid"]] = max(value, 0)
    return best_ts, beds


def build_world(
    snapshot_date: str = "2026-10-02",
    target_hhmm: str = "22:15",
    radius_km: float = 10.0,
) -> tuple[str, list[Hospital]]:
    """현장 반경 안의, 좌표와 병상이 모두 확인된 병원 목록(거리순)."""
    coords = load_coords()
    snapshot_ts, beds = load_beds(snapshot_date, target_hhmm)
    hospitals: list[Hospital] = []
    for hpid, (name, lat, lng) in coords.items():
        if hpid not in beds:
            continue  # 병상 미상 — 시뮬레이션 세계에서는 수용 능력을 정의할 수 없어 제외
        distance = haversine_km(SCENE_LAT, SCENE_LNG, lat, lng)
        if distance > radius_km:
            continue
        hospitals.append(Hospital(hpid, name, lat, lng, beds[hpid], round(distance, 2)))
    hospitals.sort(key=lambda h: h.distance_km)
    if not hospitals:
        raise SystemExit("반경 안에 병원이 없다 — radius_km 또는 스냅샷 날짜를 확인")
    return snapshot_ts, hospitals


if __name__ == "__main__":
    ts, hospitals = build_world()
    total = sum(h.capacity for h in hospitals)
    print(f"스냅샷 {ts} — 반경 10km 병원 {len(hospitals)}곳, 가용 병상 합 {total}")
    for h in hospitals:
        print(f"  {h.distance_km:5.2f}km  {h.capacity:3d}병상  {h.name} ({h.hpid})")
