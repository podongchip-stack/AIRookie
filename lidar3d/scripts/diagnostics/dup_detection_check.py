#!/usr/bin/env python3
"""A. 같은 프레임 내 중복 검출 가설 검증 (진단 전용).

가설: cannot-link 실패의 원인은 움직임이 아니라 **같은 사람의 중복 검출**이다.
      신뢰도 하한 0.15라 저신뢰 부분 검출이 통과하고,
      cannot-link가 그것을 "다른 사람"으로 강제해 3D 조각을 찢었다.
"""
import sys, json
from pathlib import Path
import numpy as np

S=Path(sys.argv[1])
zi=np.load(S/"diag_inst_nearest.npz")
frames=sorted({int(k.split("_")[0]) for k in zi.files})
def get(fi):
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    return [(zi[f"{fi}_{k}"], float(zi[f"{fi}_{k}_conf"][0])) for k in range(n)]

# ── A-1. 같은 프레임 인스턴스 쌍의 2D IoU 분포 ──────────────────
pairs=[]
for fi in frames:
    I=get(fi)
    for a in range(len(I)):
        for b in range(a+1,len(I)):
            ma,ca=I[a]; mb,cb=I[b]
            inter=(ma&mb).sum(); uni=(ma|mb).sum()
            if uni==0: continue
            iou=inter/uni
            # 포함 관계도 본다 — 작은 쪽이 큰 쪽에 거의 들어가면 중복이다
            cont=inter/min(ma.sum(),mb.sum())
            pairs.append((fi,a,b,iou,cont,ca,cb,int(ma.sum()),int(mb.sum())))
P=np.array([[p[3],p[4],p[5],p[6]] for p in pairs])
print("="*70); print("A-1. 같은 프레임 인스턴스 쌍의 2D 겹침"); print("="*70)
print(f"  쌍 {len(pairs)}개 (프레임 {len(frames)}개)")
if len(P):
    print(f"  IoU        : 중앙 {np.median(P[:,0]):.3f}  75% {np.percentile(P[:,0],75):.3f}  "
          f"90% {np.percentile(P[:,0],90):.3f}  최대 {P[:,0].max():.3f}")
    print(f"  포함비율    : 중앙 {np.median(P[:,1]):.3f}  75% {np.percentile(P[:,1],75):.3f}  "
          f"90% {np.percentile(P[:,1],90):.3f}  최대 {P[:,1].max():.3f}")
    print()
    for t in (0.1,0.2,0.3,0.5):
        print(f"    IoU>{t:.1f} 인 쌍: {(P[:,0]>t).sum():5d} ({(P[:,0]>t).mean()*100:5.1f}%)")
    for t in (0.5,0.7,0.9):
        print(f"    포함비율>{t:.1f} 인 쌍: {(P[:,1]>t).sum():5d} ({(P[:,1]>t).mean()*100:5.1f}%)")

# ── A-2. 프레임 398 인스턴스1 ↔ 3 ───────────────────────────────
print(); print("="*70); print("A-2. 프레임 398 — 인스턴스1 ↔ 인스턴스3"); print("="*70)
I=get(398)
print(f"  인스턴스 {len(I)}개, 신뢰도 {[f'{c:.2f}' for _,c in I]}")
for a in range(len(I)):
    for b in range(a+1,len(I)):
        ma,ca=I[a]; mb,cb=I[b]
        inter=(ma&mb).sum(); uni=(ma|mb).sum()
        if uni==0: continue
        print(f"    {a}↔{b}: IoU {inter/uni:.3f}  포함비율 {inter/min(ma.sum(),mb.sum()):.3f}  "
              f"화소 {ma.sum():>6}/{mb.sum():>6}  conf {ca:.2f}/{cb:.2f}")

# ── A-3. 신뢰도와 겹침의 관계 ───────────────────────────────────
print(); print("="*70); print("A-3. 겹치는 쌍은 한쪽이 저신뢰인가"); print("="*70)
if len(P):
    hi=P[P[:,0]>0.2]; lo=P[P[:,0]<=0.05]
    for name,G in (("IoU>0.2 (중복 의심)",hi),("IoU≤0.05 (별개)",lo)):
        if not len(G): continue
        mn=np.minimum(G[:,2],G[:,3]); mx=np.maximum(G[:,2],G[:,3])
        print(f"  {name:<22} 쌍 {len(G):4d} | 낮은쪽 conf 중앙 {np.median(mn):.2f}  "
              f"높은쪽 중앙 {np.median(mx):.2f} | 낮은쪽<0.3 비율 {(mn<0.3).mean()*100:5.1f}%")

# ── A-4. 인스턴스 수 분포 ───────────────────────────────────────
print(); print("="*70); print("A-4. 프레임당 인스턴스 수 (정답: 매트 위 3명)"); print("="*70)
cnt=np.array([len(get(f)) for f in frames])
u,c=np.unique(cnt,return_counts=True)
print("  " + "  ".join(f"{a}개:{b}" for a,b in zip(u,c)))
print(f"  3 초과인 프레임: {(cnt>3).sum()} / {len(cnt)} ({(cnt>3).mean()*100:.1f}%)")
# 저신뢰를 빼면?
for th in (0.3,0.5):
    c2=np.array([sum(1 for _,cf in get(f) if cf>=th) for f in frames])
    print(f"  신뢰도 {th} 이상만: 3 초과 프레임 {(c2>3).sum()} ({(c2>3).mean()*100:.1f}%), "
          f"중앙 인스턴스 수 {np.median(c2):.0f}")
