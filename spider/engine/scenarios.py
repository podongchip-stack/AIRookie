"""시나리오·무작위 환자 생성 — map.html의 SITES·SCN·KDIST·randomPatients를 옮겼다. 난수는 시드를 받아 재현 가능하다."""
from __future__ import annotations

import math
import random

from .model import KTAS_Z

SITES = {
    "강남역": (37.4981, 127.0276), "시청": (37.5665, 126.9780), "종로3가": (37.5704, 126.9918), "서울역": (37.5547, 126.9707),
    "노원역": (37.6542, 127.0568), "구로디지털단지": (37.5034, 126.8820), "잠실": (37.5145, 127.1059), "홍대입구": (37.5509, 126.9100),
    "건대입구": (37.5386, 127.0824), "연신내": (37.6176, 126.9227),
}
# (위치, KTAS, 발생 분)
SCN = {
    "gangnam": [("강남역", 4, 0), ("강남역", 3, 0), ("강남역", 3, 1), ("강남역", 2, 2), ("강남역", 2, 2), ("강남역", 1, 3)],
    "stagger": [("시청", 2, 0), ("시청", 2, 4), ("시청", 2, 8), ("시청", 2, 12), ("시청", 2, 16)],
    "same2": [("서울역", 2, 0), ("서울역", 2, 0), ("시청", 2, 1), ("시청", 2, 1), ("종로3가", 2, 3), ("종로3가", 2, 3)],
    "turnover": [("시청", 2, 0), ("시청", 2, 20), ("시청", 2, 40), ("시청", 2, 60)],
    "hongdae": [("홍대입구", 4, 0), ("홍대입구", 3, 0), ("홍대입구", 3, 1), ("홍대입구", 2, 1), ("홍대입구", 1, 2), ("시청", 2, 10), ("시청", 3, 10)],
    "custom": [],
}
SCN_LABEL = {
    "gangnam": "강남역 다중 추돌 — 6명, 경증부터 들어오고 중증이 뒤에",
    "stagger": "시청 KTAS 2 × 5명 — 4분 간격 (τ 창 효과)",
    "same2": "도심 KTAS 2 × 6명 — 서울역·시청·종로, 먼 쪽이 먼저 출발",
    "turnover": "강북삼성 앞 반복 — 20분 간격 4명 (회전 효과)",
    "hongdae": "홍대 화재 5명 + 10분 뒤 시청 2명",
    "custom": "직접 구성",
}
KDIST = {"real": (.05, .15, .40, .30, .10), "severe": (.30, .40, .30, 0, 0), "uniform": (.2, .2, .2, .2, .2)}
SEOUL = (37.43, 37.70, 126.77, 127.19)  # lat0, lat1, lng0, lng1


class PatientList:
    """화면의 환자 목록과 같은 규칙으로 id를 매기고 같은 자리 환자를 조금씩 비껴 놓는다(JS addPatient)."""

    def __init__(self):
        self.items: list[dict] = []
        self.next_id = 1

    def add(self, site: str, k: int, t0: float, lat: float | None = None, lng: float | None = None, cond: str | None = None, text: str | None = None) -> dict:
        if lat is None:
            lat, lng = SITES[site]
        n = sum(1 for p in self.items if p["site"] == site)
        ang, r = n * 2.1, 0.0012 if n else 0.0
        p = {"id": self.next_id, "site": site, "k": k, "t0": t0, "lat": lat + r * math.sin(ang), "lng": lng + r * math.cos(ang) * 1.25, "z": KTAS_Z[k]}
        if cond:
            p["cond"] = cond
        if text:
            p["text"] = text
        self.next_id += 1
        self.items.append(p)
        return p

    @classmethod
    def scenario(cls, name: str) -> "PatientList":
        pl = cls()
        for site, k, t0 in SCN[name]:
            pl.add(site, k, t0)
        return pl


def _dice_cond(k: int, r2: float) -> str:
    if k <= 2:
        return "stemi" if r2 < .2 else "stroke" if r2 < .4 else "trauma" if r2 < .5 else "general"
    if k == 3:
        return "stemi" if r2 < .1 else "stroke" if r2 < .2 else "trauma" if r2 < .3 else "general"
    return "general"


def random_patients(n: int, width: float, scope: str, kdist: str, roads, live: list[dict], seed: int | None = None) -> list[dict]:
    """무작위 환자 n명: {k, t0, lat, lng, cond}. scope 'seoul'은 서울 안 도로 노드 중 무작위, 'korea'는 병원 주변 10 km 안.
    id·site는 호출자(PatientList.add)가 붙인다."""
    rng = random.Random(seed)
    dist = KDIST[kdist]
    out = []
    graph = roads if getattr(roads, "n", 0) else None
    for _ in range(n):
        k, r, acc = 1, rng.random(), 0.0
        for j in range(5):
            acc += dist[j]
            if r < acc:
                k = j + 1
                break
        if scope == "korea":
            h = live[int(rng.random() * len(live))]
            rr, a = math.sqrt(rng.random()) * 0.09, rng.random() * math.pi * 2
            lat, lng = h["lat"] + rr * math.sin(a), h["lng"] + rr * math.cos(a) * 1.25
        elif graph is not None:
            lat0, lat1, lng0, lng1 = SEOUL
            v, g = 0, 0
            while True:
                v = int(rng.random() * graph.n)
                if graph.deg[v] > 0 and lat0 <= graph.lat[v] <= lat1 and lng0 <= graph.lng[v] <= lng1:
                    break
                g += 1
                if g >= 100000:
                    break
            lat, lng = float(graph.lat[v]), float(graph.lng[v])
        else:
            lat, lng = 37.45 + rng.random() * 0.22, 126.80 + rng.random() * 0.36
        out.append({"k": k, "t0": math.floor(rng.random() * width + 0.5), "lat": lat, "lng": lng, "cond": _dice_cond(k, rng.random())})
    return out
