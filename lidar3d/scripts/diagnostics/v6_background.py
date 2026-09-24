#!/usr/bin/env python3
"""1절 — v6 배경 인물의 저신뢰 검출이 어디로 떨어지는지 (open3d 전용)."""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d
from scipy.spatial import cKDTree
S=Path("server/sessions/session_20260921v6_iPhone12Pro")
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
W,H=meta["depth_width"],meta["depth_height"]
sx,sy=W/meta["video_frame_width"],H/meta["video_frame_height"]
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
mask_map={int(k):int(v) for k,v in json.load(open(S/"person_masks_map.json")).items()}
zi=np.load(S/"person_instances.npz")
def q2R(a,b,c,d):
    return np.array([[1-2*(b*b+c*c),2*(a*b-c*d),2*(a*c+b*d)],
                     [2*(a*b+c*d),1-2*(a*a+c*c),2*(b*c-a*d)],
                     [2*(a*c-b*d),2*(b*c+a*d),1-2*(a*a+b*b)]])
def clean(d,maxd=4.0):
    d=d.copy(); d[(d<=0)|(d>maxd)]=0
    if not (d>0).any(): return d
    pad=np.pad(d,1,mode="edge")
    nb=np.stack([pad[:-2,1:-1],pad[2:,1:-1],pad[1:-1,:-2],pad[1:-1,2:]])
    with np.errstate(divide="ignore",invalid="ignore"):
        rel=np.abs(nb-d[None])/np.maximum(d[None],1e-6)
    d[np.nanmax(np.where(nb>0,rel,0),axis=0)>0.04]=0
    return d
OBJ=np.asarray(o3d.io.read_triangle_mesh(str(S/"fused_objects.ply")).vertices)
ALL=np.asarray(o3d.io.read_triangle_mesh(str(S/"fused_adaptive.ply")).vertices)
P1=np.asarray(o3d.io.read_triangle_mesh(str(S/"fused_person_01.ply")).vertices)
P2=np.asarray(o3d.io.read_triangle_mesh(str(S/"fused_person_02.ply")).vertices)
tobj=cKDTree(OBJ); tall=cKDTree(ALL); t1=cKDTree(P1); t2=cKDTree(P2)
print(f"융합 정점: 전체장면 {len(ALL):,} / 객체 {len(OBJ):,} / p01 {len(P1):,} / p02 {len(P2):,}\n")
print(f"{'프레임':>7}{'인스':>5}{'conf':>6}{'마스크px':>9}{'원본뎁스':>9}{'정제후':>8}"
      f"{'거리중앙':>9}{'3D중심(x,y,z)':>24}{'p01':>7}{'p02':>7}{'객체':>7}{'전체':>7}")
n_ok=n_nodepth=0; rows_out=[]
for r in rows:
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2": continue
    fi=mask_map.get(int(r["depth_index"]))
    if fi is None or f"{fi}_n" not in zi.files: continue
    nk=int(zi[f"{fi}_n"][0])
    lo=[(k,zi[f"{fi}_{k}"],float(zi[f"{fi}_{k}_conf"][0])) for k in range(nk)
        if float(zi[f"{fi}_{k}_conf"][0])<0.5]
    if not lo: continue
    draw=np.fromfile(S/"depth"/r["depth_file"],dtype="<f4").reshape(H,W)
    d=clean(draw)
    R=q2R(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")]); T=R@np.diag([1.,-1.,-1.])
    fx,fy=float(p["fx"])*sx,float(p["fy"])*sy; cx,cy=float(p["cx"])*sx,float(p["cy"])*sy
    for k,m,c in lo:
        if m.sum()<80: continue
        raw_v=int(((draw>0)&(draw<20)&m).sum()); cl_v=int(((d>0)&m).sum())
        if cl_v<40:
            n_nodepth+=1
            rows_out.append((fi,k,c,int(m.sum()),raw_v,cl_v,
                             float(np.median(draw[m&(draw>0)])) if raw_v else -1,
                             None,None,None,None,None)); continue
        vv,uu=np.nonzero(m&(d>0))
        zz=d[vv,uu]; med=np.median(zz); s=np.abs(zz-med)<0.6
        vv,uu,zz=vv[s],uu[s],zz[s]
        X=(uu-cx)/fx*zz; Y=(vv-cy)/fy*zz
        P=np.stack([X,Y,zz],1)@T.T+t; cen=P.mean(0)
        d1=t1.query(cen[None])[0][0]; d2=t2.query(cen[None])[0][0]
        do=tobj.query(cen[None])[0][0]; da=tall.query(cen[None])[0][0]
        n_ok+=1
        rows_out.append((fi,k,c,int(m.sum()),raw_v,cl_v,float(med),cen,d1,d2,do,da))
for x in rows_out[:22]:
    fi,k,c,px,raw_v,cl_v,med,cen,d1,d2,do,da=x
    if cen is None:
        print(f"{fi:>7}{k:>5}{c:>6.2f}{px:>9}{raw_v:>9}{cl_v:>8}{med:>8.2f}m"
              f"{'  뎁스 부족 — 3D 산출 불가':>24}")
    else:
        print(f"{fi:>7}{k:>5}{c:>6.2f}{px:>9}{raw_v:>9}{cl_v:>8}{med:>8.2f}m"
              f"{f'({cen[0]:5.2f},{cen[1]:5.2f},{cen[2]:5.2f})':>24}"
              f"{d1:>6.2f}m{d2:>6.2f}m{do:>6.2f}m{da:>6.2f}m")
print(f"\n저신뢰 검출 {len(rows_out)}개 중 3D 산출 가능 {n_ok} / 뎁스 부족 {n_nodepth}")
ok=[x for x in rows_out if x[7] is not None]
if ok:
    meds=np.array([x[6] for x in ok]); das=np.array([x[11] for x in ok])
    d1s=np.array([x[8] for x in ok]); dos=np.array([x[10] for x in ok])
    print(f"  카메라 거리      중앙 {np.median(meds):.2f}m  최대 {meds.max():.2f}m")
    print(f"  전체 장면까지    중앙 {np.median(das):.3f}m  (0에 가까울수록 형상 있음)")
    print(f"  객체 볼륨까지    중앙 {np.median(dos):.3f}m")
    print(f"  사람조각 p01까지 중앙 {np.median(d1s):.2f}m")
    print(f"  → 전체장면 5cm 이내 {(das<0.05).mean()*100:.0f}% / "
          f"객체볼륨 5cm 이내 {(dos<0.05).mean()*100:.0f}%")
