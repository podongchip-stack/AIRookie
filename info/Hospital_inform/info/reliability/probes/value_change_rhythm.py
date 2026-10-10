"""병원별 '값 변화' 리듬 — 필드별 변화 간격 분포와 변화 시각(시·분) 집중도."""
import json, math, statistics, collections, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SNAP = Path("data/snapshots_nationwide")
OP = "getEmrrmRltmUsefulSckbdInfoInqire"
KST = timezone(timedelta(hours=9))
FIELDS = ["hvec", "hv28", "hvicc", "hvoc", "hvgc"]
GAP = 3600

def parse(raw, field):
    try: v = int(str(raw).strip())
    except (TypeError, ValueError): return None
    if v == -1 and field != "hvec": return None
    return v

# (hpid, field) -> list of change timestamps ; observation count ; last (ts, value)
changes = collections.defaultdict(list); obs = collections.Counter(); last = {}
names = {}; first_ts = last_ts = None
for p in sorted(SNAP.glob("*.jsonl")):
    for line in p.open("rb"):
        try: r = json.loads(line)
        except json.JSONDecodeError: continue
        if r.get("operation") != OP or "error" in r: continue
        ts = datetime.fromisoformat(r["ts"]).astimezone(KST)
        first_ts = first_ts or ts; last_ts = ts
        for it in r.get("items") or []:
            h = (it.get("hpid") or "").strip()
            if not h: continue
            names[h] = it.get("dutyName", "")
            for f in FIELDS:
                v = parse(it.get(f), f)
                if v is None: continue
                k = (h, f); prev = last.get(k)
                if prev and (ts - prev[0]).total_seconds() <= GAP:
                    obs[k] += 1
                    if v != prev[1]: changes[k].append(ts)
                last[k] = (ts, v)

span_days = (last_ts - first_ts).total_seconds() / 86400
print(f"기간 {span_days:.1f}일 · {first_ts:%m/%d}~{last_ts:%m/%d}")

def classify(h, f):
    k = (h, f); ch = changes.get(k, []); n_obs = obs[k]
    if n_obs < 200: return None
    rate = len(ch) / n_obs                         # 20분 간격당 변화 확률
    gaps_h = [(b - a).total_seconds() / 3600 for a, b in zip(ch, ch[1:])]
    gaps_h = [g for g in gaps_h if g <= 24]        # 수집 중단 걸친 간격 제외
    med_gap = statistics.median(gaps_h) if gaps_h else None
    hours = collections.Counter(t.hour for t in ch)
    top3 = sum(n for _, n in hours.most_common(3)) / len(ch) if ch else 0
    # 폴링 슬롯(:00/:20/:40)별 집중도 — 특정 슬롯에만 몰리면 정시 수기 갱신 의심
    slots = collections.Counter(t.minute // 20 for t in ch)
    slot_top = max(slots.values()) / len(ch) if ch else 0
    wd = collections.Counter(t.weekday() for t in ch)
    weekend_share = (wd[5] + wd[6]) / len(ch) if ch else 0
    if len(ch) < 10: kind = "거의 불변"
    elif top3 >= 0.5: kind = "정시 몰림(수기 의심)"
    elif rate >= 0.3: kind = "상시 변동(실시간)"
    else: kind = "간헐 변동"
    return dict(hpid=h, name=names[h], field=f, obs=n_obs, changes=len(ch), rate=rate,
                med_gap_h=med_gap, top3_hour_share=top3, slot_top=slot_top,
                weekend_share=weekend_share, top_hours=[hh for hh, _ in hours.most_common(3)], kind=kind)

rows = [r for h in names for f in FIELDS if (r := classify(h, f))]
for f in FIELDS:
    fr = [r for r in rows if r["field"] == f]
    if not fr: continue
    print(f"\n══ {f} ({len(fr)}곳) ══")
    kinds = collections.Counter(r["kind"] for r in fr)
    for k, n in kinds.most_common(): print(f"  {k:<16s} {n:>4}곳")
    rates = sorted(r["rate"] for r in fr)
    print("  20분당 변화 확률 p10/p50/p90:", " / ".join(f"{rates[int(len(rates)*q)]:.2f}" for q in (.1,.5,.9)))
    gaps = sorted(r["med_gap_h"] for r in fr if r["med_gap_h"])
    if gaps: print("  변화 간격 중위(h) p10/p50/p90:", " / ".join(f"{gaps[int(len(gaps)*q)]:.1f}" for q in (.1,.5,.9)))
    print("  변화의 상위 3시간대 점유 중위:", f"{statistics.median(r['top3_hour_share'] for r in fr):.0%}",
          "· 주말 비율 중위:", f"{statistics.median(r['weekend_share'] for r in fr):.0%}")
    if f == "hvec":
        print("  — 정시 몰림 예시:")
        for r in sorted((r for r in fr if r["kind"].startswith("정시")), key=lambda r: -r["top3_hour_share"])[:8]:
            print(f"    {r['hpid']} {r['name'][:14]:<14s} 변화 {r['changes']:>4} · 상위3시간 {r['top3_hour_share']:.0%} {r['top_hours']} · 간격중위 {r['med_gap_h']:.1f}h · 주말 {r['weekend_share']:.0%}")
        print("  — 상시 변동 예시(변화 확률 높은 순):")
        for r in sorted((r for r in fr if r["kind"].startswith("상시")), key=lambda r: -r["rate"])[:5]:
            print(f"    {r['hpid']} {r['name'][:14]:<14s} 변화 {r['changes']:>4} · 20분당 {r['rate']:.2f} · 상위3시간 {r['top3_hour_share']:.0%} · 간격중위 {r['med_gap_h']:.1f}h")
        print("  — 거의 불변 예시:")
        for r in sorted((r for r in fr if r["kind"] == "거의 불변"), key=lambda r: r["changes"])[:8]:
            print(f"    {r['hpid']} {r['name'][:14]:<14s} 변화 {r['changes']:>3}회 / 관측 {r['obs']}")

# 병원 단위 교차: hvec 상시 변동인데 다른 필드는 불변인 병원 수
by_h = collections.defaultdict(dict)
for r in rows: by_h[r["hpid"]][r["field"]] = r["kind"]
live_er = [h for h, d in by_h.items() if d.get("hvec", "").startswith("상시")]
print(f"\n응급실 상시 변동 {len(live_er)}곳 중 입원실(hvgc) 거의 불변 {sum(1 for h in live_er if by_h[h].get('hvgc')=='거의 불변')}곳 · "
      f"중환자실(hvicc) 거의 불변 {sum(1 for h in live_er if by_h[h].get('hvicc')=='거의 불변')}곳 · 수술실(hvoc) 거의 불변 {sum(1 for h in live_er if by_h[h].get('hvoc')=='거의 불변')}곳")
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
