import json, sys, pathlib
src = sys.argv[2] if len(sys.argv) > 2 else str(pathlib.Path(__file__).resolve().parent.parent / 'info/Hospital_inform/info/data/snapshots_nationwide/2026-10-10.jsonl')
last = {}
for line in open(src, encoding='utf-8'):
    d = json.loads(line); last[d['operation']] = d
lst = {i['hpid']: i for i in last['getEgytListInfoInqire']['items']}
bed = {i['hpid']: i for i in last['getEmrrmRltmUsefulSckbdInfoInqire']['items']}
sev = {i['hpid']: i for i in last['getSrsillDissAceptncPosblInfoInqire']['items']}
GRADE = {'권역응급의료센터': 4, '지역응급의료센터': 3, '지역응급의료기관': 2, '응급실운영신고기관': 1}
def num(v):
    try: return int(v)
    except: return None
rows = []
for hpid, L in lst.items():
    pass  # 전국 전체 (서울만 보려면 hpid.startswith('A11'))
    B = bed.get(hpid, {}); S = sev.get(hpid, {})
    grade_name = L.get('dutyEmclsName', '')
    g = GRADE.get(grade_name, 1)
    ys = sum(1 for k in range(1, 29) if S.get(f'MKioskTy{k}') == 'Y')
    nos = sum(1 for k in range(1, 29) if S.get(f'MKioskTy{k}') == '불가능')
    hvec = num(B.get('hvec')); 
    rows.append(dict(
        hpid=hpid, name=L['dutyName'], lat=float(L['wgs84Lat']), lng=float(L['wgs84Lon']),
        grade=grade_name or '(등급 없음)', g=g, severeY=ys, severeNo=nos,
        z=round(g + ys/28, 2),
        hvec=hvec, er_cap=num(B.get('hvs01')), icu=num(B.get('hvicc')), op=num(B.get('hvoc')),
        ct=B.get('hvctayn'), angio=B.get('hvangioayn'), hasBeds=bool(B), hasSevere=bool(S),
        hvidate=B.get('hvidate'),
    ))
rows.sort(key=lambda r: -r['z'])
json.dump(rows, open(sys.argv[1], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
from collections import Counter
print('total', len(rows), 'with beds', sum(r['hasBeds'] for r in rows), 'with severe', sum(r['hasSevere'] for r in rows))
print(Counter(r['grade'] for r in rows))
for r in rows[:8]+rows[-5:]:
    print(f"{r['z']:5} g{r['g']} Y{r['severeY']:2} hvec={r['hvec']!s:>4}/{r['er_cap']!s:>3} CT={r['ct']} AG={r['angio']} {r['name']}")
