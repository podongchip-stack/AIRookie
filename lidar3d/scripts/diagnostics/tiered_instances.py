#!/usr/bin/env python3
"""A. 신뢰도 3계층 분류 (진단 전용, numpy만 — torch/open3d 없음).

  계층1  conf>=0.5                      → 군집 뼈대 (cannot-link 적용)
  계층2  conf<0.5 & 고신뢰에 포함>=0.7   → 같은 사람의 중복. 제거
  계층3  conf<0.5 & 어디에도 안 포함     → **버리지 않는다.** 불확실한 사람 후보

계층3을 버리면 멀리 있거나 어두운 곳의 부상자가 통째로 사라진다.
실패 비용이 비대칭이므로(놓치는 쪽이 훨씬 나쁘다) 남겨서 사람이 확인하게 한다.
"""
import sys, json
from pathlib import Path
import numpy as np

S=Path(sys.argv[1]); CONF=0.5; CONTAIN=0.7
zi=np.load(S/"diag_inst_nearest.npz")
frames=sorted({int(k.split("_")[0]) for k in zi.files})

def tiers(fi):
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    I=[(zi[f"{fi}_{k}"], float(zi[f"{fi}_{k}_conf"][0]), k) for k in range(n)]
    hi=[x for x in I if x[1]>=CONF]
    t1,t2,t3=[],[],[]
    for m,c,k in I:
        if c>=CONF: t1.append((m,c,k)); continue
        dup=False
        for hm,_,_ in hi:
            inter=(m&hm).sum()
            if inter and inter/m.sum()>=CONTAIN: dup=True; break
        (t2 if dup else t3).append((m,c,k))
    return t1,t2,t3

n1=n2=n3=0; t3list=[]
for fi in frames:
    a,b,c=tiers(fi)
    n1+=len(a); n2+=len(b); n3+=len(c)
    for m,cf,k in c: t3list.append((fi,k,cf,int(m.sum())))
tot=n1+n2+n3
print("="*66); print(f"A. 신뢰도 3계층 (conf>={CONF}, 포함>={CONTAIN})"); print("="*66)
print(f"  전체 인스턴스 {tot}개")
print(f"    계층1 뼈대(conf>={CONF})        : {n1:5d} ({n1/tot*100:5.1f}%)")
print(f"    계층2 중복으로 제거             : {n2:5d} ({n2/tot*100:5.1f}%)")
print(f"    계층3 불확실(버리지 않음)       : {n3:5d} ({n3/tot*100:5.1f}%)")
print()
if t3list:
    A=np.array([[x[2],x[3]] for x in t3list])
    print(f"  계층3 신뢰도: 중앙 {np.median(A[:,0]):.2f}  범위 {A[:,0].min():.2f}~{A[:,0].max():.2f}")
    print(f"  계층3 마스크 크기(화소): 중앙 {np.median(A[:,1]):.0f}  "
          f"최대 {A[:,1].max():.0f}  (계층1 중앙 대비 참고)")
    B=[]
    for fi in frames:
        a,_,_=tiers(fi)
        for m,c,k in a: B.append(m.sum())
    if B: print(f"  계층1 마스크 크기 중앙: {np.median(B):.0f}")
    print()
    big=[x for x in t3list if x[3]>=1000]
    print(f"  계층3 중 마스크 1000화소 이상: {len(big)}개")
    json.dump([[int(x[0]),int(x[1]),float(x[2]),int(x[3])] for x in big[:40]],
              open("/tmp/tier3_big.json","w"))
    for fi,k,cf,sz in sorted(big,key=lambda x:-x[3])[:10]:
        print(f"    프레임{fi:>4} 인스턴스{k} conf {cf:.2f}  {sz:>6}화소")
