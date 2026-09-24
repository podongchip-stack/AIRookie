#!/usr/bin/env python3
"""융합된 조각이 YOLO 인스턴스 중 **몇 명을** 덮는지 측정한다 (open3d 전용 프로세스).

가림(z-buffer) 처리를 반드시 한다. 안 하면 3D상 다른 위치의 점이 화면에서 겹쳐
보여 잘못된 결론을 낸다 (실제로 두 번 겪었다).
"""
import sys, csv, json
from pathlib import Path
import numpy as np, cv2, open3d as o3d

S=Path(sys.argv[1]); CL=int(sys.argv[2]); inst_npz=Path(sys.argv[3])
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
DW,DH=meta["depth_width"],meta["depth_height"]
VW,VH=meta["video_frame_width"],meta["video_frame_height"]

mob=o3d.io.read_triangle_mesh(str(S/"fused_objects.ply"))
with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
    ci,_,carea=mob.cluster_connected_triangles()
ci=np.asarray(ci);carea=np.asarray(carea);Vo=np.asarray(mob.vertices);To=np.asarray(mob.triangles)
Pc=Vo[np.unique(To[np.where(ci==CL)[0]])]
print(f"조각 {CL}: {carea[CL]:.2f}㎡, 정점 {len(Pc):,}\n")

poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows={int(r["video_frame_index"]):r for r in csv.DictReader(open(S/"depth"/"index.csv"))
      if int(r["video_frame_index"])>=0}
z=np.load(inst_npz)
def q2R(qx,qy,qz,qw):
    return np.array([[1-2*(qy*qy+qz*qz),2*(qx*qy-qz*qw),2*(qx*qz+qy*qw)],
                     [2*(qx*qy+qz*qw),1-2*(qx*qx+qz*qz),2*(qy*qz-qx*qw)],
                     [2*(qx*qz-qy*qw),2*(qy*qz+qx*qw),1-2*(qx*qx+qy*qy)]])

frames=sorted({int(k.split("_")[0]) for k in z.files})
for fi in frames:
    n=int(z[f"{fi}_n"][0])
    if n==0 or fi not in rows: 
        print(f"프레임 {fi}: 인스턴스 {n}개 / 뎁스 행 없음 — 건너뜀"); continue
    p=poses.get(rows[fi]["timestamp"])
    if p is None or p["tracking_state"]!="2":
        print(f"프레임 {fi}: 포즈 없음/불량 — 건너뜀"); continue
    R=q2R(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")])
    Rc=np.diag([1.,-1.,-1.])@R.T; tc=-Rc@t
    fx=float(p["fx"])*DW/VW; fy=float(p["fy"])*DH/VH
    cx=float(p["cx"])*DW/VW; cy=float(p["cy"])*DH/VH
    # z-버퍼: 전체 메시로 가림을 만들고, 대상 조각이 최전면인 화소만 표시
    zb=np.full((DH,DW),np.inf,np.float32); own=np.zeros((DH,DW),bool)
    for arr,mine in ((Vo,False),(Pc,True)):
        pc=arr@Rc.T+tc; m=pc[:,2]>0.2
        u=fx*pc[m,0]/pc[m,2]+cx; v=fy*pc[m,1]/pc[m,2]+cy; zz=pc[m,2]
        s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
        uu,vv,zz=u[s].astype(int),v[s].astype(int),zz[s]
        for dr in (-1,0,1):
            for dc in (-1,0,1):
                yy=np.clip(vv+dr,0,DH-1); xx=np.clip(uu+dc,0,DW-1)
                up=zz<zb[yy,xx]; zb[yy[up],xx[up]]=zz[up]; own[yy[up],xx[up]]=mine
    print(f"프레임 {fi} — YOLO 인스턴스 {n}개, 조각{CL}이 덮는 비율:")
    covered=0
    for i in range(n):
        m=z[f"{fi}_{i}"]
        if m.sum()==0: continue
        r_=(own&m).sum()/m.sum()*100
        mark="← 덮음" if r_>=25 else ""
        if r_>=25: covered+=1
        print(f"    인스턴스{i}: 마스크 {m.sum():>6}화소 중 {r_:5.1f}% {mark}")
    print(f"    → 25% 이상 덮은 인스턴스: {covered}/{n}\n")
