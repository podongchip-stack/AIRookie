"""
2단계 — 검출된 2D 박스를 3D 위치(미터)로 매핑 (torch를 import하지 않는다)

1단계가 만든 detections_2d.json을 읽어 메시에 투영한다. 분리 이유는 detect_stage1.py 주석 참고.

CAM/scripts/11_map_objects_3d.py 와의 차이:
  그건 monocular SfM이라 절대 depth가 없어 "이 좌표는 실제 미터가 아니다"라고 명시해야 했다.
  LiDAR는 포즈와 형상이 처음부터 미터라 그 제약이 사라진다. 여기서 나오는 (x,y,z)는 진짜 미터다.

깊이 추정: 광선이 아니라 **bbox로 투영되는 메시 정점의 median**을 쓴다.
  메시 커버리지가 낮으면(실측 최선 18.7%) 광선의 81%가 구멍으로 빠져나가 아무것도 못 맞힌다.

사용법:
  python3 scripts/detect_stage2.py <세션경로> [--mesh scene_mesh.ply] [--radius 0.6]

생성: <세션>/objects_3d.json
"""
import argparse, csv, json, sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import open3d as o3d

PRIORITY = {"person", "chair", "couch", "bed", "dining table", "tv", "laptop",
            "backpack", "handbag", "suitcase", "bottle", "cup", "bench",
            "potted plant", "refrigerator", "microwave", "oven", "sink", "toilet"}

ap = argparse.ArgumentParser()
ap.add_argument("session", type=Path)
ap.add_argument("--mesh", default="scene_mesh.ply")
ap.add_argument("--radius", type=float, default=0.6, help="같은 물체로 묶을 거리(m)")
a = ap.parse_args()

sess = a.session.resolve()
det_file = sess / "detections_2d.json"
if not det_file.exists():
    sys.exit(f"[실패] detections_2d.json이 없습니다. 먼저 detect_stage1.py를 실행하세요.")

meta = json.loads((sess / "metadata.json").read_text(encoding="utf-8"))
det = json.loads(det_file.read_text(encoding="utf-8"))
W, H = meta["video_frame_width"], meta["video_frame_height"]

mesh = o3d.io.read_triangle_mesh(str(sess / a.mesh))
V = np.asarray(mesh.vertices)
if len(V) == 0:
    sys.exit(f"[실패] {a.mesh}가 비어 있습니다.")

def quat_to_R(x, y, z, w):
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

poses = {}
for r in csv.DictReader(open(sess / "arkit_pose.csv")):
    fi = int(r["frame_index"])
    # tracking_state 2(normal)만 쓴다. 불량 포즈로 계산하면 엉뚱한 위치의 객체가 섞인다.
    if fi >= 0 and r["tracking_state"] == "2":
        poses[fi] = r

obs = defaultdict(list)
n_det = n_loc = 0
for fi_s, dets in det["frames"].items():
    p = poses.get(int(fi_s))
    if p is None:
        continue
    R = quat_to_R(*[float(p[k]) for k in ("qx", "qy", "qz", "qw")])
    t = np.array([float(p[k]) for k in ("tx", "ty", "tz")])
    fx, fy, cx, cy = [float(p[k]) for k in ("fx", "fy", "cx", "cy")]
    # world -> camera. ARKit 카메라는 -Z 전방, 이미지 v는 아래로 증가.
    cam = (V - t) @ R
    Z = cam[:, 2]
    front = Z < -1e-6
    depth = -Z
    with np.errstate(divide="ignore", invalid="ignore"):
        u = cx + fx * cam[:, 0] / depth
        v = cy - fy * cam[:, 1] / depth
    for d in dets:
        n_det += 1
        x1, y1, x2, y2 = d["bbox"]
        mx, my = (x2 - x1) * 0.15, (y2 - y1) * 0.15      # 테두리는 배경이 섞인다
        sel = front & (u >= x1+mx) & (u <= x2-mx) & (v >= y1+my) & (v <= y2-my) \
              & (depth > 0.15) & (depth < 8.0)
        if sel.sum() < 8:
            continue
        dd = depth[sel]
        keep = dd <= np.percentile(dd, 40)               # 뒤쪽 벽 배제, 앞 표면만
        pts = V[sel][keep]
        if len(pts) < 5:
            continue
        n_loc += 1
        obs[d["class"]].append({"pos": np.median(pts, axis=0), "conf": d["conf"]})

objects = []
for cls, lst in obs.items():
    used = [False]*len(lst)
    for i, o in enumerate(lst):
        if used[i]:
            continue
        grp = [o]; used[i] = True
        for j in range(i+1, len(lst)):
            if not used[j] and np.linalg.norm(lst[j]["pos"] - o["pos"]) < a.radius:
                grp.append(lst[j]); used[j] = True
        pos = np.median([g["pos"] for g in grp], axis=0)
        objects.append({"class": cls,
                        "position_xyz": [round(float(x), 3) for x in pos],
                        "position_std": [round(float(x), 3) for x in np.std([g["pos"] for g in grp], axis=0)],
                        "num_observations": len(grp),
                        "avg_confidence": round(float(np.mean([g["conf"] for g in grp])), 3),
                        "priority": cls in PRIORITY})
objects.sort(key=lambda o: -o["num_observations"])

out = {"session_id": sess.name, "model": det.get("model"), "mesh": a.mesh,
       "coordinate_system": "ARKit world (right-handed, Y-up, meters) — scene_mesh.ply와 동일",
       "units": "meters (실제 미터. monocular SfM의 상대 좌표가 아니다)",
       "detections_total": n_det, "detections_localized": n_loc,
       "objects": objects,
       "note": "3D 위치는 bbox로 투영되는 메시 정점의 median이다. "
               "메시 커버리지가 낮으면 localized 비율이 떨어진다 — 스캔 범위 부족이지 검출 실패가 아니다."}
(sess / "objects_3d.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"  검출 {n_det} / 3D확정 {n_loc} ({100*n_loc/max(n_det,1):.0f}%) / 객체 {len(objects)}개")
for o in objects[:10]:
    p = o["position_xyz"]
    print(f"    {o['class']:<15} ({p[0]:+.2f}, {p[1]:+.2f}, {p[2]:+.2f}) m  "
          f"관측 {o['num_observations']:>3}회{' ★' if o['priority'] else ''}")
print(f"  -> {sess/'objects_3d.json'}")
