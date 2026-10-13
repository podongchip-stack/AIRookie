"""병원별 hvidate 송출 주기 탐색 — 스냅샷 안의 서로 다른 hvidate 값들의 간격 패턴."""
import json, math, statistics, collections, sys
from datetime import datetime
from pathlib import Path

SNAP = Path("data/snapshots_nationwide")
OP = "getEmrrmRltmUsefulSckbdInfoInqire"

hv_by_h: dict[str, set[str]] = collections.defaultdict(set)
ages: dict[str, list[float]] = collections.defaultdict(list)
names: dict[str, str] = {}
polls = 0
for p in sorted(SNAP.glob("*.jsonl")):
    for line in p.open("rb"):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("operation") != OP or "error" in r:
            continue
        ts = datetime.fromisoformat(r["ts"]).replace(tzinfo=None)
        polls += 1
        for it in r.get("items") or []:
            h = (it.get("hpid") or "").strip(); hv = str(it.get("hvidate") or "")
            if not h or len(hv) != 14:
                continue
            hv_by_h[h].add(hv); names[h] = it.get("dutyName", "")
            try:
                age = (ts - datetime.strptime(hv, "%Y%m%d%H%M%S")).total_seconds() / 60
            except ValueError:
                continue
            if -5 <= age <= 360:
                ages[h].append(age)

rows = []
for h, hvs in hv_by_h.items():
    ts_list = sorted(datetime.strptime(x, "%Y%m%d%H%M%S") for x in hvs)
    if len(ts_list) < 20:
        continue
    secs = [t.second for t in ts_list]
    mins = [t.minute for t in ts_list]
    # 간격(분, 반올림)의 gcd — 주기 송출이면 주기의 약수로 수렴
    gaps = [round((b - a).total_seconds() / 60) for a, b in zip(ts_list, ts_list[1:])]
    gaps = [g for g in gaps if 0 < g <= 24 * 60]
    g = 0
    for x in gaps:
        g = math.gcd(g, x)
    sec_mode, sec_mode_n = collections.Counter(secs).most_common(1)[0]
    sec_share = sec_mode_n / len(secs)
    # 분 자릿수가 어떤 격자에 놓이는지: 5/10/15/20/30/60 중 맞는 가장 큰 것
    grid = next((k for k in (60, 30, 20, 15, 10, 5) if all(m % k == 0 for m in mins)), 1)
    a = sorted(ages[h]) if ages[h] else [float("nan")]
    p50 = a[len(a) // 2]; p95 = a[int(len(a) * 0.95)] if len(a) > 1 else a[0]
    if grid >= 5 and sec_share >= 0.8:
        kind = f"주기 {grid}분 격자(자동)"
    elif g >= 5 and sec_share >= 0.8:
        kind = f"주기 gcd {g}분(자동)"
    elif sec_share >= 0.8:
        kind = "초 고정·분 불규칙"
    else:
        kind = "불규칙(초 흩어짐)"
    rows.append((h, names[h], len(ts_list), grid, g, sec_mode, sec_share, p50, p95, kind))

print(f"폴링 {polls:,}회 · 병원 {len(rows)}곳 (hvidate 20개 이상)")
kinds = collections.Counter(r[9] for r in rows)
print("\n== 분류 ==")
for k, n in kinds.most_common():
    print(f"  {k:<22s} {n:>4}곳")
print("\n== 격자/gcd 분포 (자동 송출 병원) ==")
auto = [r for r in rows if "자동" in r[9]]
print("  격자:", dict(collections.Counter(r[3] for r in auto).most_common()))
print("  gcd :", dict(collections.Counter(r[4] for r in auto).most_common(10)))
print("\n== 경과 p95 (분) 분포 ==")
p95s = sorted(r[8] for r in rows if not math.isnan(r[8]))
for q in (0.1, 0.5, 0.9, 0.99):
    print(f"  p{int(q*100):>2}: {p95s[int(len(p95s)*q)]:.1f}")
print("\n== 예시: 불규칙 병원 상위 (경과 p95 긴 순) ==")
for r in sorted((r for r in rows if "자동" not in r[9]), key=lambda r: -r[8])[:15]:
    print(f"  {r[0]} {r[1][:14]:<14s} hv {r[2]:>5} · 격자 {r[3]:>2} · gcd {r[4]:>3} · 초 {r[5]:02d}({r[6]:.0%}) · 경과 p50 {r[7]:5.1f} p95 {r[8]:6.1f} · {r[9]}")
print("\n== 예시: 자동 송출 병원 (경과 p95 긴 순) ==")
for r in sorted(auto, key=lambda r: -r[8])[:10]:
    print(f"  {r[0]} {r[1][:14]:<14s} hv {r[2]:>5} · 격자 {r[3]:>2} · gcd {r[4]:>3} · 초 {r[5]:02d}({r[6]:.0%}) · 경과 p50 {r[7]:5.1f} p95 {r[8]:6.1f} · {r[9]}")

out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if out:
    out.write_text(json.dumps([dict(zip(("hpid","name","n","grid","gcd","sec","secShare","p50","p95","kind"), r)) for r in rows], ensure_ascii=False, indent=1), encoding="utf-8")
