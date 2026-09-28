#!/usr/bin/env python3
"""ARKit 세션 -> COLMAP 포맷 (SfM 없이).

우리는 ARKit에서 미터 단위 절대 포즈를 이미 갖고 있으므로 COLMAP의
Structure-from-Motion 단계를 통째로 건너뛴다. 이것이 일반 3DGS 파이프라인
대비 가장 큰 이점이다: 스케일이 실제 미터이고, 재구성 실패가 없다.

좌표 변환 (docs/coordinate_system.md 참조):
  ARKit: camera-to-world, 카메라는 -Z를 바라봄, Y가 위
  COLMAP: world-to-camera, 카메라는 +Z를 바라봄, Y가 아래
  => R_c = FLIP @ R.T,  t_c = -R_c @ t,  FLIP = diag([1,-1,-1])

주의: torch(ultralytics)와 open3d를 같은 프로세스에서 import하면 이 맥에서
멈추므로, 이 스크립트는 open3d만 쓴다 (torch 금지).
"""
import argparse, csv, json, sys
from pathlib import Path

import cv2
import numpy as np

FLIP = np.diag([1.0, -1.0, -1.0])


def quat_to_R(qx, qy, qz, qw):
    """쿼터니언 -> 3x3 회전행렬 (camera-to-world)."""
    n = np.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if n == 0:
        raise ValueError("0 노름 쿼터니언")
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ])


def R_to_quat(R):
    """3x3 회전행렬 -> (qw, qx, qy, qz). COLMAP은 QW가 먼저다."""
    tr = R[0, 0] + R[1, 1] + R[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        qw, qx, qy, qz = 0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        qw, qx, qy, qz = (R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        qw, qx, qy, qz = (R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s
    else:
        s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        qw, qx, qy, qz = (R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s
    return qw, qx, qy, qz


def load_poses(csv_path):
    """frame_index당 첫 행만 취한다 (ARKit이 같은 영상 프레임에 여러 번 붙을 수 있음)."""
    by_frame = {}
    skipped_tracking = 0
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            fi = int(row["frame_index"])
            if fi in by_frame:
                continue
            # tracking_state 2 = normal. limited/notAvailable 포즈는 3DGS를 망친다.
            if int(row["tracking_state"]) != 2:
                skipped_tracking += 1
                continue
            by_frame[fi] = row
    return by_frame, skipped_tracking


def read_ply_points(ply_path, max_points):
    """초기 점군. TSDF 메시 정점을 쓰면 3DGS가 랜덤 초기화보다 훨씬 빨리 수렴한다."""
    import open3d as o3d
    m = o3d.io.read_triangle_mesh(str(ply_path))
    pts = np.asarray(m.vertices)
    if len(pts) == 0:
        pc = o3d.io.read_point_cloud(str(ply_path))
        pts = np.asarray(pc.points)
        cols = np.asarray(pc.colors)
    else:
        cols = np.asarray(m.vertex_colors)
    if len(pts) == 0:
        raise SystemExit(f"점이 없음: {ply_path}")
    has_color = len(cols) == len(pts) and len(cols) > 0
    if not has_color:
        cols = np.full((len(pts), 3), 0.5)
    if len(pts) > max_points:
        idx = np.random.default_rng(0).choice(len(pts), max_points, replace=False)
        pts, cols = pts[idx], cols[idx]
    return pts, (np.asarray(cols) * 255).clip(0, 255).astype(np.uint8), has_color


def colorize_points(pts, poses, cams_by_frame, images_dir, names, W, H, max_frames=60):
    """정점 색을 영상 프레임에서 뽑는다 (TSDF 메시에 정점 색이 없을 때).

    각 정점을 여러 프레임에 투영해 중앙값 색을 취한다. 중앙값이므로 한 프레임에서
    사람에 가려져도 결과가 오염되지 않는다. 관측되지 않은 정점은 회색으로 남긴다
    — 보이지 않은 곳의 색을 지어내지 않는다는 원칙.
    """
    frames = sorted(names)
    step = max(1, len(frames) // max_frames)
    acc = [[] for _ in range(len(pts))]
    for fidx in frames[::step]:
        img = cv2.imread(str(images_dir / names[fidx]))
        if img is None:
            continue
        r = poses[fidx]
        fx, fy, cx, cy = (float(r["fx"]), float(r["fy"]), float(r["cx"]), float(r["cy"]))
        R = quat_to_R(float(r["qx"]), float(r["qy"]), float(r["qz"]), float(r["qw"]))
        t = np.array([float(r["tx"]), float(r["ty"]), float(r["tz"])])
        R_c = FLIP @ R.T
        pc = pts @ R_c.T + (-R_c @ t)
        m = pc[:, 2] > 0.1
        u = fx * pc[:, 0] / np.where(m, pc[:, 2], 1) + cx
        v = fy * pc[:, 1] / np.where(m, pc[:, 2], 1) + cy
        ok = m & (u >= 0) & (u < W) & (v >= 0) & (v < H)
        idxs = np.nonzero(ok)[0]
        bgr = img[v[ok].astype(int), u[ok].astype(int)]
        for i, c in zip(idxs, bgr):
            acc[i].append(c)
    out = np.full((len(pts), 3), 128, np.uint8)
    seen = 0
    for i, lst in enumerate(acc):
        if lst:
            b, g, r_ = np.median(np.array(lst), axis=0)
            out[i] = (r_, g, b)  # BGR -> RGB
            seen += 1
    print(f"  색 입힘: {seen:,}/{len(pts):,}점 ({seen/len(pts)*100:.0f}%), 나머지는 회색 유지")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--stride", type=int, default=1, help="N프레임마다 1장 (업로드 용량 절감)")
    ap.add_argument("--init-ply", default=None,
                    help="초기 점군용 PLY (미지정 시 아래 우선순위로 자동 선택)")
    ap.add_argument("--max-points", type=int, default=100_000)
    ap.add_argument("--jpeg-quality", type=int, default=92)
    args = ap.parse_args()

    sess, out = args.session, args.out
    pose_csv, video = sess / "arkit_pose.csv", sess / "video.mov"
    for p in (pose_csv, video):
        if not p.exists():
            sys.exit(f"❌ 필수 파일 없음: {p}")

    poses, skipped = load_poses(pose_csv)
    print(f"포즈: {len(poses)}개 프레임 (tracking 불량으로 제외 {skipped}개)")

    sparse = out / "sparse" / "0"
    images_dir = out / "images"
    sparse.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    # --- 영상 프레임 추출 ---
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        sys.exit(f"❌ 영상을 열 수 없음: {video}")
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    wanted = sorted(fi for fi in poses if fi % args.stride == 0)
    wanted_set = set(wanted)
    written = {}
    fi = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if fi in wanted_set:
            name = f"frame_{fi:05d}.jpg"
            cv2.imwrite(str(images_dir / name), frame,
                        [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
            written[fi] = name
        fi += 1
    cap.release()
    print(f"이미지: {len(written)}장 추출 ({W}x{H}, stride={args.stride})")
    if not written:
        sys.exit("❌ 추출된 프레임이 없다. arkit_pose.csv의 frame_index와 영상이 안 맞는다.")

    missing = wanted_set - written.keys()
    if missing:
        print(f"⚠️  포즈는 있으나 영상에 없는 프레임 {len(missing)}개는 건너뜀")

    # --- cameras.txt: 내부 파라미터가 프레임마다 미세하게 달라 이미지당 1대로 쓴다 ---
    with open(sparse / "cameras.txt", "w") as f:
        f.write("# Camera list with one line of data per camera:\n")
        f.write("#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        for cid, fidx in enumerate(sorted(written), start=1):
            r = poses[fidx]
            f.write(f"{cid} PINHOLE {W} {H} {r['fx']} {r['fy']} {r['cx']} {r['cy']}\n")

    # --- images.txt ---
    with open(sparse / "images.txt", "w") as f:
        f.write("# Image list with two lines of data per image:\n")
        f.write("#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
        f.write("#   POINTS2D[] as (X, Y, POINT3D_ID)\n")
        for iid, fidx in enumerate(sorted(written), start=1):
            r = poses[fidx]
            R = quat_to_R(float(r["qx"]), float(r["qy"]), float(r["qz"]), float(r["qw"]))
            t = np.array([float(r["tx"]), float(r["ty"]), float(r["tz"])])
            R_c = FLIP @ R.T
            t_c = -R_c @ t
            qw, qx, qy, qz = R_to_quat(R_c)
            f.write(f"{iid} {qw:.9f} {qx:.9f} {qy:.9f} {qz:.9f} "
                    f"{t_c[0]:.6f} {t_c[1]:.6f} {t_c[2]:.6f} {iid} {written[fidx]}\n")
            f.write("\n")  # 2D 대응점 없음 (SfM을 건너뛰었으므로)

    # --- points3D.txt ---
    # 초기 점군 자동 선택.
    # 뎁스 융합을 안 돌린 세션에는 fused_mesh.ply가 없다. 예전에는 그대로 빈 점군을
    # 써서 학습이 시작조차 못 했으므로, 있는 것 중 가장 조밀한 것을 고른다.
    #   fused_mesh(직접 융합) > fused_adaptive(적응형) > scene_mesh(ARKit, 가장 성김)
    if args.init_ply:
        init_ply = sess / args.init_ply
    else:
        init_ply = next((sess / n for n in
                         ("fused_mesh.ply", "fused_adaptive.ply", "scene_mesh.ply")
                         if (sess / n).exists()), sess / "fused_mesh.ply")
        print(f"초기 점군 자동 선택: {init_ply.name}")
    if init_ply.exists():
        pts, cols, has_color = read_ply_points(init_ply, args.max_points)
        if not has_color:
            print(f"  {init_ply.name}에 정점 색이 없다 -> 영상 프레임에서 추출")
            cols = colorize_points(pts, poses, None, images_dir, written, W, H)
        with open(sparse / "points3D.txt", "w") as f:
            f.write("# 3D point list with one line of data per point:\n")
            f.write("#   POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[]\n")
            for i, (p, c) in enumerate(zip(pts, cols), start=1):
                f.write(f"{i} {p[0]:.6f} {p[1]:.6f} {p[2]:.6f} {c[0]} {c[1]} {c[2]} 0.0\n")
        print(f"초기 점군: {len(pts):,}점 ({init_ply.name})")
    else:
        (sparse / "points3D.txt").write_text("")
        print(f"⚠️  {init_ply.name} 없음 -> 빈 점군 (3DGS가 랜덤 초기화로 시작하며 품질이 떨어진다)")

    (out / "arkit_export.json").write_text(json.dumps({
        "session": sess.name, "images": len(written), "width": W, "height": H,
        "stride": args.stride, "note": "ARKit 미터 포즈 사용, COLMAP SfM 생략",
    }, indent=2, ensure_ascii=False))
    print(f"\n✅ 완료: {out}")


if __name__ == "__main__":
    main()
