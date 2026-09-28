"""
⚠️ 사용 금지 — 이 환경에서 완료되지 않는다.

open3d와 torch(YOLO)를 **한 프로세스에서 import**하면 CPU 0%로 무한 대기한다
(실측 확인). 아래 2단계 스크립트로 대체되었다.

  detect_objects_3d.py -> detect_stage1.py + detect_stage2.py
  fuse_adaptive.py     -> stage1_masks.py  + stage2_fuse.py

로직 참고용으로만 남긴다.
"""
적응형 해상도 융합 — 배경은 거칠게, 관심 객체(부상자)는 정밀하게.

왜 이렇게 하는가:
  응급현장에서 필요한 정밀도는 균일하지 않다.
    - 배경(벽/바닥/통로): "어디가 막혔나"만 알면 되므로 4cm 복셀로 충분하다.
    - 부상자: 자세·체위·출혈 부위를 봐야 하므로 1cm 복셀이 필요하다.
  전체를 1cm로 하면 메모리와 시간이 16배가 된다(복셀은 3차원이라 급격히 늘어난다).
  관심 영역에만 쓰면 **필요한 곳만 정밀하면서 전체는 빠르다.**

왜 ARKit 메시로는 불가능한가:
  ARKit은 균일한 격자(실측 3cm 고정)로만 메시를 만들고, 영역별 해상도 조절 API가 없다.
  융합을 직접 하기 때문에 생기는 능력이다.

⚠️ 동적 객체의 한계 (숨기지 않음):
  TSDF는 여러 프레임을 누적하므로 **움직이는 대상은 겹쳐 흐려진다.**
  부상자는 대체로 정지해 있지만 완전히 정지하진 않는다. 그래서 사람 영역은
  `--person-window`초 안의 프레임만 융합한다 (기본 3초). 짧을수록 선명하지만 구멍이 는다.
  완전히 움직이는 대상(구조대원)은 애초에 이 방식으로 재구성할 수 없다.

Android 이식 (이 스크립트는 플랫폼 독립적이다):
  입력은 "뎁스 + intrinsics + 포즈"뿐이고 ARKit 고유 형식을 쓰지 않는다.
  ARCore의 Depth API도 같은 것을 주므로, 안드로이드 앱이 동일한 파일 규약으로
  저장하기만 하면 이 스크립트가 그대로 동작한다.
  필요한 규약은 docs/ 의 입력 계약 문서 참고.

사용법:
  python3 scripts/fuse_adaptive.py <세션> [--bg-voxel 0.04] [--obj-voxel 0.01]
                                   [--classes person] [--person-window 3.0] [--stride 3]

생성:
  <세션>/fused_bg.ply       배경 (거친 복셀)
  <세션>/fused_objects.ply  관심 객체 (정밀 복셀)
  <세션>/fused_adaptive.ply 둘을 합친 것 (뷰어용)
"""

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np
import open3d as o3d


def quat_to_R(x, y, z, w):
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w)],
        [2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y)],
    ])


def clean_depth(d, K, max_depth, edge_ratio=0.04, min_cos=0.25):
    """신뢰도 맵 없이 나쁜 깊이를 거른다 (fuse_depth.py와 동일 규칙)."""
    d = d.copy()
    d[(d <= 0) | (d > max_depth)] = 0
    if not (d > 0).any():
        return d
    pad = np.pad(d, 1, mode="edge")
    nb = np.stack([pad[:-2, 1:-1], pad[2:, 1:-1], pad[1:-1, :-2], pad[1:-1, 2:]])
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.abs(nb - d[None]) / np.maximum(d[None], 1e-6)
    d[np.nanmax(np.where(nb > 0, rel, 0), axis=0) > edge_ratio] = 0
    fx, fy = K[0], K[1]
    gy, gx = np.gradient(np.where(d > 0, d, np.nan))
    with np.errstate(invalid="ignore"):
        slope = np.sqrt((gx * fx / np.maximum(d, 1e-6)) ** 2
                        + (gy * fy / np.maximum(d, 1e-6)) ** 2)
        cos_inc = 1.0 / np.sqrt(1.0 + slope ** 2)
    d[np.nan_to_num(cos_inc, nan=0.0) < min_cos] = 0
    return d


def integrate(vol, depth, K, T, W, H, maxd):
    intr = o3d.camera.PinholeCameraIntrinsic(W, H, K[0], K[1], K[2], K[3])
    rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
        o3d.geometry.Image(np.zeros((H, W, 3), dtype=np.uint8)),
        o3d.geometry.Image(np.ascontiguousarray(depth)),
        depth_scale=1.0, depth_trunc=maxd, convert_rgb_to_intensity=False)
    vol.integrate(rgbd, intr, np.linalg.inv(T))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path)
    ap.add_argument("--bg-voxel", type=float, default=0.04, help="배경 복셀(m). 클수록 빠르고 거칠다")
    ap.add_argument("--obj-voxel", type=float, default=0.01, help="관심 객체 복셀(m)")
    ap.add_argument("--maxd", type=float, default=4.0)
    ap.add_argument("--classes", default="person",
                    help="정밀 재구성할 COCO 클래스 (쉼표 구분). 예: person,chair")
    ap.add_argument("--person-window", type=float, default=3.0,
                    help="객체 영역에 쓸 시간 창(초). 짧을수록 선명하고 구멍이 는다")
    ap.add_argument("--stride", type=int, default=3, help="YOLO를 N프레임마다 실행 (속도)")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    import cv2
    from ultralytics import YOLO

    sess = args.session.resolve()
    meta = json.loads((sess / "metadata.json").read_text(encoding="utf-8"))
    W, H = meta["depth_width"], meta["depth_height"]
    vw, vh = meta["video_frame_width"], meta["video_frame_height"]
    sx, sy = W / vw, H / vh
    targets = {c.strip() for c in args.classes.split(",") if c.strip()}

    poses = {r["timestamp"]: r for r in csv.DictReader(open(sess / "arkit_pose.csv"))}
    rows = list(csv.DictReader(open(sess / "depth" / "index.csv")))

    model_path = args.model
    if model_path is None:
        for c in ["yolov8n.pt", "../CAM/models/yolov8n.pt", "CAM/models/yolov8n.pt"]:
            if (Path.cwd() / c).exists():
                model_path = str((Path.cwd() / c).resolve()); break
    model = YOLO(model_path or "yolov8n.pt")

    # 영상 프레임을 미리 읽어 둔다 (depth의 video_frame_index로 참조)
    print("  영상 디코딩 + 객체 검출 중…")
    t0 = time.time()
    masks = {}                       # video_frame_index -> 뎁스 해상도 마스크(bool)
    cap = cv2.VideoCapture(str(sess / "video.mov"))
    wanted = {int(r["video_frame_index"]) for r in rows if int(r["video_frame_index"]) >= 0}
    idx = -1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if idx not in wanted or (idx // max(args.stride, 1)) * max(args.stride, 1) != idx:
            continue
        res = model.predict(frame, conf=args.conf, verbose=False)[0]
        mask = np.zeros((H, W), dtype=bool)
        for b in res.boxes:
            if model.names[int(b.cls)] not in targets:
                continue
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            # 영상 좌표 -> 뎁스 좌표. 두 영상은 같은 4:3이라 단순 스케일로 맞는다.
            mask[max(0, int(y1 * sy)):min(H, int(y2 * sy) + 1),
                 max(0, int(x1 * sx)):min(W, int(x2 * sx) + 1)] = True
        masks[idx] = mask
    cap.release()
    n_with_obj = sum(1 for m in masks.values() if m.any())
    print(f"  검출 완료 ({time.time()-t0:.0f}초): {len(masks)}프레임 검사, {n_with_obj}프레임에서 {args.classes} 발견")

    # 객체가 처음 보인 시각 — 그로부터 person-window 초만 객체 융합에 쓴다
    obj_times = [float(r["timestamp"]) for r in rows
                 if int(r["video_frame_index"]) in masks and masks[int(r["video_frame_index"])].any()]
    t_start = min(obj_times) if obj_times else None

    bg = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=args.bg_voxel, sdf_trunc=args.bg_voxel * 3,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor)
    obj = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=args.obj_voxel, sdf_trunc=args.obj_voxel * 3,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor)

    t1 = time.time()
    n_bg = n_obj = 0
    last_mask = np.zeros((H, W), dtype=bool)
    for r in rows:
        p = poses.get(r["timestamp"])
        if p is None or p["tracking_state"] != "2":
            continue
        path = sess / "depth" / r["depth_file"]
        if not path.exists():
            continue
        d = np.fromfile(path, dtype="<f4").reshape(H, W)
        K = [float(p["fx"]) * sx, float(p["fy"]) * sy, float(p["cx"]) * sx, float(p["cy"]) * sy]
        d = clean_depth(d, K, args.maxd)
        if (d > 0).sum() < 200:
            continue
        R = quat_to_R(*[float(p[k]) for k in ("qx", "qy", "qz", "qw")])
        t = np.array([float(p[k]) for k in ("tx", "ty", "tz")])
        T = np.eye(4); T[:3, :3] = R @ np.diag([1.0, -1.0, -1.0]); T[:3, 3] = t

        vfi = int(r["video_frame_index"])
        # YOLO를 stride로 돌렸으므로 마스크가 없는 프레임은 직전 것을 쓴다
        # (10Hz 간격이면 사람은 거의 안 움직인다).
        if vfi in masks:
            last_mask = masks[vfi]
        mask = last_mask

        # 배경: 객체 영역을 빼고 전부
        d_bg = d.copy(); d_bg[mask] = 0
        if (d_bg > 0).sum() >= 200:
            integrate(bg, d_bg, K, T, W, H, args.maxd); n_bg += 1

        # 객체: 마스크 안쪽만, 그리고 시간 창 안쪽만
        if mask.any() and t_start is not None and \
           float(r["timestamp"]) - t_start <= args.person_window:
            d_ob = d.copy(); d_ob[~mask] = 0
            if (d_ob > 0).sum() >= 100:
                integrate(obj, d_ob, K, T, W, H, args.maxd); n_obj += 1

    mesh_bg = bg.extract_triangle_mesh(); mesh_bg.compute_vertex_normals()
    mesh_ob = obj.extract_triangle_mesh(); mesh_ob.compute_vertex_normals()

    # 색으로 구분: 배경은 회색, 정밀 객체는 빨강 (뷰어에서 한눈에 보이게)
    mesh_bg.paint_uniform_color([0.55, 0.57, 0.60])
    mesh_ob.paint_uniform_color([0.90, 0.16, 0.16])

    o3d.io.write_triangle_mesh(str(sess / "fused_bg.ply"), mesh_bg)
    o3d.io.write_triangle_mesh(str(sess / "fused_objects.ply"), mesh_ob)
    o3d.io.write_triangle_mesh(str(sess / "fused_adaptive.ply"), mesh_bg + mesh_ob)

    print(f"\n  융합 완료 ({time.time()-t1:.0f}초)")
    print(f"    배경  ({args.bg_voxel*100:.0f}cm 복셀, {n_bg}프레임): "
          f"{len(mesh_bg.vertices):>8,}정점  {mesh_bg.get_surface_area():7.1f} m²")
    print(f"    객체  ({args.obj_voxel*100:.0f}cm 복셀, {n_obj}프레임): "
          f"{len(mesh_ob.vertices):>8,}정점  {mesh_ob.get_surface_area():7.1f} m²")
    if n_obj == 0:
        print(f"    ⚠️ 객체 프레임 0 — {args.classes}가 검출되지 않았거나 시간 창 밖입니다")
    print(f"  -> {sess/'fused_adaptive.ply'}")


if __name__ == "__main__":
    main()
