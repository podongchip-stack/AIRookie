#!/usr/bin/env python3
"""B. 마스크 일관성 — 매트 혼입 원인 규명 (open3d 전용).

가설: TSDF는 마스크 경계가 매트를 덮은 프레임이 **몇 개만 있어도** 표면을 만든다.
      사람 몸은 거의 모든 프레임에서 마스크 안에 들지만,
      매트는 일부 프레임에서만 우연히 들어간다.

측정: 조각의 각 정점에 대해
        (마스크 안에 든 프레임 수) / (그 정점이 보이는 프레임 수)
      가림(z-buffer) 처리를 해서 **실제로 보이는** 프레임만 센다.
"""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d

S=Path(sys.argv[1]); FLOOR=-0.71
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
DW,DH=meta["depth_width"],meta["depth_height"]; VW,VH=meta["video_frame_width"],meta["video_frame_height"]
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
near={int(k):v for k,v in json.load(open(S/"diag_nearest_map.json")).items()}
zm=np.load(S/"diag_masks_nearest.npz")

mob=o3d.io.read_triangle_mesh(str(S/"fused_objects.ply"))
with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
    ci,_,ca=mob.cluster_connected_triangles()
ci=np.asarray(ci);ca=np.asarray(ca);Vo=np.asarray(mob.vertices);To=np.asarray(mob.triangles)
k3=int(np.argsort(-ca)[0]); tri=np.where(ci==k3)[0]
vi=np.unique(To[tri]); P=Vo[vi]
print(f"대상 조각 {k3}: {ca[k3]:.2f}㎡  정점 {len(P):,}\n")

def q2R(a,b,c,d):
    return np.array([[1-2*(b*b+c*c),2*(a*b-c*d),2*(a*c+b*d)],
                     [2*(a*b+c*d),1-2*(a*a+c*c),2*(b*c-a*d)],
                     [2*(a*c-b*d),2*(b*c+a*d),1-2*(a*a+b*b)]])

seen=np.zeros(len(P),np.int32); inmask=np.zeros(len(P),np.int32)
nf=0
for i,r in enumerate(rows):
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2" or i not in near: continue
    fi=near[i]
    if str(fi) not in zm.files: continue
    m=zm[str(fi)]
    R=q2R(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")])
    Rc=np.diag([1.,-1.,-1.])@R.T; tc=-Rc@t
    fx=float(p["fx"])*DW/VW; fy=float(p["fy"])*DH/VH
    cx=float(p["cx"])*DW/VW; cy=float(p["cy"])*DH/VH
    # 전체 메시로 z-버퍼를 만든다 (가림 판정용)
    pcA=Vo@Rc.T+tc; mA=pcA[:,2]>0.2
    uA=fx*pcA[mA,0]/pcA[mA,2]+cx; vA=fy*pcA[mA,1]/pcA[mA,2]+cy; zA=pcA[mA,2]
    sA=(uA>=0)&(uA<DW)&(vA>=0)&(vA<DH)
    zb=np.full((DH,DW),np.inf,np.float32)
    np.minimum.at(zb,(vA[sA].astype(int),uA[sA].astype(int)),zA[sA])
    # 대상 정점 투영
    pc=P@Rc.T+tc; mm=pc[:,2]>0.2
    idx=np.nonzero(mm)[0]
    u=fx*pc[mm,0]/pc[mm,2]+cx; v=fy*pc[mm,1]/pc[mm,2]+cy; z=pc[mm,2]
    s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
    idx=idx[s]; uu=u[s].astype(int); vv=v[s].astype(int); zz=z[s]
    vis=zz<=zb[vv,uu]+0.02          # 2cm 여유 — 자기 자신이 최전면이면 보이는 것
    idx=idx[vis]; uu=uu[vis]; vv=vv[vis]
    seen[idx]+=1
    inmask[idx]+=m[vv,uu]
    nf+=1
print(f"검사 프레임 {nf}개")
ok=seen>=5
ratio=np.where(ok,inmask/np.maximum(seen,1),np.nan)
R=ratio[ok]
print(f"정점 {ok.sum():,}개 (5프레임 이상 보임) / 전체 {len(P):,}\n")
print("="*66); print("B-2. 마스크 포함 비율 분포"); print("="*66)
hist,edges=np.histogram(R,bins=10,range=(0,1))
for i in range(10):
    bar="█"*int(hist[i]/max(hist)*46)
    print(f"  {edges[i]:.1f}~{edges[i+1]:.1f}: {hist[i]:>7,} {bar}")
print(f"\n  중앙 {np.median(R):.3f}  평균 {R.mean():.3f}")
for t in (0.3,0.5,0.7,0.8,0.9):
    print(f"    비율<{t}: {(R<t).sum():>7,} ({(R<t).mean()*100:5.1f}%)")
np.save("/tmp/consistency.npy", np.stack([vi.astype(float),ratio]))
