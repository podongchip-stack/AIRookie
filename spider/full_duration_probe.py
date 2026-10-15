"""적용 조건 4: 만실은 얼마나 오래 가나 — 거절 되먹임의 막는 시간(⑥에서 시험값 30분)의 근거.

E-Gen 스냅샷 전체에서 병원별 응급실 가용(hvec)의 시계열을 이어 붙여 두 가지를 잰다.
  만실 구간   hvec ≤ 0이 처음 관측된 폴부터 다음 hvec > 0 폴까지의 길이(관측 공백 > 60분이면 구간을 끊고 버림)
  잔여 만실   만실이 관측된 임의의 폴에서 Δ분 뒤에도 만실일 확률 — 되먹임이 실제로 맞닥뜨리는 질문
              ("도착해 보니 만실"은 구간의 시작이 아니라 구간 안의 무작위 시점이라 구간 길이보다 길게 나온다)
폴 간격이 날짜마다 다르다(5분 / 20분) — 두 묶음을 따로 집계한다. 등급(권역 4·지역센터 3·지역기관 2)별.

실행: PYTHONUTF8=1 python full_duration_probe.py → full_duration_probe.json
"""
from __future__ import annotations

import glob
import json
import os
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime

import numpy as np

import replay_probe as rp

GAP_MIN = 60.0
DELTAS = [5, 10, 15, 20, 30, 45, 60, 90, 120]


def load_series():
    """hpid -> [(분, hvec)] (전 기간, 시간순), 날짜별 폴 간격"""
    ser = defaultdict(list)
    cadence = {}
    t_ref = None
    for f in sorted(glob.glob(os.path.join(rp.SNAP, "*.jsonl"))):
        day = os.path.basename(f)[:10]
        times = []
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r.get("error") or r["operation"] != rp.BED_OP:
                    continue
                ts = datetime.fromisoformat(r["ts"][:19])
                t_ref = t_ref or ts
                t = (ts - t_ref).total_seconds() / 60
                times.append(t)
                for it in r["items"]:
                    try:
                        ser[it["hpid"]].append((t, int(it["hvec"])))
                    except (KeyError, ValueError, TypeError):
                        pass
        if len(times) > 1:
            cadence[day] = float(np.median(np.diff(sorted(times))))
    for v in ser.values():
        v.sort()
    return ser, cadence, t_ref


def main():
    H = {h["hpid"]: h for h in json.load(open(os.path.join(rp.HERE, "hospitals_xyz.json"), encoding="utf-8"))}
    ser, cadence, t_ref = load_series()
    # 폴 간격 묶음: 날짜 → 5 / 20
    fast_days = {d for d, c in cadence.items() if c <= 7.5}
    day_of = lambda t: (t_ref.toordinal() + int((t + t_ref.hour * 60 + t_ref.minute) // 1440))
    fast_ord = {datetime.fromisoformat(d).toordinal() for d in fast_days}

    spells = defaultdict(list)                    # (묶음, 등급) -> [길이 분]
    resid = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # (묶음, 등급) -> Δ -> [아직 만실, 관측]
    for hpid, s in ser.items():
        g = H.get(hpid, {}).get("g")
        if g not in (2, 3, 4):
            continue
        ts = [x[0] for x in s]
        vs = [x[1] for x in s]
        start = None
        for i in range(len(s)):
            t, v = ts[i], vs[i]
            grp = "5min" if day_of(t) in fast_ord else "20min"
            if i and t - ts[i - 1] > GAP_MIN:
                start = None
            if v <= 0:
                if start is None and i and vs[i - 1] > 0 and t - ts[i - 1] <= GAP_MIN:
                    start = t
                # 잔여: 이 만실 폴에서 Δ 뒤 값 (공백 없이 이어진 경우만)
                for d in DELTAS:
                    j = bisect_left(ts, t + d)
                    if j >= len(ts) or ts[j] - (t + d) > GAP_MIN / 2:
                        continue
                    if any(ts[k] - ts[k - 1] > GAP_MIN for k in range(i + 1, j + 1)):
                        continue
                    c = resid[(grp, g)][d]
                    c[0] += vs[j] <= 0
                    c[1] += 1
            elif start is not None:
                spells[(grp, g)].append(t - start)
                start = None

    out = {"cadence_by_day": cadence, "groups": {}}
    print(f"{'묶음':<6}{'등급':>4}{'구간 수':>8}{'중앙':>7}{'p75':>7}{'p90':>7}   잔여 만실 P(Δ분 뒤에도 만실)")
    print(" " * 39 + "".join(f"{d:>6}" for d in DELTAS))
    for grp in ("5min", "20min"):
        for g in (4, 3, 2):
            sp = np.array(spells[(grp, g)])
            rs = {d: (c[0] / c[1] if c[1] else None, c[1]) for d, c in resid[(grp, g)].items()}
            key = f"{grp}_g{g}"
            out["groups"][key] = dict(
                spells=len(sp),
                median=float(np.median(sp)) if len(sp) else None,
                p75=float(np.percentile(sp, 75)) if len(sp) else None,
                p90=float(np.percentile(sp, 90)) if len(sp) else None,
                resid={d: dict(p=rs[d][0], n=rs[d][1]) for d in DELTAS if d in rs})
            if not len(sp):
                continue
            print(f"{grp:<6}{g:>4}{len(sp):>8}{np.median(sp):>7.0f}{np.percentile(sp, 75):>7.0f}{np.percentile(sp, 90):>7.0f}   "
                  + "".join(f"{rs[d][0]:>6.2f}" if d in rs and rs[d][0] is not None else f"{'-':>6}" for d in DELTAS))
    json.dump(out, open(os.path.join(rp.HERE, "full_duration_probe.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
