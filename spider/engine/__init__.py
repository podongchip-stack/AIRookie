"""spider 엔진 — 거미줄 분배 모델의 파이썬 구현(규칙 기반, 생성형 AI 없음).

map.html(JS)에 있던 계산을 그대로 옮긴 것이라, 같은 입력에 같은 결과를 낸다(`python parity_check.py`로 대조).
나중에 hub가 가져다 쓸 모듈이다 — 다른 폴더(hub·info·sim)를 import 하지 않는다. 읽는 파일은 `hospitals_xyz.json`
(build_xyz.py)과 `roads_data.js`(build_roads_kr.py)뿐이고, 둘 다 같은 폴더에 있다.

    from engine import SpiderEngine
    eng = SpiderEngine()                                # 그래프 로드 수 초
    res = eng.solve(patients, {"tau": 10, "cap": 2})    # 화면이 그리는 결과(JSON)
"""
from __future__ import annotations

import json
import os
import threading
import time

from .model import KTAS_Z, Params, candidates, cond_label, is_full, z_eff
from .roads import NoRoads, RoadGraph, load_roads, straight_km, straight_min
from .scenarios import KDIST, SCN, SCN_LABEL, SITES, PatientList, random_patients
from .solve import cumul, pos_at, solve, to_json

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_HOSPITALS = os.path.join(HERE, "..", "hospitals_xyz.json")

__all__ = ["SpiderEngine", "Params", "PatientList", "KTAS_Z", "SCN", "SCN_LABEL", "SITES", "KDIST", "candidates", "z_eff",
           "is_full", "cond_label", "solve", "to_json", "cumul", "pos_at", "random_patients", "load_roads", "RoadGraph",
           "NoRoads", "straight_km", "straight_min", "load_hospitals"]


def load_hospitals(path: str = DEFAULT_HOSPITALS) -> list[dict]:
    return json.load(open(path, encoding="utf-8"))


class SpiderEngine:
    """병원 목록 + 도로 그래프 + 해소 루프를 한 덩어리로. 요청마다 solve()를 부르면 된다(스레드 안전)."""

    def __init__(self, hospitals_path: str = DEFAULT_HOSPITALS, roads_path: str | None = None):
        self.hospitals = load_hospitals(hospitals_path)
        self.roads = load_roads(roads_path) if roads_path else load_roads()
        self.live = [h for h in self.hospitals if h.get("hasBeds")]
        self.dead = [h for h in self.hospitals if not h.get("hasBeds")]
        self.roads.attach_hospitals(self.live)
        self._lock = threading.Lock()  # 경로 캐시 쓰기 보호

    @property
    def has_roads(self) -> bool:
        return getattr(self.roads, "n", 0) > 0

    def describe(self) -> dict:
        return {"hospitals": len(self.hospitals), "withBeds": len(self.live), "roadNodes": getattr(self.roads, "n", 0),
                "roadLoadSec": round(getattr(self.roads, "load_sec", 0.0), 1), "speedKmh": [80, 55, 45, 35, 25]}

    def solve(self, patients: list[dict], params: dict | Params | None = None, live_beds: dict | None = None) -> dict:
        """live_beds: {hpid: 응급실 가용 수 또는 None(미상)} — hub가 지금 아는 값(이송 확정 차감 반영)으로 스냅샷 값을 덮는다.
        실시간 모드의 '거미줄 제안'이 스냅샷(수집 시점)엔 자리가 있었지만 지금은 만실인 병원을 고르던 문제(2026-10-15)."""
        prm = params if isinstance(params, Params) else Params.from_dict(params)
        live = self.live
        if live_beds:
            live = [{**h, "hvec": live_beds[h["hpid"]]} if h["hpid"] in live_beds else h for h in self.live]
        t0 = time.perf_counter()
        with self._lock:
            res = solve(patients, prm, self.roads, live)
        out = to_json(res)
        out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return out

    def random_patients(self, n: int, width: float, scope: str, kdist: str, seed: int | None = None) -> list[dict]:
        with self._lock:
            return random_patients(n, width, scope, kdist, self.roads, self.live, seed)

    def hospitals_json(self) -> list[dict]:
        """화면에 줄 병원 목록 — 내부 계산용 키(node·_last_mile)는 뺀다."""
        return [{k: v for k, v in h.items() if not k.startswith("_") and k != "node"} for h in self.hospitals]
