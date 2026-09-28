#!/usr/bin/env python3
"""2절 — "뎁스가 있는 거리"와 "3D 형상이 생기는 거리"를 구분해 측정한다.

파이프라인 실측:
  - ARKit 신뢰도맵(conf_*.bin)은 **어느 스크립트도 읽지 않는다** (grep 0건).
  - 실제 거름망은 stage2_fuse.py의 clean(maxd=4.0) 과 depth_trunc=4.0 이다.
    · 0 이하 또는 4.0m 초과 -> 버림
    · 이웃 화소와 상대 차이 4% 초과 -> 버림 (경계 튐 제거)
"""
import sys, csv, json
from pathlib import Path
import numpy as np
def clean(d,maxd=4.0):
    d=d.copy(); d[(d<=0)|(d>maxd)]=0
    if not (d>0).any(): return d
    pad=np.pad(d,1,mode="edge")
    nb=np.stack([pad[:-2,1:-1],pad[2:,1:-1],pad[1:-1,:-2],pad[1:-1,2:]])
    with np.errstate(divide="ignore",invalid="ignore"):
        rel=np.abs(nb-d[None])/np.maximum(d[None],1e-6)
    d[np.nanmax(np.where(nb>0,rel,0),axis=0)>0.04]=0
    return d
print(f"{'세션':>5}{'표본프레임':>10}{'원본유효':>10}{'중앙':>7}{'90%':>7}{'99%':>7}{'최대':>7}"
      f"{'융합사용':>10}{'중앙':>7}{'90%':>7}{'최대':>7}{'생존율':>8}")
agg_raw=[]; agg_use=[]
for i in list(range(1,11)):
    S=Path(f"server/sessions/session_20260921v{i}_iPhone12Pro")
    m=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
    W,H=m["depth_width"],m["depth_height"]
    rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
    raw=[]; use=[]
    for r in rows[::3]:
        d=np.fromfile(S/"depth"/r["depth_file"],dtype="<f4").reshape(H,W)
        v=d[(d>0)&(d<20)]
        if len(v): raw.append(v)
        c=clean(d); u=c[c>0]
        if len(u): use.append(u)
    if not raw: continue
    R=np.concatenate(raw); U=np.concatenate(use) if use else np.array([0.])
    agg_raw.append(R); agg_use.append(U)
    print(f"{'v'+str(i):>5}{len(rows[::3]):>10}{len(R):>10,}{np.median(R):>7.2f}"
          f"{np.quantile(R,.9):>7.2f}{np.quantile(R,.99):>7.2f}{R.max():>7.2f}"
          f"{len(U):>10,}{np.median(U):>7.2f}{np.quantile(U,.9):>7.2f}{U.max():>7.2f}"
          f"{len(U)/len(R)*100:>7.1f}%")
R=np.concatenate(agg_raw); U=np.concatenate(agg_use)
print(f"\n=== 새 10세션 전체 ===")
print(f"(a) 뎁스 값이 존재하는 거리  : 화소 {len(R):,}  중앙 {np.median(R):.2f}m  "
      f"90% {np.quantile(R,.9):.2f}m  99% {np.quantile(R,.99):.2f}m  최대 {R.max():.2f}m")
print(f"(b) 융합에 실제 쓰인 거리    : 화소 {len(U):,}  중앙 {np.median(U):.2f}m  "
      f"90% {np.quantile(U,.9):.2f}m  99% {np.quantile(U,.99):.2f}m  최대 {U.max():.2f}m")
print(f"    → 생존율 {len(U)/len(R)*100:.1f}%")
print(f"\n거리 구간별 (원본 -> 융합 사용)")
for lo,hi in [(0,1),(1,2),(2,2.5),(2.5,3),(3,3.5),(3.5,4),(4,5),(5,20)]:
    a=((R>=lo)&(R<hi)).sum(); b=((U>=lo)&(U<hi)).sum()
    print(f"  {lo:>4.1f}~{hi:<4.1f}m  원본 {a:>10,} ({a/len(R)*100:5.2f}%)   "
          f"융합 {b:>10,} ({b/len(U)*100:5.2f}%)   생존 {b/max(a,1)*100:5.1f}%")
for t in (2.5,3.0,4.0):
    print(f"  {t}m 이내가 융합 사용 화소의 {(U<=t).mean()*100:.1f}%")
