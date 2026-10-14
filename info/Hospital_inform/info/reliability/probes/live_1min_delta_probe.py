"""E-Gen 5분 묶음마다 필드별 변화 폭(Δ) 분포를 기록한다. 1분 폴링, 값이 바뀐 폴링만 묶음으로 본다."""
import sys, time, json, collections
from datetime import datetime
sys.path.insert(0, r"C:\Dev\AIRookie\info\Hospital_inform\info")
from egen.client import HttpEgenClient

FIELDS = ["hvec", "hvgc", "hvoc", "hvicc"]
N = int(sys.argv[1]); out = sys.argv[2]
client = HttpEgenClient()

def val(it, f):
    try: return int(str(it.get(f)).strip())
    except (TypeError, ValueError): return None

prev = None; batches = []
for i in range(N):
    t0 = time.time()
    try:
        items = {it["hpid"]: it for it in client.get_realtime_beds("", "") if it.get("hpid")}
    except Exception as e:  # noqa
        print(f"{datetime.now():%H:%M:%S} 오류 {e}", flush=True); time.sleep(max(0, 60 - (time.time() - t0))); continue
    if prev is not None:
        changes = []
        for h in items:
            if h not in prev: continue
            for f in FIELDS:
                a, b = val(prev[h], f), val(items[h], f)
                if a is not None and b is not None and a != b:
                    changes.append({"hpid": h, "name": items[h].get("dutyName", ""), "field": f, "from": a, "to": b, "delta": b - a})
        if changes:
            batches.append({"ts": datetime.now().isoformat(timespec="seconds"), "changes": changes})
            summary = {f: collections.Counter(min(5, max(-5, c["delta"])) for c in changes if c["field"] == f) for f in FIELDS}
            print(f"{datetime.now():%H:%M:%S} 묶음 — " + " | ".join(
                f"{f} n={sum(summary[f].values())} ±1 {sum(v for d, v in summary[f].items() if abs(d)==1)} ±2 {sum(v for d, v in summary[f].items() if abs(d)==2)} ≥3 {sum(v for d, v in summary[f].items() if abs(d)>=3)}"
                for f in FIELDS), flush=True)
    prev = items
    time.sleep(max(0, 60 - (time.time() - t0)))
json.dump(batches, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
