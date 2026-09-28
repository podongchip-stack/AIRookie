"""
뎁스 + 포즈로 3D를 **직접 융합**한다 (ARKit 메시를 쓰지 않는다).

왜 이 방법이 필요한가 (실측으로 확정된 사실):
  같은 방·같은 시각에 두 기기를 찍었더니 ARKit이 매기는 **뎁스 신뢰도**가 갈렸다.
    iPhone 15 Pro (iOS 26.6.1): "높음" **0.00%**  -> 메시 거의 안 만들어짐
    iPhone 12 Pro (iOS 26.2.1): "높음" **73.56%** -> 메시 정상
  그런데 15 Pro의 **뎁스 값 자체는 멀쩡하다** (0.53~8.57m로 오히려 더 멀리 나온다).
  ARKit이 그걸 전부 "믿을 수 없음"으로 판정할 뿐이다. 즉 데이터가 아니라 **판정이 문제**다.
  평활 뎁스(smoothedSceneDepth)도 신뢰도 맵이 원시와 완전히 동일해서 해결이 안 됐다.

  그래서 신뢰도에 의존하지 않고, **기하학적 일관성만으로** 나쁜 점을 걸러 융합한다.

Android로 가기 위해서도 이 방향이 맞다:
  ARKit 메시에 의존하면 플랫폼마다 결과가 달라진다. ARCore(Depth API)도 뎁스와 포즈는 주므로,
  융합을 우리가 하면 **같은 파이프라인으로 두 플랫폼을 처리**할 수 있다.

필터 (신뢰도 대신 쓰는 것들):
  1. 거리 상한        — 멀수록 LiDAR 오차가 제곱으로 커진다
  2. 이웃 일관성      — 주변 픽셀과 깊이가 크게 어긋나면 잘못 측정된 점이다
  3. 시선 입사각      — 표면을 스치듯 보면 깊이가 부정확하다
  4. 다중 관측 합의   — TSDF가 여러 프레임을 누적하므로, 한 프레임만 본 곳은 신뢰도가 낮다

사용법:
  python3 scripts/fuse_depth.py server/sessions/<세션> [--voxel 0.02] [--maxd 4.0]
                                [--smoothed] [--no-filter]

생성:
  <세션>/fused_mesh.ply   (뷰어에서 열 수 있다)
"""

import argparse
import csv
import json
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
    """
    신뢰도 맵 없이 나쁜 깊이를 제거한다.

    ① 거리 상한: LiDAR 오차는 거리의 제곱에 비례해 커진다. 먼 점은 버린다.
    ② 이웃 일관성: 상하좌우 이웃과의 깊이 차가 자기 깊이의 edge_ratio를 넘으면
       물체 경계이거나 잘못 측정된 점이다. 경계의 '늘어진 삼각형'은 융합 품질을 크게 해친다.
    ③ 입사각: 표면을 스치듯 보면(법선과 시선이 거의 수직) 깊이 오차가 급증한다.
       국소 기울기로 근사해 걸러낸다.
    """
    d = d.copy()
    d[(d <= 0) | (d > max_depth)] = 0

    valid = d > 0
    if not valid.any():
        return d

    # ② 이웃 일관성
    pad = np.pad(d, 1, mode="edge")
    neighbors = np.stack([pad[:-2, 1:-1], pad[2:, 1:-1], pad[1:-1, :-2], pad[1:-1, 2:]])
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.abs(neighbors - d[None]) / np.maximum(d[None], 1e-6)
    bad_edge = (np.nanmax(np.where(neighbors > 0, rel, 0), axis=0) > edge_ratio)
    d[bad_edge] = 0

    # ③ 입사각 — 깊이 기울기가 크면 시선이 표면을 스치고 있다는 뜻이다
    fx, fy = K[0], K[1]
    gy, gx = np.gradient(np.where(d > 0, d, np.nan))
    with np.errstate(invalid="ignore"):
        # 픽셀당 실제 거리 -> 기울기를 각도로 환산
        slope = np.sqrt((gx * fx / np.maximum(d, 1e-6)) ** 2
                        + (gy * fy / np.maximum(d, 1e-6)) ** 2)
        cos_inc = 1.0 / np.sqrt(1.0 + slope ** 2)
    d[np.nan_to_num(cos_inc, nan=0.0) < min_cos] = 0
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path)
    ap.add_argument("--voxel", type=float, default=0.02, help="복셀 크기(m). 작을수록 정밀·느림")
    ap.add_argument("--maxd", type=float, default=4.0, help="이 거리(m)를 넘는 뎁스는 버린다")
    ap.add_argument("--smoothed", action="store_true", help="평활 뎁스(sdepth_*)를 쓴다")
    ap.add_argument("--no-filter", action="store_true", help="필터 없이 원본 그대로 융합 (비교용)")
    ap.add_argument("--out", default="fused_mesh.ply")
    args = ap.parse_args()

    sess = args.session.resolve()
    meta = json.loads((sess / "metadata.json").read_text(encoding="utf-8"))
    W, H = meta["depth_width"], meta["depth_height"]
    vw, vh = meta["video_frame_width"], meta["video_frame_height"]
    sx, sy = W / vw, H / vh                      # intrinsics는 영상 해상도 기준이라 뎁스로 스케일

    poses = {r["timestamp"]: r for r in csv.DictReader(open(sess / "arkit_pose.csv"))}
    rows = list(csv.DictReader(open(sess / "depth" / "index.csv")))

    vol = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=args.voxel, sdf_trunc=args.voxel * 3,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor)

    used = skipped = 0
    kept_px = total_px = 0
    for r in rows:
        p = poses.get(r["timestamp"])
        if p is None or p["tracking_state"] != "2":
            skipped += 1
            continue
        key = "smooth_depth_file" if args.smoothed else "depth_file"
        fname = r.get(key) or r["depth_file"]
        path = sess / "depth" / fname
        if not path.exists():
            skipped += 1
            continue

        d = np.fromfile(path, dtype="<f4").reshape(H, W)
        total_px += int((d > 0).sum())
        K = [float(p["fx"]) * sx, float(p["fy"]) * sy, float(p["cx"]) * sx, float(p["cy"]) * sy]
        d = d if args.no_filter else clean_depth(d, K, args.maxd)
        if args.no_filter:
            d = d.copy(); d[(d <= 0) | (d > args.maxd)] = 0
        kept_px += int((d > 0).sum())
        if (d > 0).sum() < 200:
            skipped += 1
            continue

        R = quat_to_R(*[float(p[k]) for k in ("qx", "qy", "qz", "qw")])
        t = np.array([float(p[k]) for k in ("tx", "ty", "tz")])
        # ARKit 카메라(-Z 전방, +Y 위) -> Open3D 카메라(+Z 전방, -Y 위)
        T = np.eye(4); T[:3, :3] = R @ np.diag([1.0, -1.0, -1.0]); T[:3, 3] = t

        intr = o3d.camera.PinholeCameraIntrinsic(W, H, K[0], K[1], K[2], K[3])
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.zeros((H, W, 3), dtype=np.uint8)),
            o3d.geometry.Image(np.ascontiguousarray(d)),
            depth_scale=1.0, depth_trunc=args.maxd, convert_rgb_to_intensity=False)
        vol.integrate(rgbd, intr, np.linalg.inv(T))
        used += 1

    mesh = vol.extract_triangle_mesh()
    mesh.compute_vertex_normals()

    # ④ 다중 관측 합의: 한두 프레임만 본 곳은 작은 조각으로 남는다. 그런 파편을 제거한다.
    if not args.no_filter and len(mesh.triangles) > 0:
        with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
            idx, ntri, area = mesh.cluster_connected_triangles()
        idx = np.asarray(idx); area = np.asarray(area)
        keep = area > 0.02                                   # 200 cm² 미만 조각 제거
        mesh.remove_triangles_by_mask(~keep[idx])
        mesh.remove_unreferenced_vertices()

    out = sess / args.out
    o3d.io.write_triangle_mesh(str(out), mesh)

    print(f"  프레임 {used}개 사용 / {skipped}개 제외")
    print(f"  픽셀 필터 통과율 {100*kept_px/max(total_px,1):.1f}%  ({kept_px:,}/{total_px:,})")
    print(f"  결과: {len(mesh.vertices):,}정점 / {len(mesh.triangles):,}면 / "
          f"표면 {mesh.get_surface_area():.1f} m²")
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
