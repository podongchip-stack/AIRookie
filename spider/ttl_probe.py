"""적용 조건 4 (2): 되먹임 막는 시간 스윕 — feedback_probe 세계, 결정자 1개, lag 15, 서울, 시드 1~3.

full_duration_probe의 잔여 만실 곡선이 정한 후보(30·60·90·120·240분)를 재생에서 비교한다. 거절 건수는 채점과 같은 신호라
막는 시간이 길수록 단조로 준다(순환) — 판단은 시간 지표(평균·중증 p90·경증 평균)로 한다.

실행: PYTHONUTF8=1 python ttl_probe.py 2026-09-28 1600 → ttl_probe_2026-09-28_1600.json
"""
import json
import os
import sys

import feedback_probe as fp, replay_probe as rp
day, n = sys.argv[1], int(sys.argv[2])
G, lat, lng, tree = rp.load_graph()
H = [h for h in json.load(open(os.path.join(rp.HERE, "hospitals_xyz.json"), encoding="utf-8")) if h["hasBeds"]]
for h in H: h["node"] = rp.nearest(tree, h["lat"], h["lng"])
polls = rp.load_polls(day)
hw = {int(k): v for k, v in json.load(open(os.path.join(rp.HERE, "collision_probe.json"), encoding="utf-8"))["events_by_hour"].items()}
cfgs = [("off", 1, 0.0, "off", None)] + [(f"ttl{t}", 1, 0.0, "local", float(t)) for t in (30, 60, 90, 120, 240)]
agg = {}
for seed in (1, 2, 3):
    pats = rp.make_patients(n, seed, H, tree, lat, lng, hw, polls[0][0], polls[-1][0], "seoul")
    for p in pats: p["d"] = 0
    cache = {}
    for pol in ("goldenlink", "spider_v2"):
        for c in cfgs:
            r = fp.run(pol, c, pats, H, polls, 15.0, G, cache)
            agg.setdefault((pol, c[0]), []).append(r)
json.dump([dict(policy=p, config=c, results=rs) for (p, c), rs in agg.items()],
          open(os.path.join(rp.HERE, f"ttl_probe_{day}_{n}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for (pol, name), rs in agg.items():
    m = lambda k: sum(r[k] for r in rs) / len(rs)
    print(f"{day} {n} {pol:<11}{name:<7} 거절 {m('refusals'):6.1f}  중증거절 {m('ref_k12'):5.1f}  평균 {m('meanMin'):5.2f}  중증p90 {m('k12_p90Min'):6.2f}  경증평균 {m('k45_meanMin'):5.2f}")
