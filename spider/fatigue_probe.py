"""의사 피로도 대리 지표 분포: 최근 6시간 응급실 수용 건수 ÷ 응급의학과 전문의 수.
수용 건수 = 5분 스냅샷에서 응급실 가용 병상(hvec)이 줄어든 양의 합 (환자 1명 들어오면 1 감소).
입력: 저장소 스냅샷 2026-10-10(13:25~, 5분)·10-11, 심평원 전문의 캐시."""
import json, sys, math, pathlib
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
INFO = pathlib.Path(__file__).resolve().parent.parent / 'info/Hospital_inform/info'
files = [INFO/f'data/snapshots_nationwide/2026-10-{d:02d}.jsonl' for d in (7,8,9,10,11)]  # 7~9일 20분, 10일 13:25~ 5분
hosp = {h['hpid']: h for h in json.load(open(pathlib.Path(__file__).parent/'hospitals_xyz.json', encoding='utf-8'))}
spec = json.load(open(INFO/'data/hira/specialists.json', encoding='utf-8'))
em = {}
for hp, rows in spec.items():
    for r in rows:
        if r.get('dgsbjtCdNm') == '응급의학과': em[hp] = r.get('dtlSdrCnt', 0)

def num(v):
    try: return int(v)
    except: return None
series = defaultdict(list)  # hpid -> [(ts, hvec)]
errs = []
for f in files:
    for line in open(f, encoding='utf-8'):
        d = json.loads(line)
        if d['operation'] != 'getEmrrmRltmUsefulSckbdInfoInqire': continue
        if 'items' not in d: errs.append(d['ts']); continue
        ts = datetime.fromisoformat(d['ts'].replace('Z', '+00:00'))
        for it in d['items']:
            v = num(it.get('hvec'))
            if v is None: continue
            series[it['hpid']].append((ts, v))
print('hospitals with series', len(series), 'polls', max(len(v) for v in series.values()), 'error polls', len(errs), errs[:2], '...', errs[-2:])

W = timedelta(hours=6)
rows = []
for hp, s in series.items():
    s.sort()
    ts = [t for t, _ in s]; v = [x for _, x in s]
    adm = [0] + [max(0, v[i-1] - v[i]) if (ts[i]-ts[i-1]) <= timedelta(minutes=45) else 0 for i in range(1, len(v))]   # 감소량 = 수용, 45분 넘는 공백은 안 셈
    adm = np.array(adm); t = np.array([x.timestamp() for x in ts])
    # 각 시점의 지난 6시간 수용 건수
    roll = []
    j = 0
    cum = np.cumsum(adm)
    for i in range(len(t)):
        while t[j] < t[i] - W.total_seconds(): j += 1
        roll.append(cum[i] - (cum[j-1] if j > 0 else 0))
    roll = np.array(roll)
    valid = t >= t[0] + W.total_seconds()
    if valid.sum() < 6: continue
    r = roll[valid]
    h = hosp.get(hp, {}); cap = h.get('er_cap') or None; e = em.get(hp)
    night = np.array([(datetime.fromtimestamp(x) + timedelta(hours=9)).hour for x in t[valid]])
    nmask = (night >= 22) | (night < 6)
    rows.append(dict(hpid=hp, name=h.get('name', hp), grade=h.get('grade', '?'), cap=cap, em=e,
                     mean=r.mean(), p90=np.percentile(r, 90), mx=r.max(), day=r[~nmask].mean() if (~nmask).any() else math.nan,
                     night=r[nmask].mean() if nmask.any() else math.nan, total=adm.sum(), hours=(t[-1]-t[0])/3600))
print('hospitals analysed', len(rows))
R = sorted(rows, key=lambda x: -x['mean'])
def q(a, p): return float(np.nanpercentile(a, p))
mean = np.array([x['mean'] for x in R]); p90 = np.array([x['p90'] for x in R]); mx = np.array([x['mx'] for x in R])
print('\n[6시간 수용 건수, 병원 분포] 평균의 분위: p10 %.1f  p50 %.1f  p90 %.1f  max %.1f' % (q(mean,10), q(mean,50), q(mean,90), mean.max()))
print('                           p90의 분위: p10 %.1f  p50 %.1f  p90 %.1f  max %.1f' % (q(p90,10), q(p90,50), q(p90,90), p90.max()))
ratio = p90 / np.maximum(mean, 0.5)
print('같은 병원 안 변동(p90/평균): p10 %.2f  p50 %.2f  p90 %.2f' % (q(ratio,10), q(ratio,50), q(ratio,90)))
withem = [x for x in R if x['em']]
per = np.array([x['mean'] / x['em'] for x in withem]); perp90 = np.array([x['p90'] / x['em'] for x in withem])
print('\n[6시간 수용 ÷ 응급의학 전문의 수] 전문의 수 있는 병원 %d곳' % len(withem))
print('  평균 기준: p10 %.2f  p50 %.2f  p90 %.2f  max %.2f' % (q(per,10), q(per,50), q(per,90), per.max()))
print('  p90 기준: p10 %.2f  p50 %.2f  p90 %.2f  max %.2f' % (q(perp90,10), q(perp90,50), q(perp90,90), perp90.max()))
for g in ['권역응급의료센터', '지역응급의료센터', '지역응급의료기관']:
    gg = [x for x in withem if x['grade'] == g]
    if gg: print('  %s %d곳: 평균 %.2f, p90 %.2f, 전문의 중앙값 %d' % (g, len(gg), np.median([x['mean']/x['em'] for x in gg]), np.median([x['p90']/x['em'] for x in gg]), np.median([x['em'] for x in gg])))
dn = [(x['night'] / x['day']) for x in R if x['day'] and x['day'] > 1 and not math.isnan(x['night'])]
print('\n야간(22~06)/주간 6시간 수용 비율: p10 %.2f  p50 %.2f  p90 %.2f  (n=%d)' % (q(dn,10), q(dn,50), q(dn,90), len(dn)))
print('\n[부하 상위 15 — 6시간 수용 평균 ÷ 전문의]')
for x in sorted(withem, key=lambda x: -x['mean']/x['em'])[:15]:
    print('  %5.2f/인  평균 %5.1f  p90 %5.1f  최대 %3d  전문의 %2d  정원 %3s  %s  %s' % (x['mean']/x['em'], x['mean'], x['p90'], x['mx'], x['em'], x['cap'], x['grade'][:4], x['name'][:18]))
print('\n[부하 상위 15 — 6시간 수용 건수 절대값]')
for x in R[:15]:
    print('  평균 %5.1f  p90 %5.1f  최대 %3d  전문의 %3s  정원 %3s  %s  %s' % (x['mean'], x['p90'], x['mx'], x['em'], x['cap'], x['grade'][:4], x['name'][:18]))
json.dump(R, open(pathlib.Path(__file__).parent/'fatigue_probe.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
