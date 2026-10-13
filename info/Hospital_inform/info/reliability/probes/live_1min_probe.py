"""E-Gen 전국 병상을 1분마다 읽어, 묶음(값이 바뀐 폴링)마다 필드별 변화 병원 수를 센다."""
import sys, time, json
from datetime import datetime
sys.path.insert(0, r"C:\Dev\AIRookie\info\Hospital_inform\info")
from egen.client import HttpEgenClient

FIELDS = ["hvec", "hv28", "hvicc", "hvoc", "hvgc"]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 32
out = sys.argv[2] if len(sys.argv) > 2 else None
client = HttpEgenClient()
prev = None; rows = []
for i in range(N):
    t0 = time.time()
    try:
        items = {it["hpid"]: it for it in client.get_realtime_beds("", "") if it.get("hpid")}
    except Exception as e:  # noqa
        print(f"{datetime.now():%H:%M:%S} 오류 {e}", flush=True); time.sleep(max(0, 60 - (time.time() - t0))); continue
    if prev is not None:
        common = [h for h in items if h in prev]
        hv_adv = sum(1 for h in common if items[h].get("hvidate") != prev[h].get("hvidate"))
        ch = {f: sum(1 for h in common if items[h].get(f) != prev[h].get(f)) for f in FIELDS}
        row = {"ts": datetime.now().isoformat(timespec="seconds"), "n": len(common), "hvidate_adv": hv_adv, **ch}
        rows.append(row)
        print(f"{row['ts'][11:]} 병원 {len(common)} · hvidate 전진 {hv_adv:>3} · " +
              " · ".join(f"{f} {ch[f]:>3}" for f in FIELDS), flush=True)
    prev = items
    time.sleep(max(0, 60 - (time.time() - t0)))
if out:
    json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
