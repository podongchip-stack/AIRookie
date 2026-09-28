#!/usr/bin/env python3
"""세 해법의 효과를 각각 따로 검증한다 (open3d 전용 프로세스, 파이프라인 미수정).

  A) 최근접 영상 프레임 마스크   — 시간 어긋남을 100ms→33ms로 줄인 마스크로 융합
  B) 인스턴스별 깊이 게이트      — 라벨맵 시뮬레이션. 융합은 여전히 하나의 볼륨
  C) 3D 월드 좌표 기반 사람 배정 — 인스턴스 중심점을 3D에서 군집화해 조각을 쪼갠다
"""
import sys, csv, json
from pathlib import Path
import numpy as np, cv2, open3d as o3d

S = Path(sys.argv[1]); OBV = 0.01; FLOOR = -0.71
meta = json.loads((S/"metadata.json").read_text(encoding="utf-8"))
W, H = meta["depth_width"], meta["depth_height"]
VW, VH = meta["video_frame_width"], meta["video_frame_height"]
sx, sy = W/VW, H/VH
poses = {r["timestamp"]: r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows  = list(csv.DictReader(open(S/"depth"/"index.csv")))
near  = {int(k): v for k, v in json.load(open(S/"diag_nearest_map.json")).items()}
zm    = np.load(S/"diag_masks_nearest.npz")
zi    = np.load(S/"diag_inst_nearest.npz")

def R_(qx,qy,qz,qw):
    return np.array([[1-2*(qy*qy+qz*qz),2*(qx*qy-qz*qw),2*(qx*qz+qy*qw)],
                     [2*(qx*qy+qz*qw),1-2*(qx*qx+qz*qz),2*(qy*qz-qx*qw)],
                     [2*(qx*qz-qy*qw),2*(qy*qz+qx*qw),1-2*(qx*qx+qy*qy)]])

def clean(d, mx=4.0, er=0.04):
    d=d.copy(); d[(d<=0)|(d>mx)]=0
    pad=np.pad(d,1,constant_values=0)
    nb=np.stack([pad[:-2,1:-1],pad[2:,1:-1],pad[1:-1,:-2],pad[1:-1,2:]])
    with np.errstate(divide="ignore",invalid="ignore"):
        rel=np.abs(nb-d[None])/np.maximum(d[None],1e-6)
    d[np.nanmax(np.where(nb>0,rel,0),axis=0)>er]=0
    return d

def cam(p):
    K=[float(p["fx"])*sx,float(p["fy"])*sy,float(p["cx"])*sx,float(p["cy"])*sy]
    R=R_(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")])
    T=np.eye(4); T[:3,:3]=R@np.diag([1.,-1.,-1.]); T[:3,3]=t
    return K,T

def gate_by_blobs(do, m):
    """현행: 연결 성분별 깊이 게이트"""
    n,lab=cv2.connectedComponents(m.astype(np.uint8))
    for li in range(1,n):
        b=(lab==li)&(do>0)
        if b.sum()<50: do[lab==li]=0; continue
        med=float(np.median(do[b])); do[(lab==li)&((do<med-0.6)|(do>med+0.6))]=0
    return do

def gate_by_inst(do, insts):
    """B: 인스턴스별 깊이 게이트 (라벨맵 시뮬레이션)"""
    keep=np.zeros_like(do)
    for m in insts:
        b=m&(do>0)
        if b.sum()<50: continue
        med=float(np.median(do[b]))
        ok=b&(do>=med-0.6)&(do<=med+0.6)
        keep[ok]=do[ok]
    return keep

def insts_at(fi):
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    return [zi[f"{fi}_{k}"] for k in range(n)]

def fuse(mode):
    vol=o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=OBV, sdf_trunc=OBV*3,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor)
    n=0
    for i,r in enumerate(rows):
        p=poses.get(r["timestamp"])
        if p is None or p["tracking_state"]!="2": continue
        if i not in near: continue
        fi=near[i]
        m=zm[str(fi)] if str(fi) in zm.files else None
        if m is None or not m.any(): continue
        d=clean(np.fromfile(S/"depth"/r["depth_file"],dtype="<f4").reshape(H,W))
        if (d>0).sum()<200: continue
        do=d.copy(); do[~m]=0
        do = gate_by_inst(do, insts_at(fi)) if mode=="inst" else gate_by_blobs(do, m)
        if (do>0).sum()<100: continue
        K,T=cam(p)
        rgbd=o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.zeros((H,W,3),np.uint8)),
            o3d.geometry.Image(np.ascontiguousarray(do)),
            depth_scale=1.0,depth_trunc=4.0,convert_rgb_to_intensity=False)
        vol.integrate(rgbd,o3d.camera.PinholeCameraIntrinsic(W,H,*K),np.linalg.inv(T))
        n+=1
    m=vol.extract_triangle_mesh(); m.compute_vertex_normals()
    return m,n

ok_size=lambda d:(0.30<d[1]<2.2 and 0.15<d[0]<2.0 and 0.15<d[2]<2.0)
def report(mesh,label,n):
    with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
        ci,_,ca=mesh.cluster_connected_triangles()
    ci=np.asarray(ci);ca=np.asarray(ca);V=np.asarray(mesh.vertices);T=np.asarray(mesh.triangles)
    print(f"\n{'='*68}\n{label}   융합 {n}프레임\n{'='*68}")
    print(f"  전체 {mesh.get_surface_area():.2f}㎡  정점 {len(V):,}  조각 {len(ca)}")
    npass=0
    for k in np.argsort(-ca)[:5]:
        if ca[k]<0.05: break
        P=V[np.unique(T[np.where(ci==k)[0]])]; d=P.max(0)-P.min(0)
        g=ok_size(d) and ca[k]>=0.15
        npass+= g
        print(f"    조각{k:>5} {ca[k]:6.2f}㎡  {d[0]:5.2f}x{d[1]:5.2f}x{d[2]:5.2f}m  {'✅' if g else '❌'}")
    print(f"  → 크기 통과 {npass}개")
    return mesh,ci,ca

mD,nD = fuse("blob"); report(mD,"A/모드D) 최근접 영상 프레임 마스크 + 연결성분 게이트",nD)
mB,nB = fuse("inst"); meshB=report(mB,"B) 최근접 마스크 + **인스턴스별** 깊이 게이트",nB)
o3d.io.write_triangle_mesh(str(S/"diag_objects_nearest.ply"), mD)
o3d.io.write_triangle_mesh(str(S/"diag_objects_inst.ply"), mB)
print("\n  저장: diag_objects_nearest.ply / diag_objects_inst.ply")
