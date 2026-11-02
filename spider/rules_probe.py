"""검증 ⑧: 후보 규칙 3종을 가상 세계에서 비교한다 — ① 동시 최적 배정 ② 기대 부하(동시 요청) ③ 병상 희소성 연동(센터 보존).

`sim_spider.py`의 세계(일산 장면 실측 스냅샷 병원·병상, 외부 유입 포아송, 정보 지연)를 그대로 쓰되 `sim/`·기존 spider 파일은
수정하지 않는다(import만). 기존 세계에 **동시 요청**을 더한다 — 구급차 여럿이 거의 같은 시각에 병원을 고르는데, hub의
병상 장부에는 **확정된 것만** 올라가고(확정 지연 D분) 서로의 선택은 보이지 않는다(평소 hub: 이송 확정 BedHold만 부하로 센다).
그래서 마지막 병상을 둘이 고르는 일이 생기고, 도착 거절이 난다. 거절은 가상 로그로 남긴다(전부 `demo: true`).

팔(arm)
  indep      지금 hub: 확정된 장부만 보고 각자 고른다. 비용 = 이동 + 중증도 보정 + 이송 중 부하(10×n/(n+가용)).
  greedy     ① hub가 같은 시각 요청을 한꺼번에 받아 KTAS 순으로 하나씩 배정하고 바로 장부에 올린다(plan_mci와 같은 그리디).
  hung       ① 같은 묶음을 헝가리안(전체 최적 배정)으로 푼다 — 비용에 중증도 가중(중증 3·응급 2·경증 1).
  rand2      ② 비용 상위 2곳 중 무작위(GPU 벤치마크에서 충돌을 줄이던 방식).
  soft_plain ② 아직 확정 전인 다른 사건의 후보 상위 3곳에 1/3씩 부하로 센다.
  soft_full  ② 위에서 자기와 같거나 더 위급한 사건만, 도착 시각이 τ(10분) 안에 겹칠 때만 센다(KTAS·이동 속도 반영).
  const      ③ 지금 규칙: 경증이 센터에 상수 +3분.
  scar_ρ     ③ 센터 잔여 병상이 정원×ρ 이하일 때만, 모자랄수록 커지는 페널티(최대 15분)를 경증에게. 상수 가산은 없앤다.

숫자(확정 지연 2분, 묶음 1분, 중증 가중, 페널티 15분)는 전부 가정이다 — 실측이 아니라 메커니즘을 보는 실험이다.
실행: PYTHONUTF8=1 python rules_probe.py [--seeds 20]  (scipy 필요: conda rookie_info)
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import random
import sys
from dataclasses import dataclass, replace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "sim"))   # sim/engine.py가 spider/engine/ 패키지보다 먼저 잡혀야 한다
from data_load import SCENES, Hospital, build_world, haversine_km  # noqa: E402
from engine import SimParams, _assign_severities, percentile, severity_adjust_min  # noqa: E402
from sim_spider import EXO_DWELL_MIN, EXO_RATE_PER_MIN, PRIORITY  # noqa: E402

CENTERS = {"권역응급의료센터", "지역응급의료센터"}
CONFIRM_DELAY_MIN = 2.0     # 병원 승인 + 대원 확정까지 — 이 동안 다른 사건에게는 안 보인다
BUCKET_MIN = 1.0            # 같은 묶음으로 보는 시각 폭
TAU_MIN = 10.0              # 기대 부하에서 도착이 겹친다고 보는 폭
TOP_M = 3                   # 기대 부하: 후보 상위 m곳에 1/m씩
LOAD_MAX_MIN = 10.0         # hub 이송 중 부하 페널티 상한
SCAR_PENALTY_MIN = 15.0     # 병상 희소성 페널티 최대
SEV_WEIGHT = {"immediate": 3.0, "urgent": 2.0, "delayed": 1.0}
OVERFLOW_COST_MIN = 40.0


@dataclass
class Policy:
    name: str
    mode: str = "indep"          # indep | greedy | hung
    soft: str | None = None      # None | plain | full
    rand2: bool = False
    scar_rho: float | None = None


def simulate(hospitals: list[Hospital], params: SimParams, seed: int, scene: dict, flow: float, lag: float, pol: Policy) -> dict:
    rng = random.Random(seed)
    n = len(hospitals)
    scene_pos = (scene["lat"], scene["lng"])
    cap0 = [h.capacity for h in hospitals]
    admitted = [0] * n
    exo = [0] * n
    exo_vis = [0] * n
    committed: list[set] = [set() for _ in range(n)]
    pending: dict[int, dict] = {}          # 확정 전 사건: {sev, t, pos, top}
    route: dict[int, tuple[int, float]] = {}   # patient -> (hospital, arrival t)
    skip: dict[int, set] = {}
    forced: set[int] = set()
    results: dict[int, dict] = {}
    sev_of: dict[int, str] = {}
    amb_of: dict[int, int] = {}
    refusal_log: list[dict] = []
    stats = dict(refusals=0, refusals_severe=0, refusals_severe_center=0, refusals_ours=0, refusals_exo=0, overflow=0)

    severities = _assign_severities(params.n_patients, params.severity_mix, rng)
    rng.shuffle(severities)     # 현장 트리아지 없이 도착 순 — 중증이 늦게도 나온다

    ev: list = []
    seq = 0

    def push(t, kind, who, extra=None):
        nonlocal seq
        seq += 1
        heapq.heappush(ev, (t, seq, kind, who, extra))

    def travel(pos, i):
        return haversine_km(pos[0], pos[1], hospitals[i].lat, hospitals[i].lng) * params.road_factor / params.speed_kmh * 60.0

    def vfree(i):
        return cap0[i] - admitted[i] - exo_vis[i] - len(committed[i])

    def adjust(i, sev):
        if pol.scar_rho is None:
            return severity_adjust_min(hospitals[i].level, sev)
        if sev == "immediate":
            return severity_adjust_min(hospitals[i].level, sev)
        if sev == "delayed" and hospitals[i].level in CENTERS:
            s = max(1, math.ceil(pol.scar_rho * cap0[i]))
            f = vfree(i)
            return SCAR_PENALTY_MIN * max(0.0, (s + 1 - f) / (s + 1))
        return 0.0

    def loadpen(i):
        k = len(committed[i])
        if k <= 0:
            return 0.0
        return LOAD_MAX_MIN * k / (k + max(vfree(i), 0))

    def softload(i, sev, pos, now):
        if pol.soft is None:
            return 0.0
        eta_me = now + travel(pos, i)
        s = 0.0
        for p, q in pending.items():
            if i not in q["top"]:
                continue
            if pol.soft == "full":
                if PRIORITY[q["sev"]] > PRIORITY[sev]:
                    continue
                if abs(q["t"] + travel(q["pos"], i) - eta_me) > TAU_MIN:
                    continue
            s += 1.0 / TOP_M
        return s

    def cost(i, pos, sev, now):
        c = travel(pos, i) + adjust(i, sev) + loadpen(i)
        s = softload(i, sev, pos, now)
        if s > 0:
            c += LOAD_MAX_MIN * s / (s + max(vfree(i), 0))
        return c

    def candidates(pos, sev, exclude, now):
        cs = [(cost(i, pos, sev, now), i) for i in range(n) if i not in exclude and vfree(i) > 0]
        cs.sort()
        return cs

    def depart(p, now, target, pos, is_forced=False):
        t_arr = now + travel(pos, target)
        route[p] = (target, t_arr)
        if is_forced:
            forced.add(p)
        push(t_arr, "arrive", p, target)

    def place(p, now, i, pos, top):
        """선택을 장부에 올린다 — 조율 팔은 바로, 독립 팔은 확정 지연 뒤에."""
        if pol.mode in ("greedy", "hung"):
            committed[i].add(p)
        else:
            pending[p] = dict(sev=sev_of[p], t=now, pos=pos, top=top)
            push(now + CONFIRM_DELAY_MIN, "commit", p, i)

    def decide_batch(items: list[dict], now: float):
        items = sorted(items, key=lambda it: (PRIORITY[it["sev"]], it["amb"]))
        if pol.mode == "hung":
            _hungarian(items, now)
            return
        for it in items:
            cs = candidates(it["pos"], it["sev"], it["exclude"], now)
            if not cs:
                _no_candidate(it, now)
                continue
            top = [i for _, i in cs[:TOP_M]]
            pick = cs[0][1]
            if pol.rand2 and len(cs) >= 2:
                pick = rng.choice([cs[0][1], cs[1][1]])
            place(it["p"], now, pick, it["pos"], top)
            depart(it["p"], now, pick, it["pos"])

    def _no_candidate(it, now):
        p = it["p"]
        stats["overflow"] += 1
        if it.get("refused_at") is not None:   # 도착 후 거절인데 어디에도 자리가 없다 — 그 자리에서 과밀 수용
            admitted[it["refused_at"]] += 1
            finish(p, now, it["refused_at"])
            return
        tgt = min((i for i in range(n) if i not in it["exclude"]), key=lambda i: travel(it["pos"], i), default=0)
        depart(p, now, tgt, it["pos"], is_forced=True)

    def _hungarian(items, now):
        from scipy.optimize import linear_sum_assignment
        m = len(items)
        cols: list[int | None] = []
        for i in range(n):
            cols += [i] * min(max(vfree(i), 0), m)
        cols += [None] * m   # 초과 슬롯 — 자리가 없을 때만
        big = 1e6
        mat = []
        for it in items:
            w = SEV_WEIGHT[it["sev"]]
            row = []
            for c in cols:
                if c is None:
                    row.append(w * (OVERFLOW_COST_MIN + min(travel(it["pos"], i) for i in range(n))))
                elif c in it["exclude"]:
                    row.append(big)
                else:
                    row.append(w * (travel(it["pos"], c) + adjust(c, it["sev"]) + loadpen(c)))
            mat.append(row)
        rows, picks = linear_sum_assignment(mat)
        for r, cidx in zip(rows, picks):
            it, c = items[r], cols[cidx]
            if c is None or mat[r][cidx] >= big:
                _no_candidate(it, now)
                continue
            place(it["p"], now, c, it["pos"], [c])
            depart(it["p"], now, c, it["pos"])

    queue: list[dict] = []
    scheduled: set[int] = set()

    def request(it: dict, t: float):
        queue.append(it)
        key = math.ceil(t / BUCKET_MIN) * BUCKET_MIN
        k = int(round(key * 1000))
        if k not in scheduled:
            scheduled.add(k)
            push(key, "flush", k)

    def finish(p, t, i):
        results[p] = dict(severity=sev_of[p], t_admitted=t, t_pickup=pickup_t[p], level=hospitals[i].level)
        push(t + params.t_handover_min + travel(scene_pos, i), "free", amb_of[p])

    pickup_t: dict[int, float] = {}
    next_patient = 0
    for a in range(params.n_ambulances):
        push(0.0, "free", a)
    horizon = 600.0
    for i, h in enumerate(hospitals):
        rate = flow * EXO_RATE_PER_MIN.get(h.level, EXO_RATE_PER_MIN[None])
        t = 0.0
        while rate > 0:
            t += rng.expovariate(rate)
            if t > horizon:
                break
            push(t, "exo", i)

    while ev and len(results) < params.n_patients:
        t, _, kind, who, extra = heapq.heappop(ev)
        if kind == "exo":
            i = who
            if cap0[i] - admitted[i] - exo[i] > 0:
                exo[i] += 1
                push(t + EXO_DWELL_MIN, "exo_leave", i)
                push(t + lag, "exo_seen", i)
        elif kind == "exo_leave":
            exo[who] -= 1
            push(t + lag, "exo_seen_leave", who)
        elif kind == "exo_seen":
            exo_vis[who] += 1
        elif kind == "exo_seen_leave":
            exo_vis[who] -= 1
        elif kind == "free":
            if next_patient >= params.n_patients:
                continue
            p = next_patient
            next_patient += 1
            sev_of[p] = severities[p]
            amb_of[p] = who
            pickup_t[p] = t
            skip[p] = set()
            request(dict(p=p, amb=who, sev=sev_of[p], pos=scene_pos, exclude=set()), t + params.t_load_min + params.t_broadcast_min)
        elif kind == "flush":
            scheduled.discard(who)
            batch = [it for it in queue]
            queue.clear()
            if batch:
                decide_batch(batch, t)
        elif kind == "commit":
            p, i = who, extra
            pending.pop(p, None)
            if p in route and route[p][0] == i:
                committed[i].add(p)
        elif kind == "arrive":
            p, i = who, extra
            if route.get(p, (None, None))[0] != i:
                continue
            route.pop(p)
            committed[i].discard(p)
            pending.pop(p, None)
            if cap0[i] - admitted[i] - exo[i] > 0 or p in forced:
                if p in forced and cap0[i] - admitted[i] - exo[i] <= 0:
                    stats["overflow"] += 1
                forced.discard(p)
                admitted[i] += 1
                finish(p, t, i)
            else:
                ours = cap0[i] - admitted[i] > 0   # 우리 환자가 채운 게 아니라 외부 유입이 채웠다
                cause = "EXTERNAL_INFLOW" if ours else "OUR_OVERCOMMIT"
                stats["refusals"] += 1
                stats["refusals_exo" if ours else "refusals_ours"] += 1
                sev = sev_of[p]
                if sev == "immediate":
                    stats["refusals_severe"] += 1
                    if hospitals[i].level in CENTERS:
                        stats["refusals_severe_center"] += 1
                refusal_log.append(dict(demo=True, source="virtual", t=round(t, 1), hospitalId=hospitals[i].hpid, level=hospitals[i].level,
                                        severity=sev, reasonCode="BEDS_FULL", cause=cause))
                skip[p].add(i)
                request(dict(p=p, amb=amb_of[p], sev=sev, pos=(hospitals[i].lat, hospitals[i].lng), exclude=set(skip[p]), refused_at=i),
                        t + params.t_transfer_min)

    pats = list(results.values())
    dur = [r["t_admitted"] - r["t_pickup"] for r in pats]

    def share(sev):
        g = [r for r in pats if r["severity"] == sev]
        return sum(1 for r in g if r["level"] in CENTERS) / len(g) if g else None

    def med(sev):
        g = [r["t_admitted"] - r["t_pickup"] for r in pats if r["severity"] == sev]
        return percentile(g, 0.5) if g else None

    return dict(complete=len(pats) == params.n_patients, median=percentile(dur, 0.5), p90=percentile(dur, 0.9),
                severeMedian=med("immediate"), mildMedian=med("delayed"), severeCenterShare=share("immediate"),
                mildCenterShare=share("delayed"), **stats), refusal_log


def run_cell(world, params, scene, flow, lag, pol, seeds):
    runs, logs = [], []
    for s in seeds:
        r, lg = simulate(world, params, s, scene, flow, lag, pol)
        runs.append(r)
        logs.append(lg)
    keys = ["median", "p90", "severeMedian", "mildMedian", "severeCenterShare", "mildCenterShare", "refusals", "refusals_severe",
            "refusals_severe_center", "refusals_ours", "refusals_exo", "overflow"]
    out = {"complete": all(r["complete"] for r in runs), "seeds": len(runs)}
    for k in keys:
        v = [r[k] for r in runs if r[k] is not None]
        out[k] = round(sum(v) / len(v), 2) if v else None
    return out, logs


def fmt(r):
    return (f"{r['median']:>6.1f}{r['p90']:>6.1f}{r['severeMedian'] or 0:>7.1f}{r['mildMedian'] or 0:>7.1f}{r['refusals']:>6.1f}"
            f"{r['refusals_ours']:>6.1f}{r['refusals_severe']:>6.1f}{r['refusals_severe_center']:>6.1f}{r['overflow']:>6.1f}"
            f"{(r['severeCenterShare'] or 0) * 100:>6.0f}%{(r['mildCenterShare'] or 0) * 100:>6.0f}%{'O' if r['complete'] else 'X':>3}")


HDR = f"{'팔':<12}{'중앙':>6}{'p90':>6}{'중증중앙':>7}{'경증중앙':>7}{'거절':>6}{'우리':>6}{'중증':>6}{'중증센':>6}{'초과':>6}{'중증→센':>7}{'경증→센':>7}{'완료':>3}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--scene", default="ilsan")
    args = ap.parse_args()
    scene = SCENES[args.scene]
    ts, hospitals = build_world(scene["snapshot_date"], scene["time"], radius_km=scene["radius_km"],
                                scene_lat=scene["lat"], scene_lng=scene["lng"])
    mix = (0.3, 0.4, 0.3)
    p_gen = SimParams(n_patients=scene["patients"], n_ambulances=30, severity_mix=mix)
    scarce = [replace(h, capacity=min(h.capacity, 2)) if h.level in CENTERS else h for h in hospitals]
    p_sc = SimParams(n_patients=80, n_ambulances=30, severity_mix=mix)
    worlds = {
        "일반(가용 %d, 환자 %d)" % (sum(h.capacity for h in hospitals), p_gen.n_patients): (hospitals, p_gen),
        "희소(센터 2석·전체 %d, 환자 80)" % sum(h.capacity for h in scarce): (scarce, p_sc),
    }
    seeds = list(range(args.seeds))
    out = {"scenario": dict(scene=args.scene, snapshotTs=ts, nHospitals=len(hospitals), confirmDelayMin=CONFIRM_DELAY_MIN,
                            bucketMin=BUCKET_MIN, tauMin=TAU_MIN, topM=TOP_M, scarPenaltyMin=SCAR_PENALTY_MIN, seeds=args.seeds,
                            note="가정 기반 가상 실험 — 메커니즘 확인용. 실측 근거 아님"),
           "exp1": [], "exp2": [], "exp3": [], "calibration": {}}
    sample_logs: list[dict] = []

    def block(title, key, arms, flows):
        print(f"\n━━ {title}")
        for wname, (w, prm) in worlds.items():
            for flow in flows:
                print(f"\n[{wname} · 외부유입 flow {flow} · lag 5 · 중증30% 무작위 순서 · 시드 {len(seeds)}]")
                print(HDR)
                for pol in arms:
                    r, logs = run_cell(w, prm, scene, flow, 5.0, pol, seeds)
                    r.update(world=wname, flow=flow, arm=pol.name)
                    out[key].append(r)
                    print(f"{pol.name:<12}{fmt(r)}")
                    if flow == 1.0 and wname.startswith("희소"):
                        sample_logs.extend(dict(x, arm=pol.name) for x in logs[0][:40])

    block("① 동시 최적 배정 — 독립 요청 vs 조율 그리디 vs 헝가리안", "exp1",
          [Policy("indep"), Policy("greedy", mode="greedy"), Policy("hung", mode="hung")], (1.0, 2.0))
    block("② 기대 부하 — 동시 요청에 대한 방어", "exp2",
          [Policy("indep"), Policy("rand2", rand2=True), Policy("soft_plain", soft="plain"), Policy("soft_full", soft="full")], (1.0, 2.0))
    scar_arms = [Policy("const")] + [Policy(f"scar_{r}", scar_rho=r) for r in (0.2, 0.4, 0.6)]
    block("③ 병상 희소성 연동 — 센터 보존", "exp3", scar_arms, (1.0, 2.0))

    # 가상 거절 로그로 ρ를 고르고(학습 시드), 따로 둔 시드에서 확인한다 — 순환을 피하려는 최소한의 분리
    print("\n━━ ③ 가상 거절 로그로 ρ 보정(학습 시드 0~9 → 검증 시드 10~29)")
    train, test = list(range(10)), list(range(10, 30))
    for wname, (w, prm) in worlds.items():
        best = None
        for pol in scar_arms:
            r, _ = run_cell(w, prm, scene, 1.0, 5.0, pol, train)
            score = r["refusals_severe_center"] + 0.3 * (r["mildMedian"] or 0)
            print(f"  {wname[:2]} 학습 {pol.name:<9} 중증센터거절 {r['refusals_severe_center']:>5.1f} 경증중앙 {r['mildMedian'] or 0:>5.1f}  점수 {score:>6.2f}")
            if best is None or score < best[0]:
                best = (score, pol)
        base_r, _ = run_cell(w, prm, scene, 1.0, 5.0, Policy("const"), test)
        pick_r, _ = run_cell(w, prm, scene, 1.0, 5.0, best[1], test)
        out["calibration"][wname] = dict(picked=best[1].name, heldOutConst=base_r, heldOutPicked=pick_r)
        print(f"  → 선택 {best[1].name} | 검증 시드 const: 중증센터거절 {base_r['refusals_severe_center']} 경증중앙 {base_r['mildMedian']} "
              f"| 선택: {pick_r['refusals_severe_center']} {pick_r['mildMedian']}")

    out_path = os.path.join(HERE, "rules_probe_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open(os.path.join(HERE, "rules_probe_virtual_rejections.jsonl"), "w", encoding="utf-8") as f:
        for row in sample_logs:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\n저장: {out_path} · 가상 거절 로그 표본 {len(sample_logs)}건(demo: true)")


if __name__ == "__main__":
    main()
