"""전국 도로 그래프 — roads_data.js(build_roads_kr.py 산출)를 읽어 최단경로를 계산한다.

map.html(JS 엔진)의 그래프 처리를 파이썬으로 옮긴 것이다. 결과가 JS와 같아야 하므로(parity_check.py가 대조)
세부 규칙을 그대로 따른다:
  - 간선 가중치(분) = 직선 km ÷ 등급별 속도(80/55/45/35/25 km/h) × 60, **Float32로 저장**(JS `wt`가 Float32Array)
  - 최근접 노드는 cKDTree가 아니라 JS와 같은 약 1 km 격자 고리 탐색(반경 0~5칸, 경도에 0.79 가중)
  - 탐색은 120분에서 끊는다(MAX_ROUTE_MIN). 다익스트라는 scipy(C)로 돌리고 선행자 배열로 경로 좌표를 복원한다
  - 출발점별 표(모든 병원까지의 분)는 소수 5자리 키로 150개까지 FIFO 캐시(JS runCache와 같음)

도로 그래프는 경로 계산에만 쓰고 화면엔 그리지 않는다. 그래프 로드는 한 번에 수 초, 메모리 약 200 MB.
"""
from __future__ import annotations

import base64
import json
import math
import os
import time
from collections import OrderedDict

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROADS = os.path.join(HERE, "..", "roads_data.js")

SPEED = (80.0, 55.0, 45.0, 35.0, 25.0)   # 등급별 자유흐름 속도(km/h). 구급차 보정 없음(초안)
MAX_ROUTE_MIN = 120.0                     # 이 시간 너머 병원은 탐색하지 않는다
EARTH_R = 6371.0
TABLE_CACHE_MAX = 150


def straight_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    """두 점 사이 대권 거리(km). JS straightKm과 같은 식."""
    d_lat = math.radians(b_lat - a_lat)
    d_lng = math.radians(b_lng - a_lng)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat)) * math.sin(d_lng / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def straight_min(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    """도로가 없을 때의 직선 추정(분): 직선 km × 1.35(우회) ÷ 25 km/h. JS straightMin과 같다."""
    return straight_km(a_lat, a_lng, b_lat, b_lng) * 1.35 / 25.0 * 60.0


def _hav_km_vec(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


class RoadGraph:
    """roads_data.js 한 벌. 상태는 캐시뿐이라 여러 요청이 돌려 써도 된다(쓰기는 호출자가 잠근다)."""

    def __init__(self, path: str = DEFAULT_ROADS):
        t0 = time.time()
        raw = open(path, encoding="utf-8").read()
        r = json.loads(raw[raw.index("{"):raw.rstrip().rstrip(";").rindex("}") + 1])
        self.bbox = tuple(r["bbox"])  # lng0, lng1, lat0, lat1
        x0, x1, y0, y1 = self.bbox
        if r.get("scale"):
            q = np.frombuffer(base64.b64decode(r["npos"]), dtype=np.int32)
            lng = q[0::2] / r["scale"]
            lat = q[1::2] / r["scale"]
        else:  # 예전 u16 양자화 형식
            q = np.frombuffer(base64.b64decode(r["npos"]), dtype=np.uint16)
            lng = x0 + (x1 - x0) * q[0::2] / 65535.0
            lat = y0 + (y1 - y0) * q[1::2] / 65535.0
        self.lat = np.ascontiguousarray(lat, dtype=np.float64)
        self.lng = np.ascontiguousarray(lng, dtype=np.float64)
        self.n = n = len(self.lat)
        wn = np.frombuffer(base64.b64decode(r["wn"]), dtype=np.uint32)
        starts = np.frombuffer(base64.b64decode(r["starts"]), dtype=np.uint32)
        wcls = np.frombuffer(base64.b64decode(r["wcls"]), dtype=np.uint8)

        # 간선: 각 way 안의 연속 노드 쌍 (JS와 같이 양방향)
        lens = np.diff(starts.astype(np.int64))
        way_of_vertex = np.repeat(np.arange(len(wcls)), lens)
        a = wn[:-1].astype(np.int64)
        b = wn[1:].astype(np.int64)
        same_way = way_of_vertex[:-1] == way_of_vertex[1:]
        a, b, w = a[same_way], b[same_way], way_of_vertex[:-1][same_way]
        sp = np.array(SPEED, dtype=np.float64)[wcls[w]]
        minutes = _hav_km_vec(self.lat[a], self.lng[a], self.lat[b], self.lng[b]) / sp * 60.0
        # JS는 Float32Array에 담는다 — 같은 합이 나오도록 Float32로 반올림한 뒤 Float64로 올린다
        minutes = minutes.astype(np.float32).astype(np.float64)
        # scipy 희소행렬은 같은 (a,b) 간선을 더해 버리므로(평행 간선) 짧은 쪽만 남긴다 — JS는 둘 다 두고 다익스트라가 짧은 쪽을 고른다
        rows = np.concatenate([a, b])
        cols = np.concatenate([b, a])
        vals = np.concatenate([minutes, minutes])
        key = rows * n + cols
        uniq, inv = np.unique(key, return_inverse=True)
        best = np.full(len(uniq), np.inf)
        np.minimum.at(best, inv, vals)
        # 길이 0 간선(같은 자리 노드)은 희소행렬에서 '없는 간선'으로 읽힐 수 있어 아주 작은 값으로 둔다
        best = np.maximum(best, 1e-9)
        self.graph = csr_matrix((best, (uniq // n, uniq % n)), shape=(n, n))
        self.deg = np.diff(self.graph.indptr)

        # 공간 격자(약 1 km) — JS G.nearest와 같은 규칙. 셀마다 노드를 **내림차순**으로 두면 JS의 연결 리스트
        # (나중에 넣은 노드가 앞) 순회 순서와 같아 동률일 때 같은 노드를 고른다.
        self.GX = max(50, round((x1 - x0) * 88.8))
        self.GY = max(50, round((y1 - y0) * 111.0))
        live = np.nonzero(self.deg > 0)[0]
        cx = np.minimum(self.GX - 1, np.maximum(0, ((self.lng[live] - x0) / (x1 - x0) * self.GX).astype(np.int64)))
        cy = np.minimum(self.GY - 1, np.maximum(0, ((self.lat[live] - y0) / (y1 - y0) * self.GY).astype(np.int64)))
        cell = cy * self.GX + cx
        order = np.lexsort((-live, cell))
        self._cell_nodes = live[order]
        self._cell_start = np.searchsorted(cell[order], np.arange(self.GX * self.GY + 1))
        self._table_cache: OrderedDict[str, dict] = OrderedDict()
        self.load_sec = time.time() - t0

    # ── 좌표 ↔ 노드 ──
    def in_bbox(self, lat: float, lng: float) -> bool:
        x0, x1, y0, y1 = self.bbox
        return y0 <= lat <= y1 and x0 <= lng <= x1

    def _cx(self, v: float) -> int:
        x0, x1 = self.bbox[0], self.bbox[1]
        return min(self.GX - 1, max(0, int((v - x0) / (x1 - x0) * self.GX)))

    def _cy(self, v: float) -> int:
        y0, y1 = self.bbox[2], self.bbox[3]
        return min(self.GY - 1, max(0, int((v - y0) / (y1 - y0) * self.GY)))

    def nearest(self, lat: float, lng: float) -> int:
        """가장 가까운 (연결된) 도로 노드. 격자 고리를 0~5칸까지 넓히며 처음 찾은 고리에서 멈춘다. 없으면 -1."""
        X, Y = self._cx(lng), self._cy(lat)
        for rad in range(6):
            cand = []
            for yy in range(Y - rad, Y + rad + 1):
                for xx in range(X - rad, X + rad + 1):
                    if xx < 0 or yy < 0 or xx >= self.GX or yy >= self.GY:
                        continue
                    if max(abs(xx - X), abs(yy - Y)) != rad:
                        continue
                    c = yy * self.GX + xx
                    s, e = self._cell_start[c], self._cell_start[c + 1]
                    if e > s:
                        cand.append(self._cell_nodes[s:e])
            if not cand:
                continue
            nodes = np.concatenate(cand)
            d = (self.lat[nodes] - lat) ** 2 + ((self.lng[nodes] - lng) * 0.79) ** 2
            return int(nodes[int(np.argmin(d))])  # argmin은 첫 최소 — JS의 `d<bd`(엄격)와 같은 동률 처리
        return -1

    def node_ll(self, i: int) -> list[float]:
        return [float(self.lng[i]), float(self.lat[i])]

    # ── 최단경로 ──
    def dijkstra(self, src: int) -> tuple[np.ndarray, np.ndarray, int]:
        """src에서 120분 안의 모든 노드까지. (dist, prev, 정착 노드 수). prev는 없으면 -1."""
        dist, pred = dijkstra(self.graph, directed=False, indices=src, limit=MAX_ROUTE_MIN, return_predecessors=True)
        pred = np.where(pred < 0, -1, pred)
        settled = int(np.count_nonzero(np.isfinite(dist)))
        return dist, pred, settled

    def table_from(self, lat: float, lng: float, hospitals: list[dict]) -> dict:
        """출발점 → 모든 병원(분) + 선행자 트리. hospitals 원소는 node(최근접 노드, 없으면 -1)·hpid·lat·lng를 가진다.
        JS tableFrom과 같은 캐시 키(소수 5자리)·FIFO 150."""
        key = f"{lat:.5f},{lng:.5f}"
        hit = self._table_cache.get(key)
        if hit is not None:
            return hit
        s0 = self.nearest(lat, lng) if self.in_bbox(lat, lng) else -1
        if s0 >= 0:
            dist, prev, settled = self.dijkstra(s0)
            first = straight_min(lat, lng, float(self.lat[s0]), float(self.lng[s0]))
            row = {}
            for h in hospitals:
                node = h.get("node", -1)
                d = dist[node] if node >= 0 else math.inf
                row[h["hpid"]] = (float(d) + first + h["_last_mile"]) if math.isfinite(d) else None
            out = {"row": row, "src": s0, "prev": prev, "settled": settled}
        else:
            out = {"row": {h["hpid"]: None for h in hospitals}, "src": -1, "prev": None, "settled": 0}
        if len(self._table_cache) > TABLE_CACHE_MAX:
            self._table_cache.popitem(last=False)
        self._table_cache[key] = out
        return out

    def route_to(self, lat: float, lng: float, h: dict, hospitals: list[dict]) -> tuple[list[list[float]], float]:
        """출발점 → 병원 경로 좌표([lng,lat] 목록)와 그 길이(km). 경로가 없으면 직선 두 점."""
        t = self.table_from(lat, lng, hospitals)
        node = h.get("node", -1)
        d = t["row"].get(h["hpid"])
        if t["prev"] is not None and node >= 0 and d is not None:
            prev = t["prev"]
            coords = []
            v, guard = node, 0
            while v >= 0 and guard < self.n:
                coords.append(self.node_ll(v))
                v = int(prev[v])
                guard += 1
            coords.reverse()
            coords.insert(0, [lng, lat])
            coords.append([h["lng"], h["lat"]])
            km = 0.0
            for i in range(1, len(coords)):
                km += straight_km(coords[i - 1][1], coords[i - 1][0], coords[i][1], coords[i][0])
            return coords, km
        return [[lng, lat], [h["lng"], h["lat"]]], straight_km(lat, lng, h["lat"], h["lng"])

    def attach_hospitals(self, hospitals: list[dict]) -> None:
        """병원마다 최근접 노드와 '노드 → 병원' 직선 추정분을 붙인다(JS `h.node`, tableFrom의 마지막 항)."""
        for h in hospitals:
            node = self.nearest(h["lat"], h["lng"]) if self.in_bbox(h["lat"], h["lng"]) else -1
            h["node"] = node
            h["_last_mile"] = straight_min(h["lat"], h["lng"], float(self.lat[node]), float(self.lng[node])) if node >= 0 else 0.0


class NoRoads:
    """도로 그래프 파일이 없을 때의 대체 — 전부 직선 추정. JS에서 ROADS_RAW가 없을 때와 같다."""

    n = 0
    load_sec = 0.0

    def attach_hospitals(self, hospitals: list[dict]) -> None:
        for h in hospitals:
            h["node"] = -1
            h["_last_mile"] = 0.0

    def table_from(self, lat: float, lng: float, hospitals: list[dict]) -> dict:
        return {"row": {h["hpid"]: None for h in hospitals}, "src": -1, "prev": None, "settled": 0}

    def route_to(self, lat: float, lng: float, h: dict, hospitals: list[dict]):
        return [[lng, lat], [h["lng"], h["lat"]]], straight_km(lat, lng, h["lat"], h["lng"])


def load_roads(path: str = DEFAULT_ROADS):
    return RoadGraph(path) if os.path.exists(path) else NoRoads()
