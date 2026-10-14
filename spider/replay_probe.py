"""검증 ①: 낡은 병상 정보의 비용과 재투척 효과 — E-Gen 스냅샷 재생.

시각 t의 (lag 분 낡은) 스냅샷으로 병원을 고르고, 도착 시각의 스냅샷으로 채점한다(도착 때 응급실 가용 ≤ 0이면 "도착 후
수용 불가"). 진실의 시간 변화는 실데이터(5분 폴링 날짜), 환자만 합성이다. 읽기만 한다: 스냅샷 JSONL, hospitals_xyz.json,
roads_data.js(전국 도로 그래프 — scipy 다익스트라로 실제 도로 시간).

정책(첫 선택 규칙):
  nearest     정보 없이 최근접. 도착해서야 만실을 안다.
  goldenlink  허브 규칙: (보이는 가용 − 우리 장부) > 0인 병원 중 도로분 + 중증 센터 가산(−5/−2) + 경증 센터 역가산(+3)
              + 이송 중 부하 페널티(10 × 이송 중/(이송 중+가용)) 최단.
  spider      거미줄: 유효 역량(등급+전문의 두께+야간−0.3×포화−창 혼잡) 대 필요 역량, μ·ν 줄 길이, τ 창 한도(양보 없음 — ②⑤ 결과).
              창 혼잡 항 켬(spider) / 끔(spider_nowin).
재투척(recast): 이동 중 새 폴에서 목표 병원의 (보이는 가용 − 장부)가 0 이하로 바뀌면 그 시점의 도로 위 노드에서 다시 고른다.
도착 거절은 모든 정책에서 그 병원 위치에서 재선택(+5분), 아무 데도 없으면 그 자리 초과 수용.
장부(우리 배정)는 공유된다(허브 구조). 우리 환자는 도착 후 30분 병상을 점유한다(진실·보이는 값 양쪽에서 뺀다).

실행: PYTHONUTF8=1 python replay_probe.py --day 2026-10-11 --n 400 --seed 1  → replay_probe.json
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import random
import sys
import time
from bisect import bisect_right
from collections import defaultdict

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "..", "info", "Hospital_inform", "info", "data", "snapshots_nationwide")
BED_OP = "getEmrrmRltmUsefulSckbdInfoInqire"
SPEED = [80, 55, 45, 35, 25]
MAX_ROUTE_MIN = 120.0
KTAS_Z = {1: 4, 2: 3, 3: 2, 4: 1, 5: 1}
KDIST = [.05, .15, .40, .30, .10]
GRADE_NAME = {4: "권역응급의료센터", 3: "지역응급의료센터", 2: "지역응급의료기관", 1: "응급실운영신고기관"}
CENTER = {4, 3}
# 허브 상수 (hub/scoring.py)
LEVEL_BONUS = {4: 5.0, 3: 2.0}
MILD_CENTER_PENALTY = 3.0
LOAD_PENALTY_MAX = 10.0
# 거미줄 상수 (make_map.py 기본값)
MU2, MU3, LAM, TAU, CAPN, DWELL = 30.0, 5.0, 5.0, 10.0, 2, 30.0
T_TRANSFER, T_RECAST, T_DECIDE = 5.0, 1.0, 3.0


def hav_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def load_graph():
    t0 = time.time()
    raw = open(os.path.join(HERE, "roads_data.js"), encoding="utf-8").read()
    r = json.loads(raw[raw.index("{"):raw.rstrip().rstrip(";").rindex("}") + 1])
    q = np.frombuffer(base64.b64decode(r["npos"]), dtype=np.int32)
    lng, lat = q[0::2] / r["scale"], q[1::2] / r["scale"]
    wn = np.frombuffer(base64.b64decode(r["wn"]), dtype=np.uint32)
    starts = np.frombuffer(base64.b64decode(r["starts"]), dtype=np.uint32)
    wcls = np.frombuffer(base64.b64decode(r["wcls"]), dtype=np.uint8)
    # 간선: 각 way 안의 연속 노드 쌍
    seg_a, seg_b, seg_w = [], [], []
    lens = np.diff(starts.astype(np.int64))
    way_of_vertex = np.repeat(np.arange(len(wcls)), lens)
    a = wn[:-1].astype(np.int64); b = wn[1:].astype(np.int64)
    same_way = way_of_vertex[:-1] == way_of_vertex[1:]
    a, b, w = a[same_way], b[same_way], way_of_vertex[:-1][same_way]
    sp = np.array(SPEED, dtype=float)[wcls[w]]
    minutes = hav_km(lat[a], lng[a], lat[b], lng[b]) / sp * 60.0
    minutes = np.maximum(minutes, 1e-6)
    n = len(lat)
    g = csr_matrix((np.concatenate([minutes, minutes]), (np.concatenate([a, b]), np.concatenate([b, a]))), shape=(n, n))
    deg = np.diff(g.indptr)
    tree = cKDTree(np.c_[lat[deg > 0], lng[deg > 0] * 0.79])
    idx_map = np.nonzero(deg > 0)[0]
    print(f"graph: nodes {n:,} edges {g.nnz // 2:,} ({time.time() - t0:.0f}s)", flush=True)
    return g, lat, lng, (tree, idx_map)


def nearest(tree_pack, la, lo):
    tree, idx_map = tree_pack
    _, i = tree.query([la, lo * 0.79])
    return int(idx_map[i])


def load_polls(day):
    polls = []
    with open(os.path.join(SNAP, f"{day}.jsonl"), encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("error") or r["operation"] != BED_OP:
                continue
            hh, mm, ss = r["ts"][11:13], r["ts"][14:16], r["ts"][17:19]
            t = int(hh) * 60 + int(mm) + int(ss) / 60
            d = {}
            for it in r["items"]:
                try:
                    d[it["hpid"]] = int(it["hvec"])
                except (KeyError, ValueError, TypeError):
                    pass
            polls.append((t, d))
    polls.sort(key=lambda x: x[0])
    return polls


class World:
    def __init__(self, hospitals, polls, lag):
        self.H = hospitals
        self.polls = polls
        self.ptimes = [p[0] for p in polls]
        self.lag = lag
        self.ledger = []          # dict(h, tArr, tEnd, k)
        self.by_h = defaultdict(list)

    def raw(self, hpid, t):
        i = bisect_right(self.ptimes, t) - 1
        if i < 0:
            i = 0
        return self.polls[i][1].get(hpid)

    def truth_free(self, hi, t):
        v = self.raw(self.H[hi]["hpid"], t)
        if v is None:
            return None
        return v - self.ours_dwelling(hi, t)

    def visible_raw(self, hi, t):
        return self.raw(self.H[hi]["hpid"], t - self.lag)

    def ours_dwelling(self, hi, t):
        return sum(1 for e in self.by_h[hi] if e["tArr"] <= t < e["tEnd"])

    def inflight(self, hi, t):
        return sum(1 for e in self.by_h[hi] if e["tArr"] > t)

    def win_count(self, hi, t_arr):
        return sum(1 for e in self.by_h[hi] if abs(e["tArr"] - t_arr) <= TAU)

    def visible_free(self, hi, t):
        v = self.visible_raw(hi, t)
        if v is None:
            return None
        return v - self.ours_dwelling(hi, t) - self.inflight(hi, t)

    def add(self, hi, t_arr, k, pid):
        e = dict(h=hi, tArr=t_arr, tEnd=t_arr + DWELL, k=k, pid=pid)
        self.ledger.append(e); self.by_h[hi].append(e)
        return e

    def remove(self, e):
        self.ledger.remove(e); self.by_h[e["h"]].remove(e)


def thick(em):
    return -0.4 if em <= 1 else -0.2 if em <= 3 else 0.2 if em >= 8 else 0.0


def choose(policy, w: World, row, t, k, exclude, wload=True):
    """row: 현재 위치 → 병원 index 별 도로분(inf = 닿지 않음). 반환 (hi, len, road, forced)"""
    H = w.H
    cands = [i for i in range(len(H)) if i not in exclude and np.isfinite(row[i])]
    if not cands:
        return None
    if policy == "nearest":
        i = min(cands, key=lambda i: row[i])
        return i, row[i], row[i], False
    if policy == "goldenlink":
        best = None
        for i in cands:
            free = w.visible_free(i, t)
            if free is None or free <= 0:
                continue
            g = H[i]["g"]
            cost = row[i]
            if k <= 2 and g in LEVEL_BONUS:
                cost -= LEVEL_BONUS[g]
            if k >= 4 and g in CENTER:
                cost += MILD_CENTER_PENALTY
            infl = w.inflight(i, t)
            cost += LOAD_PENALTY_MAX * infl / max(1, infl + free)
            if best is None or cost < best[1]:
                best = (i, cost, row[i], False)
        if best is None:
            i = min(cands, key=lambda i: row[i])
            return i, row[i], row[i], True
        return best
    # spider
    need = KTAS_Z[k]
    hour = (t / 60) % 24
    night = hour >= 22 or hour < 6
    infl_severe = sum(1 for e in w.ledger if e["tArr"] > t and e["k"] <= 2)
    mu0 = MU2 if k <= 2 else MU3 if k == 3 else -LAM
    mu = mu0 * max(0.0, 1 - infl_severe / 10) if k <= 3 else mu0
    nu = 30 if k <= 2 else 15 if k == 3 else 5
    scored = []
    for i in cands:
        h = H[i]
        vis = w.visible_free(i, t)
        if vis is not None and vis <= 0:
            continue   # 보이는 가용 없음 = full()
        em = h.get("em") or 0
        g = h["g"]
        nt = (-0.6 if (g <= 2 and em <= 2) else -0.25 if em <= 3 else -0.1) if night else 0.0
        raw = w.visible_raw(i, t)
        occ = max(0.0, min(1.0, 1 - raw / h["er_cap"])) if (h.get("er_cap") and raw is not None) else 0.5
        t_arr = t + row[i]
        if policy == "spider_v2":
            # v2: 부하는 z가 아니라 길이에 분으로 — z에 넣으면 μ의 부호(경증은 음수)에 곱해져 붐비는 병원이 경증에게 더 짧아진다
            z = g + thick(em) + nt
            gap = z - need
            if gap < -0.75:
                continue
            length = row[i] - mu * (min(gap, 1) + 0.25 * max(0, gap - 1)) if gap >= 0 else row[i] + nu * (-gap)
            infl = w.inflight(i, t)
            length += LOAD_PENALTY_MAX * infl / max(1, infl + (vis if vis is not None else CAPN))   # 허브 부하 페널티
            length += 5.0 * occ                                                                     # 허브 포화 페널티(최대 5분)
            scored.append((length, i))
            continue
        win = w.win_count(i, t_arr) if wload else 0
        z = g + thick(em) + nt - 0.3 * occ - 0.25 * min(2, win / CAPN)
        gap = z - need
        if gap < -0.75:
            continue
        length = row[i] - mu * (min(gap, 1) + 0.25 * max(0, gap - 1)) if gap >= 0 else row[i] + nu * (-gap)
        scored.append((length, i))
    scored.sort()
    for length, i in scored:
        t_arr = t + row[i]
        if w.win_count(i, t_arr) >= CAPN:
            continue   # 창 한도 — 양보 없이 다음 줄로
        return i, length, row[i], False
    if scored:
        length, i = scored[0]
        return i, length, row[i], True
    i = min(cands, key=lambda i: row[i])
    return i, row[i], row[i], True


def run(policy, recast, patients, hospitals, polls, lag, G, lat, lng, tree, cache, wload=True):
    w = World(hospitals, polls, lag)
    hnodes = np.array([h["node"] for h in hospitals])
    stats = dict(n=0, refusals=0, recasts=0, overflow=0, unreachable=0)
    out = []

    def table(node):
        if node not in cache:
            d, pred = dijkstra(G, indices=node, limit=MAX_ROUTE_MIN, return_predecessors=True)
            cache[node] = (d[hnodes].copy(), pred)
        return cache[node]

    def node_at(src, pred, target_node, elapsed, d_total):
        """src→target 경로 위에서 출발 후 elapsed 분 지점의 노드 (경로를 되짚는다)"""
        path = []
        v = target_node
        while v >= 0 and v != src and len(path) < 200000:
            path.append(v); v = pred[v]
        path.append(src); path.reverse()
        # 누적 거리: 노드별 d는 없으니 간선 가중치로 다시 쌓는다
        acc = 0.0
        for a, b in zip(path[:-1], path[1:]):
            step = G[a, b]
            if acc + step >= elapsed:
                return b
            acc += step
        return target_node

    for p in patients:
        stats["n"] += 1
        t = p["t0"] + T_DECIDE
        src = p["node"]
        row, pred = table(src)
        exclude = set()
        pos_node = src
        pick = choose(policy, w, row, t, p["k"], exclude, wload)
        if pick is None:
            stats["unreachable"] += 1
            continue
        hi, length, road, forced = pick
        if forced:
            stats["overflow"] += 1
        t_arr = t + road
        entry = w.add(hi, t_arr, p["k"], p["id"])
        hops = 0
        while True:
            # 이동 중 재투척: 다음 폴마다 목표의 보이는 가용이 바뀌었나
            moved = False
            if recast and not forced:
                i0 = bisect_right(w.ptimes, t)
                for pt in w.ptimes[i0:]:
                    if pt >= t_arr:
                        break
                    if (w.visible_free(hi, pt) or 0) + 1 <= 0:   # 내 예약 1 포함해 0 이하
                        # 현재 노드에서 다시 고른다
                        cur = node_at(pos_node, pred, hospitals[hi]["node"], pt - t, road)
                        w.remove(entry)
                        exclude.add(hi)
                        row2, pred2 = table(cur)
                        t2 = pt + T_RECAST
                        pick = choose(policy, w, row2, t2, p["k"], exclude, wload)
                        stats["recasts"] += 1
                        if pick is None:
                            entry = w.add(hi, t_arr, p["k"], p["id"]); exclude.discard(hi)
                            break
                        hi, length, road, forced = pick
                        if forced:
                            stats["overflow"] += 1
                        pos_node, row, pred, t = cur, row2, pred2, t2
                        t_arr = t + road
                        entry = w.add(hi, t_arr, p["k"], p["id"])
                        moved = True
                        break
            if moved:
                continue
            # 도착 채점
            tf = w.truth_free(hi, t_arr)
            if forced or tf is None or tf > 0:
                break
            # 도착 후 수용 불가 → 그 병원 위치에서 재선택
            stats["refusals"] += 1
            w.remove(entry)
            exclude.add(hi)
            hnode = hospitals[hi]["node"]
            row, pred = table(hnode)
            pos_node = hnode
            t = t_arr + T_TRANSFER
            pick = choose(policy, w, row, t, p["k"], exclude, wload)
            hops += 1
            if pick is None or hops > 5:
                stats["overflow"] += 1
                entry = w.add(hi, t_arr, p["k"], p["id"]); forced = True
                break
            hi, length, road, forced = pick
            if forced:
                stats["overflow"] += 1
            t_arr = t + road
            entry = w.add(hi, t_arr, p["k"], p["id"])
        out.append(dict(id=p["id"], k=p["k"], t0=p["t0"], tArr=t_arr, h=hi, g=hospitals[hi]["g"], hops=hops))
    dur = sorted(o["tArr"] - o["t0"] for o in out)
    pct = lambda q: dur[min(len(dur) - 1, int(q * (len(dur) - 1)))] if dur else None
    res = dict(policy=policy + ("" if (wload or policy != "spider") else "_nowin"), recast=recast, lag=lag, **stats,
               meanMin=round(sum(dur) / len(dur), 2) if dur else None, medianMin=round(pct(0.5), 2), p90Min=round(pct(0.9), 2))
    for grp, ks in (("k12", (1, 2)), ("k3", (3,)), ("k45", (4, 5))):
        g = [o for o in out if o["k"] in ks]
        res[f"{grp}_center"] = round(sum(1 for o in g if o["g"] in CENTER) / len(g), 3) if g else None
        res[f"{grp}_medianMin"] = round(sorted(o["tArr"] - o["t0"] for o in g)[len(g) // 2], 1) if g else None
    return res


def make_patients(n, seed, hospitals, tree, lat, lng, hour_w, t_min, t_max, region="korea"):
    rng = random.Random(seed)
    if region == "seoul":
        hospitals = [h for h in hospitals if h["hpid"].startswith("A11")]
    hours = list(range(24))
    pats = []
    while len(pats) < n:
        hr = rng.choices(hours, weights=[hour_w[h] for h in hours])[0]
        t0 = hr * 60 + rng.random() * 60
        if not (t_min <= t0 <= t_max - 150):
            continue
        h = rng.choice(hospitals)
        r = math.sqrt(rng.random()) * (0.04 if region == "seoul" else 0.09); a = rng.random() * 2 * math.pi
        la, lo = h["lat"] + r * math.sin(a), h["lng"] + r * math.cos(a) * 1.25
        k = rng.choices([1, 2, 3, 4, 5], weights=KDIST)[0]
        pats.append(dict(id=len(pats) + 1, t0=t0, k=k, lat=la, lng=lo, node=nearest(tree, la, lo)))
    pats.sort(key=lambda p: p["t0"])
    return pats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="2026-10-11")
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--lags", default="0,5,15")
    ap.add_argument("--region", default="korea", choices=["korea", "seoul"])
    ap.add_argument("--out", default="replay_probe.json")
    args = ap.parse_args()
    G, lat, lng, tree = load_graph()
    H = [h for h in json.load(open(os.path.join(HERE, "hospitals_xyz.json"), encoding="utf-8")) if h["hasBeds"]]
    for h in H:
        h["node"] = nearest(tree, h["lat"], h["lng"])
    polls = load_polls(args.day)
    print(f"day {args.day}: polls {len(polls)} ({polls[0][0]/60:.1f}h~{polls[-1][0]/60:.1f}h), hospitals {len(H)}", flush=True)
    hour_w = json.load(open(os.path.join(HERE, "collision_probe.json"), encoding="utf-8"))["events_by_hour"]
    hour_w = {int(k): v for k, v in hour_w.items()}
    pats = make_patients(args.n, args.seed, H, tree, lat, lng, hour_w, polls[0][0], polls[-1][0], args.region)
    cache = {}
    results = []
    hdr = f"{'lag':>4}{'policy':<16}{'recast':>7}{'평균':>7}{'중앙':>7}{'p90':>7}{'거절':>6}{'재투척':>7}{'초과':>6}{'K12센터':>8}{'K45센터':>8}{'K12중앙':>8}"
    print(hdr, flush=True)
    for lag in [float(x) for x in args.lags.split(",")]:
        for policy, wload in (("nearest", True), ("goldenlink", True), ("spider", True), ("spider", False), ("spider_v2", True)):
            for recast in ((False,) if policy == "nearest" else (False, True)):
                t0 = time.time()
                r = run(policy, recast, pats, H, polls, lag, G, lat, lng, tree, cache, wload)
                r["sec"] = round(time.time() - t0)
                results.append(r)
                print(f"{lag:>4.0f}{r['policy']:<16}{str(recast):>7}{r['meanMin']:>7.1f}{r['medianMin']:>7.1f}{r['p90Min']:>7.1f}"
                      f"{r['refusals']:>6}{r['recasts']:>7}{r['overflow']:>6}{(r['k12_center'] or 0)*100:>7.0f}%{(r['k45_center'] or 0)*100:>7.0f}%"
                      f"{r['k12_medianMin'] or 0:>8.1f}  ({r['sec']}s, cache {len(cache)})", flush=True)
    json.dump(dict(day=args.day, n=args.n, seed=args.seed, region=args.region, polls=len(polls), results=results),
              open(os.path.join(HERE, args.out), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
