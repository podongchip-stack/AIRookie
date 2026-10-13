"""검증 ⑥: 결정자 여럿 + 순간 축 거절 되먹임 — E-Gen 스냅샷 재생 (replay_probe.py의 세계·정책을 그대로 쓴다).

GPU 쪽(Dynamo 라우터 시뮬)에서 값을 한 규칙은 "충돌하면 다시 보내고, 실제 상태를 결정자의 뷰에 써 넣는다"였다.
replay_probe는 결정자가 허브 하나(장부 공유)이고 거절을 당한 환자만 다시 고른다. 여기서 두 가지를 더한다.

결정자 N: 환자마다 결정자(허브·상황실)를 무작위로 붙인다. 자기 결정자의 배정은 즉시, 다른 결정자의 배정(예약·취소)은
  sync 분 뒤에 보인다(sync=inf면 끝내 안 보임 = 서로 모르는 독립 시스템). 무작위 배정이라 결정자끼리 겹침의 최악 쪽이다.
거절 되먹임(순간 축만 — BEDS_FULL·OR_OCCUPIED·STAFF_BUSY): 도착 거절이 나면 그 병원을 "만실로 알려짐"으로 막는다.
  local  = 거절당한 환자의 결정자만 안다     shared = 다른 결정자도 FB_DELAY 분 뒤에 안다
  ttl poll = 그 뒤의 새 스냅샷이 보일 때까지(Dynamo의 다음 발행이 덮어쓰는 것과 같은 꼴)    ttl 30 = 30분 고정
  막힌 병원은 첫 선택에서 빠지고, 그 병원으로 이동 중인 구급차는 다음 폴 점검에서 재투척한다.
구조·주기·환자 축 거절은 진실 데이터가 없어 여기서 재지 않는다(거절 로그가 쌓이면).

replay_probe와 다른 점: 환자를 한 명씩 끝까지 처리하지 않고 시각 순 이벤트(결정 → 폴 점검 → 도착)로 진행한다. 그래야 뒤에
출발한 환자의 거절이 앞서 이동 중인 구급차에 닿는다. 그래서 N=1·되먹임 끔 행도 replay_probe 수치와 조금 다르다.
재투척은 모든 팔에서 켠다(①의 결론). 채점은 replay_probe와 같다(도착 때 E-Gen 가용 − 우리 점유 ≤ 0이면 거절).

실행: PYTHONUTF8=1 python feedback_probe.py --region seoul --n 800 --seeds 1,2,3 → feedback_seoul_800.json
"""
from __future__ import annotations

import argparse
import heapq
import json
import os
import random
import time
from bisect import bisect_right
from collections import defaultdict

import numpy as np
from scipy.sparse.csgraph import dijkstra

import replay_probe as rp

INF = float("inf")
FB_DELAY = 2.0   # shared 되먹임이 다른 결정자에 닿는 분

# (이름, 결정자 수, 배정 sync 분, 되먹임, ttl)
CONFIGS = [
    ("N1", 1, 0.0, "off", None),
    ("N1+fb_poll", 1, 0.0, "local", "poll"),
    ("N1+fb_30", 1, 0.0, "local", 30.0),
    ("N4_sync2", 4, 2.0, "off", None),
    ("N4_sync2+fb_poll", 4, 2.0, "shared", "poll"),
    ("N4_sync2+fb_30", 4, 2.0, "shared", 30.0),
    ("N4_nosync", 4, INF, "off", None),
    ("N4_nosync+fb_local30", 4, INF, "local", 30.0),
    ("N4_nosync+fb_shared30", 4, INF, "shared", 30.0),
]


class View(rp.World):
    """진실(E-Gen + 우리 점유)은 World 그대로, 결정자 self.me의 뷰만 덮어쓴다."""

    def __init__(self, hospitals, polls, lag, sync, fb, ttl):
        super().__init__(hospitals, polls, lag)
        self.sync, self.fb, self.ttl = sync, fb, ttl
        self.gone = defaultdict(list)     # 취소된 예약 — 다른 결정자에겐 tRem+sync까지 남아 보인다
        self.blocks = defaultdict(list)   # hi -> [(거절 시각, 결정자)]
        self.me = 0
        self.now = 0.0

    def add(self, hi, t_arr, k, pid):
        e = super().add(hi, t_arr, k, pid)
        e["tc"], e["own"] = self.now, self.me
        return e

    def remove(self, e):
        super().remove(e)
        e["tRem"] = self.now
        self.gone[e["h"]].append(e)

    def _seen(self, e, t):
        d = 0.0 if e["own"] == self.me else self.sync
        return e["tc"] + d <= t < e.get("tRem", INF) + d

    def _view(self, hi, t):
        return [e for e in self.by_h[hi] + self.gone[hi] if self._seen(e, t)]

    def _block_end(self, tb):
        if self.ttl == "poll":
            i = bisect_right(self.ptimes, tb)
            return (self.ptimes[i] if i < len(self.ptimes) else INF) + self.lag
        return tb + self.ttl

    def blocked(self, hi, t):
        for tb, own in self.blocks[hi]:
            seen = tb if own == self.me else tb + FB_DELAY if self.fb == "shared" else INF
            if seen <= t < self._block_end(tb):
                return True
        return False

    def inflight(self, hi, t):
        return sum(1 for e in self._view(hi, t) if e["tArr"] > t)

    def win_count(self, hi, t_arr):
        return sum(1 for e in self._view(hi, self.now) if abs(e["tArr"] - t_arr) <= rp.TAU)

    def visible_free(self, hi, t):
        v = self.visible_raw(hi, t)
        if v is None:
            return None
        if self.blocked(hi, t):
            return -1   # 만실로 알려짐 — 이동 중 내 예약을 넣어도 0 이하라 재투척이 걸린다
        vw = self._view(hi, t)
        return v - sum(1 for e in vw if e["tArr"] <= t < e["tEnd"]) - sum(1 for e in vw if e["tArr"] > t)


def run(policy, cfg, patients, hospitals, polls, lag, G, cache):
    name, n_dec, sync, fb, ttl = cfg
    w = View(hospitals, polls, lag, sync, fb, ttl)
    hnodes = np.array([h["node"] for h in hospitals])
    stats = dict(n=0, refusals=0, ref_k12=0, ref_k12_center=0, recasts=0, fb_recasts=0, overflow=0, unreachable=0)
    out = []

    def table(node):
        if node not in cache:
            d, pred = dijkstra(G, indices=node, limit=rp.MAX_ROUTE_MIN, return_predecessors=True)
            cache[node] = (d[hnodes].copy(), pred)
        return cache[node]

    def node_at(src, pred, target_node, elapsed):
        path = []
        v = target_node
        while v >= 0 and v != src and len(path) < 200000:
            path.append(v); v = pred[v]
        path.append(src); path.reverse()
        acc = 0.0
        for a, b in zip(path[:-1], path[1:]):
            step = G[a, b]
            if acc + step >= elapsed:
                return b
            acc += step
        return target_node

    ev, seq = [], 0

    def push(t, kind, s):
        nonlocal seq
        heapq.heappush(ev, (t, seq, kind, s)); seq += 1

    def pick(s, t, node):
        """s의 결정자로 node에서 고르고 예약한다. 못 고르면 False."""
        w.me, w.now = s["d"], t
        row, pred = table(node)
        p = rp.choose(policy, w, row, t, s["k"], s["exclude"])
        if p is None:
            return False
        hi, _, road, forced = p
        if forced:
            stats["overflow"] += 1
        s.update(hi=hi, road=road, forced=forced, t=t, pos=node, pred=pred, tArr=t + road)
        s["entry"] = w.add(hi, t + road, s["k"], s["id"])
        return True

    def next_step(s):
        i = bisect_right(w.ptimes, s["t"])
        if not s["forced"] and i < len(w.ptimes) and w.ptimes[i] < s["tArr"]:
            push(w.ptimes[i], "check", s)
        else:
            push(s["tArr"], "arrive", s)

    def finish(s):
        out.append(dict(id=s["id"], k=s["k"], t0=s["t0"], tArr=s["tArr"], h=s["hi"], g=hospitals[s["hi"]]["g"]))

    for p in patients:
        push(p["t0"] + rp.T_DECIDE, "decide",
             dict(id=p["id"], k=p["k"], t0=p["t0"], node=p["node"], d=p["d"], exclude=set(), hops=0))

    while ev:
        t, _, kind, s = heapq.heappop(ev)
        w.me, w.now = s["d"], t
        if kind == "decide":
            stats["n"] += 1
            if not pick(s, t, s["node"]):
                stats["unreachable"] += 1
                continue
            next_step(s)
        elif kind == "check":
            hi = s["hi"]
            if (w.visible_free(hi, t) or 0) + 1 > 0:
                i = bisect_right(w.ptimes, t)
                if i < len(w.ptimes) and w.ptimes[i] < s["tArr"]:
                    push(w.ptimes[i], "check", s)
                else:
                    push(s["tArr"], "arrive", s)
                continue
            stats["recasts"] += 1
            if w.blocked(hi, t):
                stats["fb_recasts"] += 1
            cur = node_at(s["pos"], s["pred"], hospitals[hi]["node"], t - s["t"])
            w.remove(s["entry"])
            s["exclude"].add(hi)
            old = dict(hi=s["hi"], road=s["road"], forced=s["forced"], t=s["t"], pos=s["pos"], pred=s["pred"], tArr=s["tArr"])
            if not pick(s, t + rp.T_RECAST, cur):
                # 갈 곳이 없으면 원래 목표로 계속 간다
                s.update(old)
                s["exclude"].discard(hi)
                w.now = t
                s["entry"] = w.add(hi, s["tArr"], s["k"], s["id"])
                push(s["tArr"], "arrive", s)
                continue
            next_step(s)
        else:   # arrive
            hi = s["hi"]
            tf = w.truth_free(hi, t)
            if s["forced"] or tf is None or tf > 0:
                finish(s)
                continue
            stats["refusals"] += 1
            if s["k"] <= 2:
                stats["ref_k12"] += 1
                stats["ref_k12_center"] += hospitals[hi]["g"] in rp.CENTER
            w.remove(s["entry"])
            if fb != "off":
                w.blocks[hi].append((t, s["d"]))
            s["exclude"].add(hi)
            s["hops"] += 1
            if s["hops"] > 5 or not pick(s, t + rp.T_TRANSFER, hospitals[hi]["node"]):
                stats["overflow"] += 1
                w.now = t
                s.update(forced=True, tArr=t)
                s["entry"] = w.add(hi, t, s["k"], s["id"])
                finish(s)
                continue
            next_step(s)

    dur = sorted(o["tArr"] - o["t0"] for o in out)
    pct = lambda q: dur[min(len(dur) - 1, int(q * (len(dur) - 1)))]
    res = dict(config=name, policy=policy, lag=lag, **stats, meanMin=round(sum(dur) / len(dur), 2),
               medianMin=round(pct(0.5), 2), p90Min=round(pct(0.9), 2))
    for grp, ks in (("k12", (1, 2)), ("k3", (3,)), ("k45", (4, 5))):
        g = [o for o in out if o["k"] in ks]
        d = sorted(o["tArr"] - o["t0"] for o in g)
        res[f"{grp}_n"] = len(g)
        res[f"{grp}_center"] = round(sum(1 for o in g if o["g"] in rp.CENTER) / len(g), 3) if g else None
        res[f"{grp}_meanMin"] = round(sum(d) / len(d), 2) if d else None
        res[f"{grp}_p90Min"] = round(d[min(len(d) - 1, int(0.9 * (len(d) - 1)))], 2) if d else None
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="2026-10-11")
    ap.add_argument("--n", type=int, default=800)
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--lags", default="0,15")
    ap.add_argument("--region", default="seoul", choices=["korea", "seoul"])
    ap.add_argument("--policies", default="goldenlink,spider_v2")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    G, lat, lng, tree = rp.load_graph()
    H = [h for h in json.load(open(os.path.join(rp.HERE, "hospitals_xyz.json"), encoding="utf-8")) if h["hasBeds"]]
    for h in H:
        h["node"] = rp.nearest(tree, h["lat"], h["lng"])
    polls = rp.load_polls(args.day)
    hour_w = json.load(open(os.path.join(rp.HERE, "collision_probe.json"), encoding="utf-8"))["events_by_hour"]
    hour_w = {int(k): v for k, v in hour_w.items()}
    results = []
    print(f"{'seed':>4}{'lag':>4} {'policy':<11}{'config':<24}{'거절':>5}{'재투척':>7}{'fb재투척':>8}{'평균':>7}{'p90':>7}{'K12센터':>8}", flush=True)
    for seed in [int(x) for x in args.seeds.split(",")]:
        pats = rp.make_patients(args.n, seed, H, tree, lat, lng, hour_w, polls[0][0], polls[-1][0], args.region)
        rng = random.Random(seed + 1000)
        dec = [rng.random() for _ in pats]
        cache = {}
        for lag in [float(x) for x in args.lags.split(",")]:
            for policy in args.policies.split(","):
                for cfg in CONFIGS:
                    for p, u in zip(pats, dec):
                        p["d"] = int(u * cfg[1])
                    t0 = time.time()
                    r = run(policy, cfg, pats, H, polls, lag, G, cache)
                    r["seed"], r["sec"] = seed, round(time.time() - t0, 1)
                    results.append(r)
                    print(f"{seed:>4}{lag:>4.0f} {policy:<11}{cfg[0]:<24}{r['refusals']:>5}{r['recasts']:>7}{r['fb_recasts']:>8}"
                          f"{r['meanMin']:>7.2f}{r['p90Min']:>7.2f}{(r['k12_center'] or 0) * 100:>7.0f}%  ({r['sec']}s)", flush=True)
    out = args.out or f"feedback_{args.region}_{args.n}.json"
    json.dump(dict(day=args.day, n=args.n, region=args.region, fb_delay=FB_DELAY, results=results),
              open(os.path.join(rp.HERE, out), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
