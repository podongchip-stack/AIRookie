#!/usr/bin/env python3
"""sdf_trunc 스윕 — 껍질 두께가 '반쪽으로 보이는' 현상의 원인인지 본다 (open3d 전용).

현재 파이프라인은 sdf_trunc = voxel * 3 (객체 복셀 1cm -> 3cm)이다.
그래서 사람이 속이 찬 덩어리가 아니라 **3cm 두께의 껍질**로 복원되고,
삼각형의 32~41%가 안쪽을 향해 구멍으로 속이 비친다.

⚠️ 파이프라인(stage2_fuse.py)은 건드리지 않는다. 결과만 따로 만들어 비교한다.
   뷰어에서 바로 볼 수 있도록 persons.json에 fused_person_1N 으로 덧붙인다.
   되돌리기: stage2_fuse.py를 다시 돌리면 원상복구된다.

사용: trunc_sweep.py <세션경로> [배수들]   기본 3,5,8,12
"""
import sys, csv, json, time, os, glob
from pathlib import Path
import numpy as np, open3d as o3d, cv2
from scipy.spatial import cKDTree

S = Path(sys.argv[1])
MULTS = [float(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [3, 5, 8, 12]
VOX = 0.01
meta = json.loads((S/"metadata.json").read_text(encoding="utf-8"))
W, H = meta["depth_width"], meta["depth_height"]
sx, sy = W/meta["video_frame_width"], H/meta["video_frame_height"]
poses = {r["timestamp"]: r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows = list(csv.DictReader(open(S/"depth"/"index.csv")))
z = np.load(S/"person_masks.npz"); masks = {int(k): z[k] for k in z.files}
mask_map = {int(k): int(v) for k, v in json.load(open(S/"person_masks_map.json")).items()}

def R_(x,y,z_,w):
    return np.array([[1-2*(y*y+z_*z_),2*(x*y-z_*w),2*(x*z_+y*w)],
                     [2*(x*y+z_*w),1-2*(x*x+z_*z_),2*(y*z_-x*w)],
                     [2*(x*z_-y*w),2*(y*z_+x*w),1-2*(x*x+y*y)]])
def clean(d, maxd=4.0):
    d = d.copy(); d[(d<=0)|(d>maxd)] = 0
    if not (d>0).any(): return d
    pad = np.pad(d,1,mode="edge")
    nb = np.stack([pad[:-2,1:-1],pad[2:,1:-1],pad[1:-1,:-2],pad[1:-1,2:]])
    with np.errstate(divide="ignore",invalid="ignore"):
        rel = np.abs(nb-d[None])/np.maximum(d[None],1e-6)
    d[np.nanmax(np.where(nb>0,rel,0),axis=0)>0.04] = 0
    return d

def fuse(trunc):
    """stage2_fuse.py의 객체 볼륨 부분만 그대로 재현하되 sdf_trunc만 바꾼다."""
    vol = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=VOX, sdf_trunc=trunc,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor)
    last = np.zeros((H,W), bool); n = 0
    for r in rows:
        p = poses.get(r["timestamp"])
        if p is None or p["tracking_state"] != "2": continue
        d = clean(np.fromfile(S/"depth"/r["depth_file"], dtype="<f4").reshape(H,W))
        if (d>0).sum() < 200: continue
        k = mask_map.get(int(r["depth_index"]))
        m = masks.get(k) if k is not None else None
        if m is not None: last = m
        if not last.any(): continue
        do = d.copy(); do[~last] = 0
        nlab, lab = cv2.connectedComponents(last.astype(np.uint8))
        for li in range(1, nlab):
            blob = (lab==li)&(do>0)
            if blob.sum() < 50: do[lab==li] = 0; continue
            med = float(np.median(do[blob]))
            do[(lab==li)&((do<med-0.6)|(do>med+0.6))] = 0
        if (do>0).sum() < 100: continue
        K = [float(p["fx"])*sx, float(p["fy"])*sy, float(p["cx"])*sx, float(p["cy"])*sy]
        R = R_(*[float(p[q]) for q in ("qx","qy","qz","qw")])
        t = np.array([float(p[q]) for q in ("tx","ty","tz")])
        T = np.eye(4); T[:3,:3] = R@np.diag([1.,-1.,-1.]); T[:3,3] = t
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.zeros((H,W,3),dtype=np.uint8)),
            o3d.geometry.Image(np.ascontiguousarray(do)),
            depth_scale=1.0, depth_trunc=4.0, convert_rgb_to_intensity=False)
        vol.integrate(rgbd, o3d.camera.PinholeCameraIntrinsic(W,H,*K), np.linalg.inv(T))
        n += 1
    return vol.extract_triangle_mesh(), n

def pick(mesh, ref=None):
    """기준 조각(배수 3)의 중심에 가장 가까운 조각을 고른다.
    ⚠️ '가장 큰 조각'으로 고르면 배수마다 대상이 바뀐다 (실측으로 확인했다)."""
    with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
        ci,_,ca = mesh.cluster_connected_triangles()
    ci = np.asarray(ci); ca = np.asarray(ca)
    V = np.asarray(mesh.vertices); T = np.asarray(mesh.triangles)
    cand = [k for k in range(len(ca)) if ca[k] > 0.05]
    if not cand: cand = [int(np.argmax(ca))]
    if ref is None:
        k = int(max(cand, key=lambda x: ca[x]))
    else:
        k = int(min(cand, key=lambda x: np.linalg.norm(
            V[T[np.where(ci==x)[0]]].reshape(-1,3).mean(0) - ref)))
    sub = o3d.geometry.TriangleMesh(mesh)
    sub.triangles = o3d.utility.Vector3iVector(T[ci==k])
    sub.remove_unreferenced_vertices(); sub.compute_vertex_normals()
    return sub, len(cand)

def thickness(m):
    """바깥 면에서 법선 반대 방향으로 광선을 쏴 반대편 면까지 거리 = 껍질 두께."""
    V = np.asarray(m.vertices); T = np.asarray(m.triangles)
    N = np.asarray(m.triangle_normals); tc = V[T].mean(1); cen = V.mean(0)
    out = ((tc-cen)*N).sum(1) > 0
    if out.sum() < 50: return float("nan")
    sc = o3d.t.geometry.RaycastingScene()
    sc.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(m))
    o = (tc[out] - N[out]*1e-3).astype(np.float32)[::5]
    d = (-N[out]).astype(np.float32)[::5]
    hit = sc.cast_rays(o3d.core.Tensor(np.hstack([o,d]), dtype=o3d.core.Dtype.Float32))
    t = hit["t_hit"].numpy()
    t = t[np.isfinite(t) & (t < 0.5)]
    return float(np.median(t)) if len(t) else float("nan")

def stats(m):
    V = np.asarray(m.vertices); T = np.asarray(m.triangles)
    N = np.asarray(m.triangle_normals); tc = V[T].mean(1); cen = V.mean(0)
    out = ((tc-cen)*N).sum(1) > 0
    from collections import Counter
    e = Counter()
    for a,b,c in T:
        for x,y in ((a,b),(b,c),(c,a)): e[(min(x,y),max(x,y))] += 1
    bnd = sum(1 for v in e.values() if v==1)
    # 껍질 두께 — 바깥 면에서 가장 가까운 안쪽 면까지 거리
    d = V.max(0)-V.min(0)
    return dict(verts=len(V), tris=len(T), area=float(m.get_surface_area()),
                outward=float(out.mean()), bnd=bnd/max(len(e),1),
                size=[float(x) for x in d])

print(f"=== {S.name} sdf_trunc 스윕 (복셀 {VOX*100:.0f}cm) ===")
print(f"  {'배수':>5}{'trunc':>8}{'프레임':>7}{'정점':>9}{'면적':>8}{'바깥향':>8}"
      f"{'열린모서리':>11}{'껍질두께':>10}{'조각수':>7}{'가로x높이x깊이':>22}{'초':>6}")
pers = json.loads((S/"persons.json").read_text(encoding="utf-8"))
pers["persons"] = [p for p in pers["persons"] if p["index"] < 10]
for old in glob.glob(f"{S}/fused_person_1*.ply"): os.remove(old)
res = []; REF = None
for i, mu in enumerate(MULTS):
    t0 = time.time(); mesh, nf = fuse(VOX*mu)
    sub, ncl = pick(mesh, REF)
    if REF is None: REF = np.asarray(sub.vertices).mean(0)
    st = stats(sub); st["thick"] = thickness(sub); st["ncl"] = ncl
    el = time.time()-t0
    idx = 11+i
    sub.paint_uniform_color([.90,.16,.16])
    o3d.io.write_triangle_mesh(f"{S}/fused_person_{idx:02d}.ply", sub)
    c = np.asarray(sub.vertices).mean(0)
    pers["persons"].append({"file": f"fused_person_{idx:02d}.ply", "index": idx,
        "surface_m2": round(st["area"],3), "size_m": [round(x,3) for x in st["size"]],
        "center_xyz": [round(float(x),3) for x in c], "vertices": st["verts"],
        "note": f"[실험] sdf_trunc {VOX*mu*100:.0f}cm (기본 3cm) — "
                f"바깥향 {st['outward']*100:.0f}%, 껍질 {st['thick']*100:.1f}cm"})
    res.append((mu, st))
    print(f"  x{mu:<4.0f}{VOX*mu*100:>6.0f}cm{nf:>7}{st['verts']:>9,}{st['area']:>7.2f}㎡"
          f"{st['outward']*100:>7.1f}%{st['bnd']*100:>10.1f}%{st['thick']*100:>9.1f}cm"
          f"{st['ncl']:>7}  {st['size'][0]:5.2f}x{st['size'][1]:5.2f}x{st['size'][2]:5.2f}{el:>6.0f}")
pers["count"] = len([p for p in pers["persons"] if p["index"] < 10])
(S/"persons.json").write_text(json.dumps(pers, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"  → 뷰어 사람 목록에 11~{10+len(MULTS)}번으로 추가했다. "
      f"되돌리려면 stage2_fuse.py를 다시 돌리면 된다.")
