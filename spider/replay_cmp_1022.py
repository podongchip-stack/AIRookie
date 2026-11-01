# 같은 환자·같은 E-Gen 하루 재생에서 정책 비교 (replay_probe.py 재사용)
# 실행: python spider/replay_cmp_1022.py seoul 800 1  (2026-10-22, 결과보고서 2.4 환자 배분 근거. nearest_avail = 현재 관행 근사)
import sys, json, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay_probe as R
import numpy as np

_orig_choose = R.choose
def choose(policy, w, row, t, k, exclude, wload=True):
    if policy == "nearest_avail":
        # 현재 관행 근사: 각 구급대가 E-Gen(lag 분 낡은 값)에서 빈 병상이 보이는 가장 가까운 병원을 고름.
        # 다른 구급차의 이송 중 환자는 모름(공유 장부 없음). 이미 도착한 우리 환자는 병원 입력으로 반영됐다고 봄.
        H = w.H
        cands = [i for i in range(len(H)) if i not in exclude and np.isfinite(row[i])]
        if not cands: return None
        ok = []
        for i in cands:
            v = w.visible_raw(i, t)
            if v is None: continue
            if v - w.ours_dwelling(i, t) > 0: ok.append(i)
        if not ok:
            i = min(cands, key=lambda i: row[i]); return i, row[i], row[i], True
        i = min(ok, key=lambda i: row[i]); return i, row[i], row[i], False
    return _orig_choose(policy, w, row, t, k, exclude, wload)
R.choose = choose

region, n, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
G, lat, lng, tree = R.load_graph()
H = [h for h in json.load(open(os.path.join(R.HERE, "hospitals_xyz.json"), encoding="utf-8")) if h["hasBeds"]]
for h in H: h["node"] = R.nearest(tree, h["lat"], h["lng"])
polls = R.load_polls("2026-10-11")
hour_w = {int(k): v for k, v in json.load(open(os.path.join(R.HERE, "collision_probe.json")))["events_by_hour"].items()}
pats = R.make_patients(n, seed, H, tree, lat, lng, hour_w, polls[0][0], polls[-1][0], region)
cache = {}; res = []
for lag in (0.0, 15.0):
    for policy in ("nearest", "nearest_avail", "goldenlink", "spider_v2"):
        t0 = time.time()
        r = R.run(policy, False, pats, H, polls, lag, G, lat, lng, tree, cache, True)
        r["sec"] = round(time.time() - t0); res.append(r)
        print(region, n, seed, lag, policy, r["refusals"], r["meanMin"], r["k12_center"], r["k12_medianMin"], r["sec"], flush=True)
json.dump(dict(region=region, n=n, seed=seed, results=res), open(f"cmp_{region}_{n}_s{seed}.json", "w"), ensure_ascii=False, indent=1)
