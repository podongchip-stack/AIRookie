#!/usr/bin/env python3
"""stale 마스크 가설 검증 (진단 전용 — 파이프라인을 수정하지 않는다).

stage2_fuse.py는 video_frame_index<0 인 뎁스 프레임에 **직전 마스크를 재사용**한다.
그 사이 카메라가 움직였다면 마스크가 엉뚱한 표면에 적용되어,
사람과 주변이 하나로 붙을 수 있다 (H3).

검증: 객체 볼륨을 두 가지로 만들어 조각 크기를 비교한다.
  A) 전체 프레임 (현행)          — stale 마스크 재사용 포함
  B) 신선한 마스크 프레임만      — video_frame_index>=0 이고 마스크가 있는 프레임만
"""
import sys, csv, json
from pathlib import Path
import numpy as np, cv2, open3d as o3d

S = Path(sys.argv[1]); OBV = 0.01
meta = json.loads((S/"metadata.json").read_text(encoding="utf-8"))
W, H = meta["depth_width"], meta["depth_height"]
vw, vh = meta["video_frame_width"], meta["video_frame_height"]
sx, sy = W/vw, H/vh
poses = {r["timestamp"]: r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows = list(csv.DictReader(open(S/"depth"/"index.csv")))
z = np.load(S/"person_masks.npz"); masks = {int(k): z[k] for k in z.files}

def R_(qx,qy,qz,qw):
    return np.array([[1-2*(qy*qy+qz*qz),2*(qx*qy-qz*qw),2*(qx*qz+qy*qw)],
                     [2*(qx*qy+qz*qw),1-2*(qx*qx+qz*qz),2*(qy*qz-qx*qw)],
                     [2*(qx*qz-qy*qw),2*(qy*qz+qx*qw),1-2*(qx*qx+qy*qy)]])

def clean(d, max_depth=4.0, edge_ratio=0.04):
    d = d.copy(); d[(d<=0)|(d>max_depth)] = 0
    pad = np.pad(d,1,constant_values=0)
    nb = np.stack([pad[:-2,1:-1],pad[2:,1:-1],pad[1:-1,:-2],pad[1:-1,2:]])
    with np.errstate(divide="ignore",invalid="ignore"):
        rel = np.abs(nb-d[None])/np.maximum(d[None],1e-6)
    d[np.nanmax(np.where(nb>0,rel,0),axis=0)>edge_ratio] = 0
    return d

# 최근접 마스크 프레임 (시간 기준)
import csv as _csv
_vf={int(r["frame_index"]):float(r["timestamp"])
     for r in _csv.DictReader(open(S/"video_frames.csv"))}
_have=sorted((_vf[i],i) for i in masks if i in _vf)
_ht=np.array([x[0] for x in _have]); _hi=np.array([x[1] for x in _have])

def fuse(mode: str):
    """mode: 'all'(현행) | 'fresh'(신선만) | 'nearest'(최근접 타임스탬프)"""
    vol = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=OBV, sdf_trunc=OBV*3,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor)
    last = np.zeros((H,W), bool); n = 0
    for r in rows:
        p = poses.get(r["timestamp"])
        if p is None or p["tracking_state"] != "2": continue
        vfi = int(r["video_frame_index"])
        if vfi in masks:
            last = masks[vfi]
        elif mode == "fresh":
            continue                      # ← 낡은 마스크를 아예 쓰지 않는다
        elif mode == "nearest":
            ts = float(r["timestamp"])
            last = masks[int(_hi[int(np.argmin(np.abs(_ht - ts)))])]
        if not last.any(): continue
        d = clean(np.fromfile(S/"depth"/r["depth_file"], dtype="<f4").reshape(H,W))
        if (d>0).sum() < 200: continue
        do = d.copy(); do[~last] = 0
        nlab, lab = cv2.connectedComponents(last.astype(np.uint8))
        for li in range(1, nlab):
            blob = (lab==li)&(do>0)
            if blob.sum() < 50: do[lab==li]=0; continue
            med = float(np.median(do[blob]))
            do[(lab==li)&((do<med-0.6)|(do>med+0.6))] = 0
        if (do>0).sum() < 100: continue
        K=[float(p["fx"])*sx,float(p["fy"])*sy,float(p["cx"])*sx,float(p["cy"])*sy]
        R=R_(*[float(p[k]) for k in ("qx","qy","qz","qw")])
        t=np.array([float(p[k]) for k in ("tx","ty","tz")])
        T=np.eye(4); T[:3,:3]=R@np.diag([1.,-1.,-1.]); T[:3,3]=t
        rgbd=o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.zeros((H,W,3),np.uint8)),
            o3d.geometry.Image(np.ascontiguousarray(do)),
            depth_scale=1.0, depth_trunc=4.0, convert_rgb_to_intensity=False)
        vol.integrate(rgbd, o3d.camera.PinholeCameraIntrinsic(W,H,*K), np.linalg.inv(T))
        n += 1
    m = vol.extract_triangle_mesh(); m.compute_vertex_normals()
    return m, n

def report(m, label, n):
    with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
        ci,_,carea = m.cluster_connected_triangles()
    ci=np.asarray(ci); carea=np.asarray(carea)
    V=np.asarray(m.vertices); T=np.asarray(m.triangles)
    ok=lambda d:(0.30<d[1]<2.2 and 0.15<d[0]<2.0 and 0.15<d[2]<2.0)
    print(f"\n{'='*66}\n{label}  (융합 프레임 {n}개)\n{'='*66}")
    print(f"  전체 {m.get_surface_area():.2f}㎡  정점 {len(V):,}  조각 {len(carea)}개")
    print(f"  {'조각':>6}{'표면적':>9}{'가로x높이x깊이':>24}  판정")
    npass=0; apass=0
    for k in np.argsort(-carea)[:6]:
        if carea[k] < 0.05: break
        vi=np.unique(T[np.where(ci==k)[0]]); P=V[vi]; d=P.max(0)-P.min(0)
        good = ok(d) and carea[k]>=0.15
        if good: npass+=1; apass+=carea[k]
        print(f"  {k:>6}{carea[k]:>8.2f}㎡   {d[0]:5.2f}x{d[1]:5.2f}x{d[2]:5.2f}m  "
              f"{'✅ 사람 크기' if good else '❌ 범위 밖'}")
    print(f"  → 크기 통과 조각 {npass}개, 합계 {apass:.2f}㎡")
    return npass, apass

mA,nA = fuse("all");     report(mA,"A) 전체 프레임 — 현행 (직전 마스크 재사용)",nA)
mB,nB = fuse("fresh");   report(mB,"B) 신선한 마스크 프레임만",nB)
mC,nC = fuse("nearest"); report(mC,"C) 최근접 타임스탬프 매칭",nC)
