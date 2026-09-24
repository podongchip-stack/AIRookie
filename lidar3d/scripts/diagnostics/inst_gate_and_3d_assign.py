#!/usr/bin/env python3
"""B-3 (인스턴스 게이트가 개선하는 부분) + C (3D 월드 좌표 기반 사람 배정).

open3d 전용 프로세스.
"""
import sys, csv, json
from pathlib import Path
import numpy as np, cv2, open3d as o3d

S=Path(sys.argv[1]); FLOOR=-0.71
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
W,H=meta["depth_width"],meta["depth_height"]; VW,VH=meta["video_frame_width"],meta["video_frame_height"]
sx,sy=W/VW,H/VH
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
near={int(k):v for k,v in json.load(open(S/"diag_nearest_map.json")).items()}
zi=np.load(S/"diag_inst_nearest.npz")
def R_(qx,qy,qz,qw):
    return np.array([[1-2*(qy*qy+qz*qz),2*(qx*qy-qz*qw),2*(qx*qz+qy*qw)],
                     [2*(qx*qy+qz*qw),1-2*(qx*qx+qz*qz),2*(qy*qz-qx*qw)],
                     [2*(qx*qz-qy*qw),2*(qy*qz+qx*qw),1-2*(qx*qx+qy*qy)]])
def clean(d,mx=4.0,er=0.04):
    d=d.copy(); d[(d<=0)|(d>mx)]=0
    pad=np.pad(d,1,constant_values=0)
    nb=np.stack([pad[:-2,1:-1],pad[2:,1:-1],pad[1:-1,:-2],pad[1:-1,2:]])
    with np.errstate(divide="ignore",invalid="ignore"):
        rel=np.abs(nb-d[None])/np.maximum(d[None],1e-6)
    d[np.nanmax(np.where(nb>0,rel,0),axis=0)>er]=0
    return d
def insts(fi):
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    return [zi[f"{fi}_{k}"] for k in range(n)]

# ── B-3. 2D에서 사람이 겹친 프레임에서 잘려나간 픽셀 비교 ─────────────
print("="*68); print("B-3. 인스턴스 게이트가 개선하는 부분"); print("="*68)
blob_cut=[]; inst_cut=[]; overlap_frames=0
for i,r in enumerate(rows):
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2" or i not in near: continue
    fi=near[i]; II=insts(fi)
    if len(II)<2: continue
    # 2D에서 실제로 인접/겹치는 경우만 (팽창 후 교집합)
    kern=np.ones((5,5),np.uint8)
    touch=False
    for a in range(len(II)):
        for b in range(a+1,len(II)):
            if (cv2.dilate(II[a].astype(np.uint8),kern)&II[b].astype(np.uint8)).any():
                touch=True; break
        if touch: break
    if not touch: continue
    overlap_frames+=1
    d=clean(np.fromfile(S/"depth"/r["depth_file"],dtype="<f4").reshape(H,W))
    m=np.zeros((H,W),bool)
    for x in II: m|=x
    base=(d>0)&m
    if base.sum()<100: continue
    # 연결 성분 게이트
    do=d.copy(); do[~m]=0
    n,lab=cv2.connectedComponents(m.astype(np.uint8))
    for li in range(1,n):
        b=(lab==li)&(do>0)
        if b.sum()<50: do[lab==li]=0; continue
        med=float(np.median(do[b])); do[(lab==li)&((do<med-0.6)|(do>med+0.6))]=0
    blob_cut.append(1-(do>0).sum()/base.sum())
    # 인스턴스 게이트
    keep=np.zeros_like(d)
    for x in II:
        b=x&(d>0)
        if b.sum()<50: continue
        med=float(np.median(d[b])); ok=b&(d>=med-0.6)&(d<=med+0.6); keep[ok]=d[ok]
    inst_cut.append(1-(keep>0).sum()/base.sum())
if blob_cut:
    B=np.array(blob_cut)*100; I=np.array(inst_cut)*100
    print(f"  2D에서 사람이 맞닿은 프레임: {overlap_frames}개")
    print(f"  잘려나간 사람 픽셀 비율")
    print(f"    연결성분 게이트 (현행) : 중앙 {np.median(B):5.1f}%  평균 {B.mean():5.1f}%  최대 {B.max():5.1f}%")
    print(f"    인스턴스 게이트        : 중앙 {np.median(I):5.1f}%  평균 {I.mean():5.1f}%  최대 {I.max():5.1f}%")
    print(f"    → 개선폭 중앙 {np.median(B)-np.median(I):+5.1f}%p")
else:
    print("  맞닿은 프레임 없음")

# ── C. 3D 월드 좌표 기반 사람 배정 ────────────────────────────────────
print(); print("="*68); print("C. 3D 월드 좌표 기반 사람 배정"); print("="*68)
cents=[]
for i,r in enumerate(rows):
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2" or i not in near: continue
    fi=near[i]; II=insts(fi)
    if not II: continue
    d=clean(np.fromfile(S/"depth"/r["depth_file"],dtype="<f4").reshape(H,W))
    R=R_(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")]); T=R@np.diag([1.,-1.,-1.])
    fx,fy=float(p["fx"])*sx,float(p["fy"])*sy; cx,cy=float(p["cx"])*sx,float(p["cy"])*sy
    for k,m in enumerate(II):
        vv,uu=np.nonzero(m&(d>0.2)&(d<4.0))
        if len(vv)<120: continue
        zz=d[vv,uu]
        # 인스턴스 안에서도 깊이 중앙값 근처만 (뒤쪽 벽 제거)
        med=np.median(zz); s=np.abs(zz-med)<0.6
        if s.sum()<120: continue
        vv,uu,zz=vv[s],uu[s],zz[s]
        X=(uu-cx)/fx*zz; Y=(vv-cy)/fy*zz
        P=np.stack([X,Y,zz],1)@T.T+t
        cents.append(P.mean(0))
C=np.array(cents)
print(f"C-1. 인스턴스 3D 중심점 {len(C)}개 수집")
# 반경 근거: 최근접 이웃 거리 분포를 보고 정한다
from scipy.spatial import cKDTree
if len(C)>1:
    dd,_=cKDTree(C).query(C,k=2)
    nn=dd[:,1]
    print(f"  최근접 이웃 거리: 중앙 {np.median(nn):.3f}m  25% {np.percentile(nn,25):.3f}  "
          f"75% {np.percentile(nn,75):.3f}  90% {np.percentile(nn,90):.3f}")
    RAD=float(np.percentile(nn,75))
    RAD=max(0.25,min(RAD,0.8))
    print(f"  → 군집 반경 {RAD:.2f}m (최근접 이웃 75분위 기준, 0.25~0.8m로 제한)")
    lbl=-np.ones(len(C),int); cur=0
    tree=cKDTree(C)
    for i in range(len(C)):
        if lbl[i]>=0: continue
        stack=[i]; lbl[i]=cur
        while stack:
            j=stack.pop()
            for k in tree.query_ball_point(C[j],RAD):
                if lbl[k]<0: lbl[k]=cur; stack.append(k)
        cur+=1
    print(f"\nC-2. 군집 {cur}개")
    print(f"  {'군집':>5}{'관측':>7}{'중심(x,y,z)':>28}{'흩어짐(std)':>22}")
    keep=[]
    for c in range(cur):
        s=C[lbl==c]
        if len(s)<8: continue
        keep.append((c,s.mean(0),s.std(0),len(s)))
        print(f"  {c:>5}{len(s):>7}   ({s.mean(0)[0]:+.2f},{s.mean(0)[1]:+.2f},{s.mean(0)[2]:+.2f})"
              f"   ({s.std(0)[0]:.2f},{s.std(0)[1]:.2f},{s.std(0)[2]:.2f})")
    print(f"  → 관측 8회 이상인 안정 군집: {len(keep)}개")
    np.save("/tmp/cluster_centers.npy", np.array([k[1] for k in keep]))
