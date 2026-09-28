"""
메시에 **실제 영상의 색**을 입힌다 (torch를 import하지 않는다).

무엇을 하는가:
  각 정점을 카메라로 투영해 그 픽셀의 실제 색을 가져온다. 여러 프레임에서 보이면
  median을 취해 밝기 변화·모션블러의 영향을 줄인다.
  결과적으로 "옷 색깔·자세가 사진처럼 보이는" 3D가 된다.

⚠️ 가장 중요한 설계 — 안 본 곳은 칠하지 않는다:
  한 번도 관측되지 않은 정점은 **회색으로 남긴다.** 그 자체가 "여기는 못 봤다"는
  정직한 표시다. 주변 색으로 메워 넣으면 보기는 좋아지지만, 관측하지 않은 것을
  관측한 것처럼 보이게 만든다 — 의료·구조 판단에서 가장 위험한 실패다.
  (documents/warning/0917v1_2148 3번 항목)

가림(occlusion) 처리:
  정점이 카메라 화면 안에 들어온다고 보이는 것은 아니다. 다른 물체 뒤에 가려질 수 있다.
  뎁스맵을 써서 "투영된 깊이 ≈ 그 픽셀의 측정 깊이"일 때만 색을 채택한다.
  이게 없으면 벽 뒤의 정점이 벽 색을 가져간다.

사용법:
  python3 scripts/color_mesh.py <세션경로> <메시파일> [--out 이름] [--stride 2]
  예) python3 scripts/color_mesh.py server/sessions/session_X fused_person_01.ply

생성: <세션>/<메시이름>_colored.ply
"""
import argparse, csv, json, sys, time
from pathlib import Path

import numpy as np
import cv2
import open3d as o3d

ap = argparse.ArgumentParser()
ap.add_argument("session", type=Path)
ap.add_argument("mesh")
ap.add_argument("--out", default=None)
ap.add_argument("--stride", type=int, default=2, help="영상 N프레임마다 1장 사용")
ap.add_argument("--depth-tol", type=float, default=0.08, help="가림 판정 허용 오차(m)")
a = ap.parse_args()

t0 = time.time()
sess = a.session.resolve()
mesh_path = sess / a.mesh
if not mesh_path.exists():
    sys.exit(f"[실패] {a.mesh}가 없습니다: {sess}")

meta = json.loads((sess / "metadata.json").read_text(encoding="utf-8"))
DW, DH = meta["depth_width"], meta["depth_height"]
VW, VH = meta["video_frame_width"], meta["video_frame_height"]
sx, sy = DW / VW, DH / VH

mesh = o3d.io.read_triangle_mesh(str(mesh_path))
mesh.compute_vertex_normals()
V = np.asarray(mesh.vertices)
N = np.asarray(mesh.vertex_normals)
if len(V) == 0:
    sys.exit(f"[실패] {a.mesh}가 비어 있습니다.")
print(f"[{time.time()-t0:5.1f}s] 메시 {len(V):,}정점", flush=True)

poses = {r["timestamp"]: r for r in csv.DictReader(open(sess / "arkit_pose.csv"))}
drows = {int(r["video_frame_index"]): r for r in csv.DictReader(open(sess / "depth" / "index.csv"))
         if int(r["video_frame_index"]) >= 0}

def quat_to_R(x, y, z, w):
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

# 정점마다 관측된 색들을 모은다 (나중에 median)
samples = [[] for _ in range(len(V))]

cap = cv2.VideoCapture(str(sess / "video.mov"))
if not cap.isOpened():
    sys.exit("[실패] video.mov를 열 수 없습니다.")
idx = -1; used = 0
while True:
    ok, frame = cap.read()
    if not ok:
        break
    idx += 1
    if idx % max(a.stride, 1) or idx not in drows:
        continue
    r = drows[idx]
    p = poses.get(r["timestamp"])
    if p is None or p["tracking_state"] != "2":
        continue
    dpath = sess / "depth" / r["depth_file"]
    if not dpath.exists():
        continue
    depth = np.fromfile(dpath, dtype="<f4").reshape(DH, DW)

    R = quat_to_R(*[float(p[k]) for k in ("qx", "qy", "qz", "qw")])
    t = np.array([float(p[k]) for k in ("tx", "ty", "tz")])
    fx, fy, cx, cy = [float(p[k]) for k in ("fx", "fy", "cx", "cy")]

    cam = (V - t) @ R                      # world -> camera
    Z = cam[:, 2]
    front = Z < -1e-6                      # ARKit 카메라는 -Z 전방
    dep = -Z
    with np.errstate(divide="ignore", invalid="ignore"):
        u = cx + fx * cam[:, 0] / dep
        v = cy - fy * cam[:, 1] / dep      # 이미지 v는 아래로 증가
    inside = front & (u >= 0) & (u < VW) & (v >= 0) & (v < VH) & (dep > 0.2) & (dep < 6.0)

    # 뒷면은 칠하지 않는다 (카메라를 등진 면에 앞면 색이 묻는 것을 막는다)
    fwd = -R[:, 2]
    facing = (N @ fwd) < -0.15

    cand = np.where(inside & facing)[0]
    if cand.size == 0:
        continue

    # 가림 검사: 뎁스맵의 그 픽셀 깊이와 비교
    du = np.clip((u[cand] * sx).astype(int), 0, DW - 1)
    dv = np.clip((v[cand] * sy).astype(int), 0, DH - 1)
    measured = depth[dv, du]
    visible = (measured > 0) & (np.abs(measured - dep[cand]) < a.depth_tol)
    cand = cand[visible]
    if cand.size == 0:
        continue

    cu = np.clip(u[cand].astype(int), 0, VW - 1)
    cv_ = np.clip(v[cand].astype(int), 0, VH - 1)
    bgr = frame[cv_, cu]                   # OpenCV는 BGR
    for k, vi in enumerate(cand):
        samples[vi].append(bgr[k])
    used += 1
    if used % 25 == 0:
        print(f"[{time.time()-t0:5.1f}s] {used}프레임 반영", flush=True)
cap.release()

GRAY = np.array([140, 140, 140], dtype=np.float64)   # 안 본 정점의 색
colors = np.zeros((len(V), 3))
seen = 0
for i, s in enumerate(samples):
    if s:
        med = np.median(np.array(s, dtype=np.float64), axis=0)
        colors[i] = med[::-1] / 255.0      # BGR -> RGB
        seen += 1
    else:
        colors[i] = GRAY / 255.0
mesh.vertex_colors = o3d.utility.Vector3dVector(colors)

out = a.out or (mesh_path.stem + "_colored.ply")
o3d.io.write_triangle_mesh(str(sess / out), mesh)
print(f"[{time.time()-t0:5.1f}s] 완료: {used}프레임 반영, "
      f"정점 {seen:,}/{len(V):,} ({100*seen/len(V):.1f}%)에 실제 색 입힘")
print(f"  나머지 {len(V)-seen:,}개는 **한 번도 관측되지 않아 회색**으로 남겼습니다.")
print(f"  -> {sess/out}")
