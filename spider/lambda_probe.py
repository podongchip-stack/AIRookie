"""검증 ④′: 상위 역량 아껴 두기 — 경증을 센터에서 떼어 내면 뒤에 오는 중증이 센터에 들어가나 (스냅샷 재생).

④(μ 교차점)는 "상위 병원이 더 잘 치료하나"라 결과 데이터 없이는 못 잰다. 질문을 바꾼다: 거미줄 배치 층의 다른 쪽,
경증의 센터 회피(λ)가 센터 자리를 비워 두어 KTAS 1·2의 센터 도착 거절·소요 시간을 줄이는가, 대가로 경증은 몇 분 잃는가.
GPU 쪽 Dynamo 시뮬에서 역량 잉여 패널티가 등급 속도가 같을 때 이긴 것과 같은 구조의 실험이다.

세계·채점은 feedback_probe(시각 순 이벤트, 재투척 켬)와 같고, 결정자 1개. 되먹임 끔 / 30분 막기 두 가지.
  spider_v2   λ = KTAS 4·5의 μ(−λ분/레벨, 센터 쪽 줄이 길어짐) ∈ LAMS
  goldenlink  경증 센터 역가산(MILD_CENTER_PENALTY, 허브 기본 3분) ∈ MILD_PENS — 허브 규칙의 같은 손잡이

실행: PYTHONUTF8=1 python lambda_probe.py --region seoul --n 800 --seeds 1,2,3 → lambda_seoul_800.json
"""
from __future__ import annotations

import argparse
import json
import os
import time

import feedback_probe as fp
import replay_probe as rp

LAMS = [0.0, 5.0, 10.0, 20.0]
MILD_PENS = [0.0, 3.0, 10.0, 20.0]
CONFIGS = [c for c in fp.CONFIGS if c[0] in ("N1", "N1+fb_30")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="2026-10-11")
    ap.add_argument("--n", type=int, default=800)
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--lag", type=float, default=15.0)
    ap.add_argument("--region", default="seoul", choices=["korea", "seoul"])
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
    print(f"{'seed':>4} {'policy':<11}{'λ':>5} {'config':<10}{'거절':>5}{'K12거절':>8}{'K12평균':>8}{'K12센터':>8}"
          f"{'K45평균':>8}{'K45센터':>8}{'평균':>7}", flush=True)
    for seed in [int(x) for x in args.seeds.split(",")]:
        pats = rp.make_patients(args.n, seed, H, tree, lat, lng, hour_w, polls[0][0], polls[-1][0], args.region)
        for p in pats:
            p["d"] = 0
        cache = {}
        for policy, knob, vals in (("spider_v2", "LAM", LAMS), ("goldenlink", "MILD_CENTER_PENALTY", MILD_PENS)):
            for v in vals:
                setattr(rp, knob, v)
                for cfg in CONFIGS:
                    t0 = time.time()
                    r = fp.run(policy, cfg, pats, H, polls, args.lag, G, cache)
                    r.update(seed=seed, lam=v, sec=round(time.time() - t0, 1))
                    results.append(r)
                    print(f"{seed:>4} {policy:<11}{v:>5.0f} {cfg[0]:<10}{r['refusals']:>5}{r['ref_k12']:>8}{r['k12_meanMin']:>8.2f}"
                          f"{r['k12_center'] * 100:>7.0f}%{r['k45_meanMin']:>8.2f}{r['k45_center'] * 100:>7.0f}%{r['meanMin']:>7.2f}",
                          flush=True)
        rp.LAM, rp.MILD_CENTER_PENALTY = 5.0, 3.0
    out = args.out or f"lambda_{args.region}_{args.n}.json"
    json.dump(dict(day=args.day, n=args.n, region=args.region, lag=args.lag, results=results),
              open(os.path.join(rp.HERE, out), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
