"""검증 ②·⑤: 현 위치 재투척 vs 출발점 재투척 vs 그 자리 대기, 그리고 우선순위 양보 — 대량사고 시뮬레이션.

`sim/`의 세계(일산 장면: 실측 스냅샷 병원·병상·138명·중증도 분포)를 그대로 가져오되 `sim/` 파일은 수정하지 않는다
(모듈 import만). sim의 goldenlink 팔은 허브가 완전 정보로 예약하므로 도착 거절이 0이고 이동 중 바뀌는 게 없다 —
그 세계에서는 재투척·양보가 발동할 일이 없어 네 팔이 같다. 그래서 두 요소를 세계에 더한다:

  외부 유입   자가 내원·다른 구급대 환자가 병원마다 포아송으로 들어와 **실제** 병상을 쓴다(우리 예약과 무관하게).
             비율은 collision_probe(스냅샷 실측)의 등급별 감소 사건 빈도를 기준(flow=1.0)으로 두고 0~2배를 스윕한다.
  정보 지연   허브는 외부 유입을 lag 분 뒤에 본다(E-Gen 5분 묶음 + 병원 입력 지연). 자기 예약·수용은 즉시 본다.

팔(arm) — 첫 선택 규칙은 전부 허브와 같다(가용 병원 중 중증도 보정 이동시간 최단, sim.engine.severity_adjust_min).
다른 것은 "예약한 병원이 (허브가 보기에) 찼음을 알게 된 뒤" 무엇을 하느냐뿐이다:
  goldenlink   지금 허브: 그대로 가서 도착 후 거절이면 그 병원 위치에서 재선택(재이송 5분).
  spider_here  스파이더: 아는 순간 **현재 위치**에서 다시 던진다(현 위치 기준 이동시간 + 보정, 재투척 1분).
  spider_scene 아는 순간 **현장 기준 순위**의 다음 가용 병원으로 간다(이동은 현 위치에서).
  wait         아는 순간에도 계속 가서 병원 앞에서 자리가 날 때까지 기다린다(late binding).
양보(yield): 중증(immediate)이 고를 때 가용 병원이 없거나 더 가까운 곳이 이동 중인 경증·응급의 예약으로 차 있으면
그 예약을 밀어내고 자리를 가져간다. 밀린 쪽은 그 팔의 재투척 방식으로 다시 고른다(goldenlink·wait는 양보 없음).
허브의 BedHold(밀어낸 자리의 확정 유지)는 항상 켜져 있다고 본다 — 홀드 없는 변형은 허브에 없으므로 모델링하지 않는다.

실행: PYTHONUTF8=1 python sim_spider.py [--seeds 20]  → sim_spider_results.json. 표준 라이브러리만.
"""
from __future__ import annotations

import argparse
import heapq
import json
import os
import random
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "sim"))
from data_load import SCENES, Hospital, build_world, haversine_km  # noqa: E402  (sim/ 읽기 전용)
from engine import SimParams, percentile, severity_adjust_min      # noqa: E402

ARMS = ("goldenlink", "spider_here", "spider_scene", "wait")
PRIORITY = {"immediate": 0, "urgent": 1, "delayed": 2}
# 외부 유입 기준 비율(분당) — collision_probe 등급별 "하루당 2+ 감소 사건"(9.6/7.8/3.4)과 전체 감소 사건 빈도
# (병원-시간당 0.83)를 등급별로 나눈 근사. flow 배수로 스윕한다.
EXO_RATE_PER_MIN = {"권역응급의료센터": 0.022, "지역응급의료센터": 0.018,
                    "지역응급의료기관": 0.009, None: 0.004}
EXO_DWELL_MIN = 90.0     # 외부 유입 환자가 병상을 비우기까지
T_RECAST_MIN = 1.0       # 재투척(허브 재브로드캐스트) 비용
YIELD_GAIN_MIN = 10.0    # 양보 'scarce' 모드: 밀어내서 얻는 이득이 이 분 이상일 때만 발동 (대안이 사실상 없을 때)


@dataclass
class World:
    hospitals: list[Hospital]
    params: SimParams
    flow: float
    lag: float
    arm: str
    yield_on: bool
    rng: random.Random
    admitted: list[int] = field(init=False)
    exo: list[int] = field(init=False)            # 실제 외부 점유
    exo_visible: list[int] = field(init=False)    # 허브가 보는 외부 점유
    reservations: dict[int, int] = field(default_factory=dict)   # patient -> hospital
    waiting: dict[int, list[int]] = field(default_factory=dict)  # hospital -> [patient] (wait 팔)

    def __post_init__(self):
        n = len(self.hospitals)
        self.admitted = [0] * n
        self.exo = [0] * n
        self.exo_visible = [0] * n

    def actual_free(self, i: int) -> int:
        return self.hospitals[i].capacity - self.admitted[i] - self.exo[i]

    def reserved_at(self, i: int) -> list[int]:
        return [p for p, h in self.reservations.items() if h == i]

    def visible_free(self, i: int) -> int:
        """허브가 보는 약속 가능 병상: 정원 − 수용 − (지연된) 외부 점유 − 예약."""
        return self.hospitals[i].capacity - self.admitted[i] - self.exo_visible[i] - len(self.reserved_at(i))


@dataclass
class Amb:
    idx: int
    patient: int | None = None
    severity: str = "urgent"
    t_pickup: float = 0.0
    from_pos: tuple[float, float] = (0.0, 0.0)
    to: int | None = None
    t0: float = 0.0
    t1: float = 0.0
    recasts: int = 0
    refusals: int = 0
    bumped: int = 0
    waited: float = 0.0
    skip: set = field(default_factory=set)   # 양보한(밀려난) 병원 — 모델 규칙대로 다시 걸지 않는다
    forced: bool = False                      # 빈 벽이 없어 초과로 붙은 상태 — 더는 밀어내지 않는다(모델의 초과 규칙)


def simulate(arm: str, hospitals: list[Hospital], params: SimParams, seed: int, scene: dict,
             flow: float, lag: float, yield_on: bool, triage_order: bool = True) -> dict:
    rng = random.Random(seed)
    w = World(hospitals, params, flow, lag, arm, yield_on, rng)
    n = len(hospitals)
    scene_pos = (scene["lat"], scene["lng"])

    def travel(pos, i):
        return haversine_km(pos[0], pos[1], hospitals[i].lat, hospitals[i].lng) * params.road_factor / params.speed_kmh * 60.0

    def pos_at(a: Amb, t: float):
        if a.to is None or a.t1 <= a.t0:
            return a.from_pos
        f = max(0.0, min(1.0, (t - a.t0) / (a.t1 - a.t0)))
        h = hospitals[a.to]
        return (a.from_pos[0] + (h.lat - a.from_pos[0]) * f, a.from_pos[1] + (h.lng - a.from_pos[1]) * f)

    # 중증도 배치는 sim.engine과 같은 규칙(중증 우선 순서)
    from engine import _assign_severities
    severities = _assign_severities(params.n_patients, params.severity_mix, rng)
    if not triage_order:
        rng.shuffle(severities)   # ⑤용: 현장 트리아지 없이 도착 순 — 중증이 늦게도 나온다
    ambs = [Amb(i) for i in range(params.n_ambulances)]
    results: dict[int, dict] = {}
    ev: list[tuple[float, int, str, int]] = []   # (t, seq, kind, who)
    seq = 0

    def push(t, kind, who):
        nonlocal seq
        seq += 1
        heapq.heappush(ev, (t, seq, kind, who))

    for a in ambs:
        push(0.0, "free", a.idx)
    # 외부 유입 일정 (포아송) — 시뮬 상한 600분
    horizon = 600.0
    for i, h in enumerate(hospitals):
        rate = flow * EXO_RATE_PER_MIN.get(h.level, EXO_RATE_PER_MIN[None])
        t = 0.0
        while rate > 0:
            t += rng.expovariate(rate)
            if t > horizon:
                break
            push(t, "exo", i)
    next_patient = 0
    stats = dict(refusals=0, recasts=0, bumps=0, yields=0, overflow=0, waits=0, wait_min=0.0, exo_admitted=0, exo_turned_away=0)

    def choose(pos, severity, exclude: set[int], scene_rank: bool):
        """허브 규칙: 보이는 가용 병원 중 (이동시간 + 중증도 보정) 최단. scene_rank면 현장 기준 순위로 고른다."""
        base = scene_pos if scene_rank else pos
        cands = [i for i in range(n) if i not in exclude and w.visible_free(i) > 0]
        if not cands:
            return None
        return min(cands, key=lambda i: travel(base, i) + severity_adjust_min(hospitals[i].level, severity))

    def choose_with_yield(pos, severity, exclude: set[int], scene_rank: bool, me: int, allow_yield: bool = True):
        """양보: 중증이면 가용 병원뿐 아니라 '이동 중인 덜 위급한 예약'을 밀어낼 수 있는 병원도 후보로 본다.
        yield_on: False / "all"(창이 겹치면 언제나) / "scarce"(이득이 YIELD_GAIN_MIN 이상일 때만 + 밀린 쪽은 다시 못 밀어냄)."""
        best = choose(pos, severity, exclude, scene_rank)
        if not (yield_on and allow_yield and severity == "immediate" and arm.startswith("spider")):
            return best, None
        base = scene_pos if scene_rank else pos
        best_cost = travel(base, best) + severity_adjust_min(hospitals[best].level, severity) if best is not None else float("inf")
        pick, victim = best, None
        for i in range(n):
            if i in exclude or w.visible_free(i) > 0:
                continue
            # 실제로 수용 가능한 병상 자체가 없으면(허브가 보기에) 밀어내도 소용없다
            if hospitals[i].capacity - w.admitted[i] - w.exo_visible[i] <= 0:
                continue
            movable = [p for p in w.reserved_at(i) if p != me and PRIORITY[results_sev[p]] > PRIORITY[severity]
                       and p in en_route and not ambs[en_route[p]].forced]
            if not movable:
                continue
            cost = travel(base, i) + severity_adjust_min(hospitals[i].level, severity)
            if yield_on == "scarce" and best_cost - cost < YIELD_GAIN_MIN:
                continue
            if cost < best_cost:
                best_cost, pick = cost, i
                # 가장 덜 위급하고 가장 늦게 도착하는 예약을 밀어낸다
                victim = max(movable, key=lambda p: (PRIORITY[results_sev[p]], ambs[en_route[p]].t1))
        return pick, victim

    results_sev: dict[int, str] = {}
    en_route: dict[int, int] = {}   # patient -> amb idx (이동 중)

    def depart(a: Amb, t: float, target: int, pos):
        a.from_pos = pos
        a.to = target
        a.t0 = t
        a.t1 = t + travel(pos, target)
        w.reservations[a.patient] = target
        en_route[a.patient] = a.idx
        push(a.t1, "arrive", a.idx)

    def recast(a: Amb, t: float, reason: str, allow_yield: bool = True):
        """예약이 깨진 구급차가 그 팔의 방식으로 다시 고른다."""
        w.reservations.pop(a.patient, None)
        pos = pos_at(a, t)
        en_route.pop(a.patient, None)
        a.to = None
        scene_rank = arm == "spider_scene"
        target, victim = choose_with_yield(pos, a.severity, set(a.skip), scene_rank, a.patient, allow_yield)
        a.recasts += 1
        stats["recasts"] += 1
        if victim is not None:
            stats["yields"] += 1
            bump(victim, t + T_RECAST_MIN)
        a.forced = target is None
        if target is None:
            target = min((i for i in range(n) if i not in a.skip), key=lambda i: travel(pos, i), default=min(range(n), key=lambda i: travel(pos, i)))  # 빈 벽 없음 — 가장 가까운 곳에 초과로
        depart(a, t + T_RECAST_MIN, target, pos)

    def bump(p: int, t: float):
        """이동 중인 환자 p의 예약을 깬다. 그 구급차는 현재 위치에서 팔의 방식으로 다시 고른다."""
        a = ambs[en_route.pop(p)]
        stats["bumps"] += 1
        a.bumped += 1
        a.skip.add(w.reservations.pop(p))
        pos = pos_at(a, t)
        a.to = None          # 옛 도착 이벤트 무효화 (arrive에서 en_route·t1 대조로 걸러진다)
        a.from_pos = pos
        recast(a, t, "bumped", allow_yield=(yield_on != "scarce"))   # scarce: 밀린 쪽은 연쇄로 밀어내지 못한다

    def check_broken_reservations(i: int, t: float):
        """허브가 보기에 병원 i의 약속 가능 병상이 음수가 되면 덜 위급한 예약부터 깨진다(spider 팔만 이동 중 반응)."""
        if not arm.startswith("spider"):
            return
        while w.visible_free(i) < 0:
            movable = [p for p in w.reserved_at(i) if p in en_route and not ambs[en_route[p]].forced]
            if not movable:
                break
            victim = max(movable, key=lambda p: (PRIORITY[results_sev[p]], ambs[en_route[p]].t1))
            bump(victim, t)

    def finish(a: Amb, t: float, i: int):
        results[a.patient] = dict(index=a.patient, severity=a.severity, t_pickup=a.t_pickup, t_admitted=t,
                                  hospital=hospitals[i].hpid, level=hospitals[i].level,
                                  recasts=a.recasts, refusals=a.refusals, bumped=a.bumped)
        a.patient = None; a.to = None; a.recasts = 0; a.refusals = 0; a.bumped = 0; a.skip = set(); a.forced = False
        t_free = t + params.t_handover_min + travel(scene_pos, i)
        push(t_free, "free", a.idx)

    while ev:
        t, _, kind, who = heapq.heappop(ev)
        if kind == "exo":
            i = who
            if w.actual_free(i) > 0:
                w.exo[i] += 1
                stats["exo_admitted"] += 1
                push(t + EXO_DWELL_MIN, "exo_leave", i)
                push(t + lag, "exo_seen", i)
            else:
                stats["exo_turned_away"] += 1
        elif kind == "exo_leave":
            w.exo[who] -= 1
            push(t + lag, "exo_seen_leave", who)
            # 대기 중이던 우리 환자가 있으면 들어간다
            q = w.waiting.get(who, [])
            if q and w.actual_free(who) > 0:
                p = q.pop(0)
                a = ambs[en_route.pop(p)]
                w.admitted[who] += 1
                stats["wait_min"] += t - a.t1
                finish(a, t, who)
        elif kind == "exo_seen":
            w.exo_visible[who] += 1
            check_broken_reservations(who, t)
        elif kind == "exo_seen_leave":
            w.exo_visible[who] -= 1
        elif kind == "free":
            a = ambs[who]
            if next_patient >= params.n_patients:
                continue
            a.patient = next_patient
            a.severity = severities[next_patient]
            results_sev[next_patient] = a.severity
            next_patient += 1
            a.t_pickup = t
            t_dec = t + params.t_load_min + params.t_broadcast_min
            target, victim = choose_with_yield(scene_pos, a.severity, set(), False, a.patient)
            if victim is not None:
                stats["yields"] += 1
                bump(victim, t_dec)
            a.forced = target is None
            if target is None:
                target = min(range(n), key=lambda i: travel(scene_pos, i))
            a.to = None
            depart(a, t_dec, target, scene_pos)
        elif kind == "arrive":
            a = ambs[who]
            if a.patient is None or a.to is None or en_route.get(a.patient) != a.idx or abs(a.t1 - t) > 1e-6:
                continue  # 밀려서 이미 다른 곳으로 간 구급차의 옛 도착 이벤트
            i = a.to
            if w.actual_free(i) > 0 or a.forced:
                if a.forced and w.actual_free(i) <= 0:
                    stats["overflow"] += 1
                w.reservations.pop(a.patient, None)
                del en_route[a.patient]
                w.admitted[i] += 1
                finish(a, t, i)
            else:
                stats["refusals"] += 1
                a.refusals += 1
                if arm == "wait":
                    stats["waits"] += 1
                    w.reservations.pop(a.patient, None)
                    w.waiting.setdefault(i, []).append(a.patient)
                else:
                    # 도착 후 거절 — 그 병원 위치에서 재선택(허브 규칙), 재이송 5분
                    del en_route[a.patient]
                    a.from_pos = (hospitals[i].lat, hospitals[i].lng)
                    a.to = None
                    exclude = {i}
                    target = choose((hospitals[i].lat, hospitals[i].lng), a.severity, exclude, False)
                    if target is None:
                        # 반경 안 어디에도 (허브가 보기에) 자리가 없음 — sim.engine과 같이 그 자리에서 과밀 수용
                        stats["overflow"] += 1
                        w.admitted[i] += 1
                        finish(a, t, i)
                    else:
                        depart(a, t + params.t_transfer_min, target, a.from_pos)

    return _collect(results, params.n_patients, stats, hospitals)


def _collect(results, n_patients, stats, hospitals):
    pats = list(results.values())
    done = len(pats) == n_patients
    dur = [p["t_admitted"] - p["t_pickup"] for p in pats]
    centers = {"권역응급의료센터", "지역응급의료센터"}

    def share(sev):
        g = [p for p in pats if p["severity"] == sev]
        return round(sum(1 for p in g if p["level"] in centers) / len(g), 3) if g else None

    def med(sev):
        g = [p["t_admitted"] - p["t_pickup"] for p in pats if p["severity"] == sev]
        return percentile(g, 0.5) if g else None

    return dict(complete=done, n=len(pats), medianTransportMin=percentile(dur, 0.5), p90TransportMin=percentile(dur, 0.9),
                finishedAtMin=round(max((p["t_admitted"] for p in pats), default=0), 1),
                severeMedianMin=med("immediate"), mildMedianMin=med("delayed"),
                severeCenterShare=share("immediate"), mildCenterShare=share("delayed"), **stats)


def run_cell(arm, hospitals, params, scene, flow, lag, yield_on, seeds, triage_order=True):
    runs = []
    for s in range(seeds):
        runs.append(simulate(arm, hospitals, params, s, scene, flow, lag, yield_on, triage_order))
    keys = ["medianTransportMin", "p90TransportMin", "finishedAtMin", "severeMedianMin", "mildMedianMin",
            "severeCenterShare", "mildCenterShare", "refusals", "recasts", "bumps", "yields", "overflow", "waits", "wait_min", "exo_admitted"]
    out = {"complete": all(r["complete"] for r in runs), "seeds": seeds}
    for k in keys:
        vals = [r[k] for r in runs if r[k] is not None]
        out[k] = round(sum(vals) / len(vals), 2) if vals else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--scene", default="ilsan")
    args = ap.parse_args()
    scene = SCENES[args.scene]
    ts, hospitals = build_world(scene["snapshot_date"], scene["time"], radius_km=scene["radius_km"],
                                scene_lat=scene["lat"], scene_lng=scene["lng"])
    params = SimParams(n_patients=scene["patients"], n_ambulances=30, severity_mix=scene["severity_mix"])
    out = {"scenario": dict(scene=args.scene, snapshotTs=ts, nHospitals=len(hospitals),
                            totalBeds=sum(h.capacity for h in hospitals), patients=params.n_patients, ambulances=30),
           "sweep": [], "yield": []}
    print(f"[{scene['label']}] 병원 {len(hospitals)}곳 가용 {out['scenario']['totalBeds']} 환자 {params.n_patients} 시드 {args.seeds}")
    hdr = f"{'flow':>5}{'lag':>5}{'arm':<14}{'중앙값':>7}{'p90':>7}{'중증중앙':>8}{'경증중앙':>8}{'거절':>6}{'재투척':>7}{'밀림':>6}{'대기':>6}{'중증→센터':>9}{'완료':>5}"
    print(hdr)
    for flow in (0.0, 0.5, 1.0, 2.0):
        for lag in (0.0, 5.0, 15.0):
            if flow == 0.0 and lag > 0:
                continue
            for arm in ARMS:
                r = run_cell(arm, hospitals, params, scene, flow, lag, False, args.seeds)
                r.update(flow=flow, lag=lag, arm=arm, yield_on=False)
                out["sweep"].append(r)
                print(f"{flow:>5.1f}{lag:>5.0f}{arm:<14}{r['medianTransportMin']:>7.1f}{r['p90TransportMin']:>7.1f}"
                      f"{r['severeMedianMin'] or 0:>8.1f}{r['mildMedianMin'] or 0:>8.1f}{r['refusals']:>6.1f}{r['recasts']:>7.1f}"
                      f"{r['bumps']:>6.1f}{r['waits']:>6.1f}{(r['severeCenterShare'] or 0)*100:>8.0f}%{'O' if r['complete'] else 'X':>5}")
    # ⑤ 양보: 일산 분포(중증 1.5%, 트리아지 순)에선 중증 앞에 밀어낼 경증 예약이 없어 양보가 발동하지 않는다.
    # 중증 30%·도착 순(무작위) 세계에서 잰다 — 같은 병원·병상·환자 수. 그리고 양보가 값을 할 '희소 세계'(권역·지역센터
    # 가용을 2석으로 깎아 센터 병상 < 중증 수요)를 따로 둔다. 양보 모드: all(창이 겹치면 언제나) / scarce(이득 10분 이상 + 연쇄 금지).
    from dataclasses import replace as dc_replace
    params5 = SimParams(n_patients=scene["patients"], n_ambulances=30, severity_mix=(0.3, 0.4, 0.3))
    centers = {"권역응급의료센터", "지역응급의료센터"}
    # 희소 세계: 센터를 2석씩으로 깎으면 전체 가용이 82석이라 환자 138명은 초과 수용이 결과를 지배한다 → 환자 80명
    # (중증 24명 > 센터 22석, 전체 80 < 82)으로 "센터만 모자란" 세계를 만든다.
    scarce = [dc_replace(h, capacity=min(h.capacity, 2)) if h.level in centers else h for h in hospitals]
    params_sc = SimParams(n_patients=80, n_ambulances=30, severity_mix=(0.3, 0.4, 0.3))
    out["scarce_scenario"] = dict(centerBeds=sum(h.capacity for h in scarce if h.level in centers),
                                  centerBedsOriginal=sum(h.capacity for h in hospitals if h.level in centers),
                                  totalBeds=sum(h.capacity for h in scarce), patients=params_sc.n_patients,
                                  severeDemand=round(params_sc.n_patients * 0.3))
    for label, world, prm, key in (("일반 세계(가용 200, 환자 138)", hospitals, params5, "yield"),
                                   (f"희소 세계(센터 가용 {out['scarce_scenario']['centerBeds']}석·전체 {out['scarce_scenario']['totalBeds']}석, 환자 80·중증 {out['scarce_scenario']['severeDemand']}명)", scarce, params_sc, "scarce")):
        out[key] = []
        print(f"\n양보(⑤) — {label}, flow 1.0, lag 5, 중증 30%·무작위 순서")
        print(hdr.replace("대기", "양보"))
        for arm, y in (("goldenlink", False), ("spider_here", False), ("spider_here", "all"), ("spider_here", "scarce")):
            r = run_cell(arm, world, prm, scene, 1.0, 5.0, y, args.seeds, triage_order=False)
            r.update(flow=1.0, lag=5.0, arm=arm, yield_on=y, severity_mix=[0.3, 0.4, 0.3], triage_order=False)
            out[key].append(r)
            name = arm + ({"all": "+양보", "scarce": "+양보(희소)"}.get(y, ""))
            print(f"{1.0:>5.1f}{5:>5.0f}{name:<14}{r['medianTransportMin']:>7.1f}{r['p90TransportMin']:>7.1f}"
                  f"{r['severeMedianMin'] or 0:>8.1f}{r['mildMedianMin'] or 0:>8.1f}{r['refusals']:>6.1f}{r['recasts']:>7.1f}"
                  f"{r['bumps']:>6.1f}{r['yields']:>6.1f}{(r['severeCenterShare'] or 0)*100:>8.0f}%{'O' if r['complete'] else 'X':>5}")
    with open(os.path.join(HERE, "sim_spider_results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
