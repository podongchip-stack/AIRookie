#!/usr/bin/env python3
"""1절 — 군집 쪼개짐이 시점 이동 때문인지 확인 (open3d 전용).

인스턴스 중심점은 "보이는 표면의 중심"이라 카메라가 돌면 같은 사람이어도 이동한다.
그것이 v1에서 한 사람이 3군집으로 쪼개진 원인인지 본다.
"""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d
S=Path(sys.argv[1]); TAG=S.name.split("_")[1]; CONF=0.5; PIECE=sys.argv[2]
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
DW,DH=meta["depth_width"],meta["depth_height"]
sx,sy=DW/meta["video_frame_width"],DH/meta["video_frame_height"]
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
near={int(k):v for k,v in json.load(open(S/"diag_nearest_map.json")).items()}
zi=np.load(S/"diag_inst_nearest.npz"); Z=np.load(f"/tmp/pieces_{TAG}.npz")
i2p=json.load(open(f"/tmp/inst2piece_{TAG}.json"))
def q2R(a,b,c,d):
    return np.array([[1-2*(b*b+c*c),2*(a*b-c*d),2*(a*c+b*d)],
                     [2*(a*b+c*d),1-2*(a*a+c*c),2*(b*c-a*d)],
                     [2*(a*c-b*d),2*(b*c+a*d),1-2*(a*a+b*b)]])
def clean(x,mx=4.0,er=0.04):
    x=x.copy(); x[(x<=0)|(x>mx)]=0
    pad=np.pad(x,1,constant_values=0)
    nb=np.stack([pad[:-2,1:-1],pad[2:,1:-1],pad[1:-1,:-2],pad[1:-1,2:]])
    with np.errstate(divide="ignore",invalid="ignore"):
        rel=np.abs(nb-x[None])/np.maximum(x[None],1e-6)
    x[np.nanmax(np.where(nb>0,rel,0),axis=0)>er]=0
    return x
PV=Z[PIECE]; pc=PV.mean(0)
print(f"{TAG} 조각 {PIECE}: 정점 {len(PV):,}  정점 전체 중심 ({pc[0]:.2f},{pc[1]:.2f},{pc[2]:.2f})")
obs=[]
for i,r in enumerate(rows):
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2" or i not in near: continue
    fi=near[i]
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    ks=[k for k in range(n) if float(zi[f"{fi}_{k}_conf"][0])>=CONF
        and PIECE in (i2p.get(f"{fi}_{k}",[0,[]])[1])]
    if not ks: continue
    d=clean(np.fromfile(S/"depth"/r["depth_file"],dtype="<f4").reshape(DH,DW))
    R=q2R(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")]); T=R@np.diag([1.,-1.,-1.])
    fx,fy=float(p["fx"])*sx,float(p["fy"])*sy; cx,cy=float(p["cx"])*sx,float(p["cy"])*sy
    for k in ks:
        m=zi[f"{fi}_{k}"]
        vv,uu=np.nonzero(m&(d>0.2)&(d<4.0))
        if len(vv)<120: continue
        zz=d[vv,uu]; med=np.median(zz); s=np.abs(zz-med)<0.6
        if s.sum()<120: continue
        vv,uu,zz=vv[s],uu[s],zz[s]
        X=(uu-cx)/fx*zz; Y=(vv-cy)/fy*zz
        P=np.stack([X,Y,zz],1)@T.T+t
        obs.append((fi,P.mean(0),t))
print(f"이 조각을 덮는 고신뢰 관측 {len(obs)}개\n")
C=np.array([o[1] for o in obs]); CAM=np.array([o[2] for o in obs]); FI=np.array([o[0] for o in obs])
# 1-1. 시점각(조각 중심 기준 방위각) vs 관측 중심점
d=CAM-pc; az=np.degrees(np.arctan2(d[:,2],d[:,0]))
print("1-1. 카메라 방위각 구간별 관측 중심점")
print(f"  {'방위각':>12}{'관측':>6}{'중심점 평균 (x,y,z)':>28}{'조각중심과 거리':>14}")
bins=np.arange(-180,181,45); ref=None
for b0,b1 in zip(bins[:-1],bins[1:]):
    s=(az>=b0)&(az<b1)
    if s.sum()<5: continue
    mu=C[s].mean(0); dist=np.linalg.norm(mu-pc)
    print(f"  {b0:>5}~{b1:<5}{s.sum():>6}   ({mu[0]:5.2f},{mu[1]:5.2f},{mu[2]:5.2f}){dist:>13.2f}m")
rng=[]
for b0,b1 in zip(bins[:-1],bins[1:]):
    s=(az>=b0)&(az<b1)
    if s.sum()>=5: rng.append(C[s].mean(0))
if len(rng)>=2:
    R2=np.array(rng); span=R2.max(0)-R2.min(0)
    print(f"  → 시점 구간 평균들의 흩어짐: {span[0]:.2f} x {span[1]:.2f} x {span[2]:.2f} m "
          f"(최대 쌍 거리 {max(np.linalg.norm(a-b) for a in R2 for b in R2):.2f}m)")
# 시간 구간별 (실제 움직임)
print("\n  시간(프레임) 구간별 관측 중심점")
q=np.quantile(FI,[0,.25,.5,.75,1.0])
tmu=[]
for a,b in zip(q[:-1],q[1:]):
    s=(FI>=a)&(FI<=b)
    if s.sum()<5: continue
    mu=C[s].mean(0); tmu.append(mu)
    print(f"  f{int(a):>4}~{int(b):<5}{s.sum():>6}   ({mu[0]:5.2f},{mu[1]:5.2f},{mu[2]:5.2f})")
if len(tmu)>=2:
    T2=np.array(tmu); span=T2.max(0)-T2.min(0)
    print(f"  → 시간 구간 평균들의 흩어짐: {span[0]:.2f} x {span[1]:.2f} x {span[2]:.2f} m "
          f"(최대 쌍 거리 {max(np.linalg.norm(a-b) for a in T2 for b in T2):.2f}m)")
# 1-2. 정점 전체 중심과 관측 중심점 거리
dd=np.linalg.norm(C-pc,axis=1)
print(f"\n1-2. 조각 정점중심 ↔ 관측 중심점 거리")
print(f"  중앙 {np.median(dd):.2f}m  평균 {dd.mean():.2f}m  최소 {dd.min():.2f}m  최대 {dd.max():.2f}m")
print(f"  반경 0.374m 이내 {(dd<=0.374).mean()*100:.1f}%")
print(f"  관측 중심점들끼리의 최대 거리 {max(np.linalg.norm(a-b) for a in C[::5] for b in C[::5]):.2f}m")

# 시점과 시간은 섞여 있다(카메라가 시간에 따라 돈다). 시간 구간을 고정하고
# 그 안에서 시점만 달라질 때 중심점이 얼마나 움직이는지 본다.
print("\n1-1b. 시간 구간을 고정한 뒤 시점만 바꿨을 때의 이동")
for a,b in zip(q[:-1],q[1:]):
    sel=(FI>=a)&(FI<=b)
    if sel.sum()<20: continue
    aa=az[sel]; CC=C[sel]
    mus=[]
    for b0,b1 in zip(bins[:-1],bins[1:]):
        s2=(aa>=b0)&(aa<b1)
        if s2.sum()>=5: mus.append(CC[s2].mean(0))
    if len(mus)<2:
        print(f"  f{int(a):>4}~{int(b):<5} 시점 구간이 {len(mus)}개뿐 — 비교 불가"); continue
    M=np.array(mus)
    print(f"  f{int(a):>4}~{int(b):<5} 시점구간 {len(mus)}개  "
          f"최대 쌍 거리 {max(np.linalg.norm(x-y) for x in M for y in M):.2f}m")
