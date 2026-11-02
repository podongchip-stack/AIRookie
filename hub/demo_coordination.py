"""실제 GPS/서버 없이: python hub/demo_coordination.py"""
from collections import Counter
from types import SimpleNamespace as NS
from first_call import Coordinator, rank

rows=[dict(hospitalId=h,name=h,emergencyLevel="지역응급의료기관",travelMin=t,distanceKm=t/3) for h,t in [("병원A",5),("병원B",5.5),("병원C",6)]]
c=Coordinator(); ids={f"사건{i}" for i in range(6)}; results=[]; assigned=[]
for i in range(6):
    cid=f"사건{i}"
    loads=c.pressure(cid,ids,[],results,i)
    pick=rank(rows,[],loads)[0][0]
    c.remember(cid,pick['hospitalId'],i)
    assigned.append(pick['hospitalId'])
    results.append(NS(caseId=cid,hospitals=[NS(hospitalId=pick['hospitalId'],status="confirmed")]))
    print(cid, '→', pick['hospitalId'], pick['firstCallReason'])
print('거리만 고려:', {'병원A':6})
print('사건 조정 적용:', dict(Counter(assigned)))
assert max(Counter(assigned).values()) < 6
