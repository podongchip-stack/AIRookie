"""검증 3: τ 창 충돌이 실제로 일어나나 — E-Gen 스냅샷에서 "같은 병원 응급실 병상이 짧은 창 안에 2 이상 줄어드는" 사건 빈도.

읽기만 한다: info/Hospital_inform/info/data/snapshots_nationwide/*.jsonl (분석 전 snapshot_cloud.py --sync).
hvec(응급실 가용)은 병원이 입력할 때만 바뀌고 -1은 과밀 1명(값)으로 읽는다(mapper 규칙). 창 안 감소량은
"도착 − 퇴실"의 순변화라 동시 도착의 하한이다. 20분 폴링(9/7~10/9)은 연속 폴 1칸(≤25분), 5분 폴링(10/10~)은 15분
슬라이딩 창으로 센다. 결과는 collision_probe.json.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "..", "info", "Hospital_inform", "info", "data", "snapshots_nationwide")
BED_OP = "getEmrrmRltmUsefulSckbdInfoInqire"
LIST_OP = "getEgytListInfoInqire"
GRADE = {"권역응급의료센터": 4, "지역응급의료센터": 3, "지역응급의료기관": 2, "응급실운영신고기관": 1}


def strict_by_input_time(series_in):
    """보강: 병원 입력 시각(hvidate) 기준 — 연속 두 입력의 간격이 15분 이하이면서 hvec가 2 이상 준 사건만.
    일괄 갱신(한 시간에 한 번 몰아서 입력)이 섞이는 폴 기준 집계의 혼입을 걷어낸 하한값."""
    last: dict[str, tuple[int, datetime]] = {}
    strict = Counter(); loose = Counter(); by_grade = Counter()
    for hpid, items in series_in.items():
        for v, d in items:
            if hpid in last:
                pv, pd = last[hpid]
                if d != pd and pv - v >= 2:
                    loose[min(pv - v, 5)] += 1
                    if 0 < (d - pd).total_seconds() <= 15 * 60:
                        strict[min(pv - v, 5)] += 1
                        by_grade[GRADES.get(hpid, 1)] += 1
            last[hpid] = (v, d)
    return dict(events_2plus_between_inputs=sum(loose.values()), events_2plus_inputs_within_15min=sum(strict.values()),
                drop_dist_within_15min={str(k): v for k, v in sorted(strict.items())},
                by_grade_within_15min={str(g): by_grade.get(g, 0) for g in (4, 3, 2, 1)})


GRADES: dict[str, int] = {}


def hvec_of(item) -> int | None:
    v = item.get("hvec")
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def load():
    series: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
    inputs: dict[str, list[tuple[int, datetime]]] = defaultdict(list)   # (hvec, 병원 입력 시각) 폴 순서대로
    grade: dict[str, int] = GRADES
    errors = 0
    for f in sorted(glob.glob(os.path.join(SNAP, "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r.get("error"):
                    errors += 1
                    continue
                if r["operation"] == LIST_OP:
                    for it in r["items"]:
                        grade[it["hpid"]] = GRADE.get(it.get("dutyEmclsName", ""), 1)
                elif r["operation"] == BED_OP:
                    ts = datetime.fromisoformat(r["ts"])
                    for it in r["items"]:
                        v = hvec_of(it)
                        if v is not None:
                            series[it["hpid"]].append((ts, v))
                            try:
                                inputs[it["hpid"]].append((v, datetime.strptime(it["hvidate"], "%Y%m%d%H%M%S")))
                            except (KeyError, ValueError):
                                pass
    for s in series.values():
        s.sort()
    return series, grade, errors, inputs


def analyze(series, grade):
    drop_by_poll = Counter()      # 연속 폴(≤25분) 사이 감소량 분포
    win15_drop = Counter()        # 15분 슬라이딩 창(5분 폴링 구간만) 감소량 분포
    ev_hour = Counter()           # 2+ 감소 사건의 시각 분포 (연속 폴 기준)
    ev_grade = Counter(); hosp_days_grade = Counter()
    ev_hosp = Counter()
    hosp_hours = 0.0
    changes = 0
    for hpid, s in series.items():
        g = grade.get(hpid, 1)
        days = set()
        for i in range(1, len(s)):
            (t0, v0), (t1, v1) = s[i - 1], s[i]
            dt = (t1 - t0).total_seconds() / 60
            if dt <= 0 or dt > 25:
                continue
            hosp_hours += dt / 60
            days.add(t1.date())
            if v1 != v0:
                changes += 1
            d = v0 - v1
            if d > 0:
                drop_by_poll[min(d, 5)] += 1
                if d >= 2:
                    ev_hour[t1.hour] += 1
                    ev_grade[g] += 1
                    ev_hosp[hpid] += 1
        hosp_days_grade[g] += len(days)
        # 15분 슬라이딩 창 — 폴 간격 ≤ 6분인 구간만
        j = 0
        for i in range(len(s)):
            while j < i and (s[i][0] - s[j][0]).total_seconds() > 15 * 60:
                j += 1
            if j < i and (s[i][0] - s[i - 1][0]).total_seconds() <= 6 * 60:
                d = max(s[k][1] for k in range(j, i)) - s[i][1]
                if d > 0:
                    win15_drop[min(d, 5)] += 1
    return dict(
        hospitals=len(series), hospital_hours=round(hosp_hours), value_changes=changes,
        drop_by_poll={str(k): v for k, v in sorted(drop_by_poll.items())},
        win15_drop_5min_polling={str(k): v for k, v in sorted(win15_drop.items())},
        events_2plus=sum(v for k, v in drop_by_poll.items() if k >= 2),
        events_2plus_per_100_hospital_hours=round(100 * sum(v for k, v in drop_by_poll.items() if k >= 2) / max(1, hosp_hours), 3),
        events_by_hour={str(h): ev_hour.get(h, 0) for h in range(24)},
        events_by_grade={str(g): dict(events=ev_grade.get(g, 0), hospital_days=hosp_days_grade.get(g, 0),
                                      per_hospital_day=round(ev_grade.get(g, 0) / max(1, hosp_days_grade.get(g, 0)), 3)) for g in (4, 3, 2, 1)},
        hospitals_with_event=len(ev_hosp),
        top_hospitals=[dict(hpid=h, events=n) for h, n in ev_hosp.most_common(15)],
    )


def main():
    series, grade, errors, inputs = load()
    out = analyze(series, grade)
    out["strict_by_hospital_input_time"] = strict_by_input_time(inputs)
    out["error_lines_skipped"] = errors
    with open(os.path.join(HERE, "collision_probe.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k not in ("events_by_hour", "top_hospitals")}, ensure_ascii=False, indent=1))
    print("by hour:", " ".join(f"{h}:{out['events_by_hour'][str(h)]}" for h in range(24)))


if __name__ == "__main__":
    sys.exit(main())
