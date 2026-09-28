#!/usr/bin/env python3
"""1절 — 저신뢰(conf<0.5) 인스턴스를 조각에 대응시킨다 (open3d 전용).

"놓침 0"은 고신뢰 기준이라, 고신뢰로 검출된 적 없는 인물은 원리상 안 잡힌다.
저신뢰까지 내려가 배경 인물이 어느 조각에 있는지 본다.
"""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d
S=Path(sys.argv[1]); TAG=S.name.split("_")[1]; COVER=0.30
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
DW,DH=meta["depth_width"],meta["depth_height"]
sx,sy=DW/meta["video_frame_width"],DH/meta["video_frame_height"]
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
near={int(k):v for k,v in json.load(open(S/"diag_nearest_map.json")).items()}
zi=np.load(S/"diag_inst_nearest.npz"); Z=np.load(f"/tmp/pieces_{TAG}.npz")
Vo=np.asarray(o3d.io.read_triangle_mesh(str(S/"fused_objects.ply")).vertices)
def q2R(a,b,c,d):
    return np.array([[1-2*(b*b+c*c),2*(a*b-c*d),2*(a*c+b*d)],
                     [2*(a*b+c*d),1-2*(a*a+c*c),2*(b*c-a*d)],
                     [2*(a*c-b*d),2*(b*c+a*d),1-2*(a*a+b*b)]])
_c={}
def cam(i):
    if i in _c: return _c[i]
    p=poses[rows[i]["timestamp"]]
    R=q2R(*[float(p[x]) for x in ("qx","qy","qz","qw")])
    t=np.array([float(p[x]) for x in ("tx","ty","tz")])
    Rc=np.diag([1.,-1.,-1.])@R.T; tc=-Rc@t
    K=(float(p["fx"])*sx,float(p["fy"])*sy,float(p["cx"])*sx,float(p["cy"])*sy)
    q=Vo@Rc.T+tc; f=q[:,2]>0.2
    u=K[0]*q[f,0]/q[f,2]+K[2]; v=K[1]*q[f,1]/q[f,2]+K[3]
    s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
    zb=np.full((DH,DW),np.inf,np.float32)
    if s.any(): np.minimum.at(zb,(v[s].astype(int),u[s].astype(int)),q[f,2][s])
    _c[i]=(Rc,tc,K,zb); return _c[i]
def foot(V,i):
    Rc,tc,K,zb=cam(i)
    q=V@Rc.T+tc; f=q[:,2]>0.2
    if not f.any(): return None
    u=K[0]*q[f,0]/q[f,2]+K[2]; v=K[1]*q[f,1]/q[f,2]+K[3]; z=q[f,2]
    s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
    if not s.any(): return None
    u=u[s].astype(int); v=v[s].astype(int); z=z[s]
    vis=z<=zb[v,u]+0.02
    if vis.sum()<30: return None
    raw=np.zeros((DH,DW),bool); raw[v[vis],u[vis]]=True
    d=raw.copy()
    for dy in(-1,0,1):
        for dx in(-1,0,1): d|=np.roll(np.roll(raw,dy,0),dx,1)
    return d
def dedup(I):
    I=sorted(I,key=lambda x:-x[1].sum()); out=[]
    for k,m,c in I:
        if any((m&m2).sum()/max(m.sum(),1)>=0.7 for _,m2,_ in out): continue
        out.append((k,m,c))
    return out
names=sorted(Z.files); acc={n:[] for n in names}; orphan=[]
nlo=0
for i in sorted(near):
    fi=near[i]
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    lo=dedup([(k,zi[f"{fi}_{k}"],float(zi[f"{fi}_{k}_conf"][0])) for k in range(n)
              if float(zi[f"{fi}_{k}_conf"][0])<0.5])
    if not lo: continue
    fps={nm:foot(Z[nm],i) for nm in names}
    for k,m,c in lo:
        nlo+=1
        hit=[nm for nm in names if fps[nm] is not None
             and (m&fps[nm]).sum()/max(m.sum(),1)>=COVER]
        for nm in hit: acc[nm].append((fi,k,c))
        if not hit: orphan.append((fi,k,c))
print(f"===== {TAG} 저신뢰 인스턴스 {nlo}개 (중복 병합 후) =====")
print(f"  {'조각':>6}{'덮는 저신뢰':>12}{'conf 중앙':>10}{'conf 최대':>10}{'프레임 범위':>18}")
for nm in names:
    L=acc[nm]
    if not L: print(f"  {nm:>6}{0:>12}"); continue
    cs=np.array([c for _,_,c in L]); fs=np.array([f for f,_,_ in L])
    print(f"  {nm:>6}{len(L):>12}{np.median(cs):>10.2f}{cs.max():>10.2f}"
          f"{f'f{fs.min()}~f{fs.max()}':>18}")
print(f"\n  어느 조각도 안 덮는 저신뢰 인스턴스: {len(orphan)}개")
if orphan:
    o=sorted(orphan,key=lambda x:-x[2])[:10]
    print("   " + ", ".join(f"f{f}#{k} {c:.2f}" for f,k,c in o))
json.dump({n:[[int(f),int(k),float(c)] for f,k,c in acc[n]] for n in names},
          open(f"/tmp/lowconf_{TAG}.json","w"))
