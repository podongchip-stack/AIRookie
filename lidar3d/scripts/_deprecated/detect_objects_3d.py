"""
⚠️ 사용 금지 — 이 환경에서 완료되지 않는다.

open3d와 torch(YOLO)를 **한 프로세스에서 import**하면 CPU 0%로 무한 대기한다
(실측 확인). 아래 2단계 스크립트로 대체되었다.

  detect_objects_3d.py -> detect_stage1.py + detect_stage2.py
  fuse_adaptive.py     -> stage1_masks.py  + stage2_fuse.py

로직 참고용으로만 남긴다.
"""
YOLO 객체 인식 + LiDAR 3D 위치 매핑

무엇을 하는가:
  video.mov의 프레임에 YOLOv8(COCO 80클래스)을 돌려 사람/의자/가방 같은 **임의 객체**를
  검출하고, arkit_pose.csv의 카메라 포즈로 각 객체의 3D 위치를 **실제 미터**로 계산한다.

왜 필요한가 (두 시스템의 빈칸이 정확히 반대다):
  - ARKit 메시 분류는 8개뿐이다: none/wall/floor/ceiling/table/seat/window/door.
    **방 구조 분류기**이지 물체 인식기가 아니다. "사람", "가방", "소화기"는 표현 불가.
  - YOLO(COCO 80)는 사람/사물은 잘 잡지만 **door가 아예 없다**.
  둘을 합치면: 구조물은 LiDAR 분류가, 임의 객체는 YOLO가 담당한다.

CAM/scripts/11_map_objects_3d.py 와의 차이 (여기가 핵심):
  기존 스크립트는 monocular SfM이라 절대 depth가 없어서, dense point cloud를 bbox에
  투영해 median을 취하는 우회를 했고 결과에 "이건 실제 미터가 아니다"라고 명시해야 했다.
  LiDAR는 포즈와 형상이 처음부터 미터 단위라 그 제약이 **사라진다.** 나오는 (x,y,z)와
  거리는 전부 진짜 미터다.

깊이 추정 방식 — 왜 레이캐스팅이 아니라 정점 투영인가:
  실측 결과 이 세션의 메시 커버리지는 약 8%(10.4 m^2 / 예상 133 m^2)로 구멍이 매우 많다.
  광선을 쏘면 81%가 구멍으로 빠져나가 아무것도 못 맞힌다. 그래서 bbox 안으로 **투영되는
  메시 정점들**을 모아 median을 쓴다 (구멍에 강하다). 커버리지가 좋아지면 둘 다 잘 된다.

사용법:
  python3 scripts/detect_objects_3d.py server/sessions/session_XXXX [--stride 5] [--conf 0.35]

생성되는 파일:
  <세션폴더>/objects_3d.json   (뷰어가 읽어서 3D 라벨로 표시)

성공/실패 판단:
  - localized / total 비율이 낮으면 메시 커버리지 부족이다. 더 넓게/천천히 스캔할 것.
  - 검출이 아예 없으면 --conf를 0.2로 낮춰 재시도.
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

# 이 프로젝트가 특히 관심 있는 COCO 클래스 (응급현장 맥락)
PRIORITY_CLASSES = {
    "person", "chair", "couch", "bed", "dining table", "tv", "laptop",
    "backpack", "handbag", "suitcase", "bottle", "cup", "bench",
    "potted plant", "refrigerator", "microwave", "oven", "sink", "toilet",
}


def quat_to_R(x, y, z, w):
    """쿼터니언 -> 3x3 회전행렬. arkit_pose.csv의 (qx,qy,qz,qw)는 camera-to-world."""
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w)],
        [2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y)],
    ])


def load_poses(session: Path):
    """frame_index -> 포즈. -1(영상 프레임 없음)과 트래킹 불량은 버린다."""
    poses = {}
    with (session / "arkit_pose.csv").open() as f:
        for r in csv.DictReader(f):
            fi = int(r["frame_index"])
            if fi < 0:
                continue
            # tracking_state: 2=normal. limited/notAvailable 프레임의 포즈로 3D를 계산하면
            # 좌표가 통째로 어긋난 객체가 조용히 섞여 들어간다.
            if r["tracking_state"] != "2":
                continue
            poses[fi] = {
                "R": quat_to_R(*[float(r[k]) for k in ("qx", "qy", "qz", "qw")]),
                "t": np.array([float(r[k]) for k in ("tx", "ty", "tz")]),
                "K": [float(r[k]) for k in ("fx", "fy", "cx", "cy")],
                "timestamp": float(r["timestamp"]),
            }
    return poses


def project_vertices(V, pose):
    """
    메시 정점을 카메라 화면 좌표로 투영한다.

    ARKit 카메라 규약 (실측으로 검증함 — 이 방향이 반대면 명중률이 1/2.5로 떨어진다):
      +X 오른쪽, +Y 위, **-Z가 정면**. 이미지 좌표 v는 아래로 증가하므로 Y 부호가 뒤집힌다.
    """
    fx, fy, cx, cy = pose["K"]
    # world -> camera (R은 camera-to-world이므로 전치가 world-to-camera)
    cam = (V - pose["t"]) @ pose["R"]
    Z = cam[:, 2]
    front = Z < -1e-6                       # -Z가 정면이므로 앞쪽은 Z<0
    depth = -Z                              # 양수 깊이(미터)
    with np.errstate(divide="ignore", invalid="ignore"):
        u = cx + fx * cam[:, 0] / depth
        v = cy - fy * cam[:, 1] / depth     # 이미지 v는 아래로 증가
    return u, v, depth, front


def localize(V, pose, bbox, W, H):
    """
    bbox 안으로 투영되는 메시 정점들의 median world 좌표 = 객체의 3D 위치.

    median인 이유: bbox에는 객체 뒤쪽 벽 정점도 같이 잡힌다. 평균을 쓰면 벽 쪽으로
    끌려가고, median은 다수를 차지하는 표면 쪽에 머문다.
    """
    x1, y1, x2, y2 = bbox
    # 테두리는 배경이 섞이므로 15% 안쪽만 쓴다
    mx, my = (x2 - x1) * 0.15, (y2 - y1) * 0.15
    x1, y1, x2, y2 = x1 + mx, y1 + my, x2 - mx, y2 - my

    u, v, depth, front = project_vertices(V, pose)
    sel = front & (u >= x1) & (u <= x2) & (v >= y1) & (v <= y2) & (depth > 0.15) & (depth < 8.0)
    n = int(sel.sum())
    if n < 8:                                # 표본이 너무 적으면 신뢰할 수 없다
        return None, n
    d = depth[sel]
    # 가장 가까운 표면(= 객체) 쪽을 취한다. 뒤쪽 벽을 배제하기 위해 하위 40% 깊이만 사용.
    keep = d <= np.percentile(d, 40)
    pts = V[sel][keep]
    if len(pts) < 5:
        return None, n
    return np.median(pts, axis=0), n


def cluster(observations, radius=0.6):
    """
    같은 클래스의 관측을 위치로 묶어 하나의 객체로 만든다.
    (프레임마다 따로 나온 'person' 30개가 전부 같은 사람일 수 있다.)
    radius는 미터 — LiDAR라서 이런 임계값을 실제 거리로 정할 수 있다.
    """
    objects = []
    for cls, obs in observations.items():
        used = [False] * len(obs)
        for i, o in enumerate(obs):
            if used[i]:
                continue
            group = [o]
            used[i] = True
            for j in range(i + 1, len(obs)):
                if used[j]:
                    continue
                if np.linalg.norm(obs[j]["pos"] - o["pos"]) < radius:
                    group.append(obs[j])
                    used[j] = True
            pos = np.median([g["pos"] for g in group], axis=0)
            std = np.std([g["pos"] for g in group], axis=0)
            objects.append({
                "class": cls,
                "position_xyz": [round(float(x), 3) for x in pos],
                "position_std": [round(float(x), 3) for x in std],
                "num_observations": len(group),
                "avg_confidence": round(float(np.mean([g["conf"] for g in group])), 3),
                "priority": cls in PRIORITY_CLASSES,
            })
    # 관측이 많은 순 = 신뢰도 높은 순
    return sorted(objects, key=lambda o: -o["num_observations"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path)
    ap.add_argument("--stride", type=int, default=5, help="영상 N프레임마다 1장 처리")
    ap.add_argument("--conf", type=float, default=0.35, help="YOLO 신뢰도 하한")
    ap.add_argument("--model", default=None, help="YOLO 가중치 경로 (기본: yolov8n.pt 자동 탐색)")
    args = ap.parse_args()

    session = args.session.resolve()
    for need in ("video.mov", "arkit_pose.csv", "scene_mesh.ply", "metadata.json"):
        if not (session / need).exists():
            sys.exit(f"[중단] {need} 가 없습니다: {session}")

    import cv2
    import open3d as o3d
    from ultralytics import YOLO

    meta = json.loads((session / "metadata.json").read_text(encoding="utf-8"))
    W, H = meta["video_frame_width"], meta["video_frame_height"]

    mesh = o3d.io.read_triangle_mesh(str(session / "scene_mesh.ply"))
    V = np.asarray(mesh.vertices)
    area = mesh.get_surface_area()
    print(f"메시    : {len(V):,} 정점 / 표면 {area:.1f} m^2")

    poses = load_poses(session)
    print(f"포즈    : {len(poses):,} 프레임 (tracking normal만)")

    # 모델 탐색: 지정 -> 현재 폴더 -> CAM/models (기존 프로젝트와 같은 가중치를 재사용)
    model_path = args.model
    if model_path is None:
        for cand in ["yolov8n.pt",
                     "../CAM/models/yolov8n.pt",
                     "../../CAM/models/yolov8n.pt"]:
            p = (Path.cwd() / cand).resolve()
            if p.exists():
                model_path = str(p)
                break
    model = YOLO(model_path or "yolov8n.pt")
    print(f"모델    : {model_path or 'yolov8n.pt (자동 다운로드)'}")

    cap = cv2.VideoCapture(str(session / "video.mov"))
    observations = defaultdict(list)
    n_det = n_loc = n_frames = 0
    idx = -1

    print(f"\n영상 처리 중 (stride={args.stride}, conf={args.conf}) ...")
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if idx % args.stride or idx not in poses:
            continue
        n_frames += 1
        res = model.predict(frame, conf=args.conf, verbose=False)[0]
        pose = poses[idx]
        for box in res.boxes:
            cls = model.names[int(box.cls)]
            conf = float(box.conf)
            bbox = [float(x) for x in box.xyxy[0]]
            n_det += 1
            pos, n_pts = localize(V, pose, bbox, W, H)
            if pos is None:
                continue
            n_loc += 1
            observations[cls].append({"pos": pos, "conf": conf, "frame": idx, "mesh_points": n_pts})
        if n_frames % 25 == 0:
            print(f"  {n_frames}프레임 / 검출 {n_det} / 3D확정 {n_loc}")
    cap.release()

    objects = cluster(observations)
    out = {
        "session_id": session.name,
        "model": Path(model_path or "yolov8n.pt").name,
        "coordinate_system": "ARKit world (right-handed, Y-up, meters) — scene_mesh.ply와 동일",
        "units": "meters (실제 미터. monocular SfM의 상대 좌표가 아니다)",
        "frames_processed": n_frames,
        "detections_total": n_det,
        "detections_localized": n_loc,
        "mesh_surface_area_m2": round(area, 2),
        "objects": objects,
        "note": ("3D 위치는 bbox로 투영되는 메시 정점의 median이다. 메시 커버리지가 낮으면 "
                 "localized 비율이 떨어진다 — 그건 검출 실패가 아니라 스캔 범위 부족이다."),
    }
    (session / "objects_3d.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*58}")
    print(f"  프레임 {n_frames} / 검출 {n_det} / 3D 확정 {n_loc}"
          f" ({100*n_loc/max(n_det,1):.0f}%)")
    print(f"  객체 {len(objects)}개")
    for o in objects[:12]:
        p = o["position_xyz"]
        star = " ★" if o["priority"] else ""
        print(f"    {o['class']:<15} ({p[0]:+.2f}, {p[1]:+.2f}, {p[2]:+.2f}) m"
              f"  관측 {o['num_observations']:>3}회  conf {o['avg_confidence']:.2f}{star}")
    print(f"\n  -> {session / 'objects_3d.json'}")
    print("="*58)


if __name__ == "__main__":
    main()
