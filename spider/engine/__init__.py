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
from datetime import datetime, timezone

from .model import KTAS_Z, Params, candidates, cond_label, is_full, z_eff
from .roads import NoRoads, RoadGraph, load_roads, straight_km, straight_min
from .scenarios import KDIST, SCN, SCN_LABEL, SITES, PatientList, random_patients
from .solve import cumul, pos_at, solve, to_json

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_HOSPITALS = os.path.join(HERE, "..", "hospitals_xyz.json")

__all__ = ["SpiderEngine", "overlay_hub", "Params", "PatientList", "KTAS_Z", "SCN", "SCN_LABEL", "SITES", "KDIST", "candidates", "z_eff",
           "is_full", "cond_label", "solve", "to_json", "cumul", "pos_at", "random_patients", "load_roads", "RoadGraph",
           "NoRoads", "straight_km", "straight_min", "load_hospitals"]


def load_hospitals(path: str = DEFAULT_HOSPITALS) -> list[dict]:
    return json.load(open(path, encoding="utf-8"))


LEVEL_G = {"권역응급의료센터": 4, "지역응급의료센터": 3, "지역응급의료기관": 2, "응급실운영신고기관": 1}


def _iso_epoch(s: str | None) -> float | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        return None


def overlay_hub(live: list[dict], feats: list[dict] | None, live_beds: dict | None = None, now: float | None = None) -> list[dict]:
    """실시간 모드(2026-10-15): 스냅샷 병원 목록에 hub가 지금 아는 값을 덮는다(hub /hospital-features) — hub 순위와 같은 재료로
    거미줄 제안을 계산하려고. 바꾸는 것: 응급실 가용(이송 확정 차감 반영, 미상·1일 넘은 값은 None)·정원·등급·응급의학과 전문의
    수(심평원)·CT·혈관조영 운영(E-Gen), 그리고 새 키 _noGroups(질환군 "불가능" 신고·차단 공지)·_inflight(hub 이송 중 건수)·
    _rel(병상 정보 신뢰도 곡선 — 지금 나이·확인 나이로 환산). hub에 없는 병원은 스냅샷 그대로. live_beds는 hub 특징을 못 받았을
    때의 대비책(화면이 관제 목록에서 넘긴 가용 수)이다."""
    now = time.time() if now is None else now
    fm = {f["hospitalId"]: f for f in feats or []}
    out = []
    for h in live:
        f = fm.get(h["hpid"])
        if f is None and not (live_beds and h["hpid"] in live_beds):
            out.append(h)
            continue
        x = dict(h)
        if f is None:
            x["hvec"] = live_beds[h["hpid"]]
            out.append(x)
            continue
        x["hvec"] = f.get("beds")
        if f.get("erCapacity"):
            x["er_cap"] = f["erCapacity"]
        if f.get("emergencyLevel") in LEVEL_G:
            x["g"] = LEVEL_G[f["emergencyLevel"]]
        if f.get("emSpecialists") is not None:
            x["em"] = f["emSpecialists"]
        for k in ("ct", "angio"):
            if f.get(k):
                x[k] = "Y" if f[k] == "Y" else "N"
        x["_noGroups"] = frozenset(f.get("noGroups") or ())
        x["_inflight"] = int(f.get("inFlight") or 0)
        rel = f.get("bedReliability")
        born = _iso_epoch(rel.get("bornAt")) if rel else None
        if rel and born is not None:
            conf = _iso_epoch(rel.get("confirmedAt"))
            age = max(now - born, 0.0)
            x["_rel"] = {"m": float(rel["predictedSurvivalSec"]), "sigma": float(rel.get("sigma") or 1.0), "age": age,
                         "u": min(max(conf - born, 0.0), age) if (conf is not None and conf > born) else None}
        out.append(x)
    return out


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

    def solve(self, patients: list[dict], params: dict | Params | None = None, live_beds: dict | None = None,
              hub_features: list[dict] | None = None) -> dict:
        """실시간 모드면 hub_features(hub /hospital-features)·live_beds로 스냅샷 병원 값을 덮어 hub와 같은 재료로 계산한다
        (overlay_hub). 실시간 모드의 '거미줄 제안'이 수집 시점엔 자리가 있었지만 지금은 만실인 병원을 고르던 문제(2026-10-15)."""
        prm = params if isinstance(params, Params) else Params.from_dict(params)
        live = overlay_hub(self.live, hub_features, live_beds) if (hub_features or live_beds) else self.live
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
