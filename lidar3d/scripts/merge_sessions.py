"""
두 대(이상)의 아이폰이 각자 찍은 세션을 하나의 3D로 병합한다.

왜 앱 수정이 필요 없는가:
  각 아이폰이 이미 **미터 단위로 완성된** 메시를 따로 만들어 온다. monocular 스테레오처럼
  두 카메라 사이 기선(baseline)을 IMU로 추정할 필요가 없다 — 스케일 미지수가 애초에 없다.
  남는 문제는 기선 추정이 아니라 **좌표계 정렬(registration)** 이고, 그건 전부 맥에서 한다.

미지수가 4개뿐인 이유 (이게 이 방법이 잘 되는 핵심):
  ARKit은 두 기기 모두 **중력으로 Y축을 정렬**한다. 그래서 roll/pitch는 애초에 어긋나지
  않고 **yaw(방위) + 평행이동 3개 = 4자유도**만 맞추면 된다. 6자유도보다 훨씬 안정적이다.
  (그래도 일반 6DOF 정합을 쓰는 이유는 Y 정렬 자체에도 미세 오차가 있기 때문이다.
   대신 아래에서 회복된 roll/pitch가 큰지 검사해 정합이 엉뚱하게 튄 경우를 걸러낸다.)

⚠️ 중첩(ghosting) 경고 — documents/warning/0917v1_2148_현장 3D 중첩 문제.md 1번:
  두 스캔이 서로 다른 시각에 이뤄졌다면, 그 사이 움직인 것(사람!)이 **두 겹으로** 남는다.
  정지 구조물(벽/바닥/출입구)은 완벽히 겹쳐서 결과가 멀쩡해 보이므로 더 위험하다.
  병합 결과는 **정지 구조물 파악용으로만** 신뢰할 것.

사용법:
  python3 scripts/merge_sessions.py <세션A> <세션B> [<세션C> ...] [--voxel 0.06] [--out 이름]

  예)
    python3 scripts/merge_sessions.py \
        server/sessions/session_A server/sessions/session_B

생성되는 것:
  server/sessions/merged_<타임스탬프>/  (뷰어에서 바로 열린다)
    ├── scene_mesh.ply
    ├── scene_mesh_faces_class.bin
    └── metadata.json   (정합 품질, 원본 세션, 경고가 전부 기록됨)

성공/실패 판단:
  - fitness < 0.15  -> 두 스캔이 겹치지 않는다. 정합 실패. 겹치는 구간을 만들어 재촬영.
  - inlier RMSE > 5cm -> 정렬이 헐겁다. 결과 좌표를 정밀 용도로 쓰지 말 것.
  - 회복된 roll/pitch가 크면(>5도) 중력축이 안 맞는 것 = 정합이 엉뚱한 해로 빠진 것.
"""

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import open3d as o3d

CLASS_NAMES = ["none", "wall", "floor", "ceiling", "table", "seat", "window", "door"]
# MeshExporter.swift의 classPalette와 동일해야 한다 (한쪽만 고치면 색과 라벨이 어긋난다)
PALETTE = [(130, 130, 130), (200, 200, 190), (90, 140, 90), (90, 110, 180),
           (200, 150, 60), (180, 90, 180), (90, 200, 220), (230, 40, 40)]


def load_session(path: Path):
    mesh = o3d.io.read_triangle_mesh(str(path / "scene_mesh.ply"))
    if len(mesh.vertices) == 0:
        raise SystemExit(f"[중단] 메시가 비어 있습니다: {path}")
    cls_file = path / "scene_mesh_faces_class.bin"
    cls = np.fromfile(cls_file, dtype=np.uint8) if cls_file.exists() else None
    ntri = len(mesh.triangles)
    if cls is None or len(cls) < ntri:
        # 분류가 없거나 짧으면 none(0)으로 채운다. 병합 자체는 계속 진행한다.
        cls = np.zeros(ntri, dtype=np.uint8) if cls is None else \
            np.pad(cls[:ntri], (0, max(0, ntri - len(cls))))
    meta = {}
    mp = path / "metadata.json"
    if mp.exists():
        meta = json.loads(mp.read_text(encoding="utf-8"))
    return mesh, cls[:ntri], meta


def start_pose_prior(meta_ref, meta_src):
    """
    두 세션의 'START 시점 기준 자세'로 초기 정렬 행렬을 만든다.

    왜 이게 강력한가:
      ARKit world 원점은 **앱 화면이 뜬 자리**이지 START를 누른 자리가 아니다. 그래서 두
      대원이 같은 곳에서 출발해도 좌표계는 전혀 안 맞는다 (실측: 각각 원점에서 4.5m / 7.0m).
      하지만 START 시점 자세를 알면, 두 사람이 **같은 자리에서 START만 눌러도**
      두 좌표계의 관계가 그 차이로 거의 그대로 나온다. 전역 탐색이 눈감고 찾을 필요가 없다.

    yaw만 쓰는 이유: 중력 정렬로 roll/pitch는 이미 일치한다. 폰을 든 기울기까지 넣으면
    좌표계 관계에 없는 기울기를 끌어들여 오히려 어긋난다.

    두 세션 중 하나라도 이 정보가 없으면(구버전 앱으로 찍은 세션) None을 돌려주고,
    호출부는 기존 전역 정합으로 넘어간다 — 옛 데이터도 계속 병합된다.
    """
    def frame(meta):
        t = meta.get("session_start_pose_translation")
        y = meta.get("session_start_pose_yaw_rad")
        if not t or y is None:
            return None
        c, s_ = np.cos(y), np.sin(y)
        T = np.eye(4)
        T[:3, :3] = [[c, 0, s_], [0, 1, 0], [-s_, 0, c]]
        T[:3, 3] = t
        return T

    Fr, Fs = frame(meta_ref), frame(meta_src)
    if Fr is None or Fs is None:
        return None
    # src 좌표계의 점을 ref 좌표계로: (ref의 START 프레임) * (src의 START 프레임)^-1
    return Fr @ np.linalg.inv(Fs)


def refine_from(source, target, T_init, voxel):
    """주어진 초기값에서 거칠게 -> 정밀하게 ICP. 매 단계 yaw만 남기도록 사영한다."""
    T = np.array(T_init, copy=True)
    est = o3d.pipelines.registration.TransformationEstimationPointToPlane()
    for threshold in (voxel * 8, voxel * 4, voxel * 2, voxel * 1.4):
        T = project_to_yaw(T)
        T = np.array(o3d.pipelines.registration.registration_icp(
            source, target, threshold, T, est).transformation, copy=True)
    T = project_to_yaw(T)
    return o3d.pipelines.registration.evaluate_registration(source, target, voxel * 1.4, T), T


def prepare(pcd, voxel):
    down = pcd.voxel_down_sample(voxel)
    down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 2, max_nn=30))
    fpfh = o3d.pipelines.registration.compute_fpfh_feature(
        down, o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 5, max_nn=100))
    return down, fpfh


def project_to_yaw(T):
    """
    회전을 **Y축 회전(yaw)만** 남기도록 사영한다.

    왜 이렇게까지 하는가:
      ARKit은 두 기기 모두 중력으로 Y축을 정렬하므로, 물리적으로 roll/pitch 차이는 0이어야 한다.
      그런데 일반 6자유도 정합에 맡기면 그 사실을 모르는 채로 탐색하다가, 겹침이 적을 때
      **기울어진 엉뚱한 해**로 빠진다 (실측: 중력축이 20.8° 기운 해를 찾아냄).
      아는 물리를 제약으로 넣으면 탐색 공간이 6 -> 4자유도로 줄어 훨씬 안정적이다.
    """
    R = T[:3, :3]
    # 전방벡터의 수평 성분으로 yaw를 뽑는다 (기울기 성분은 버린다)
    yaw = np.arctan2(R[0, 2], R[2, 2])
    c, s = np.cos(yaw), np.sin(yaw)
    out = np.eye(4)
    out[:3, :3] = [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    out[:3, 3] = T[:3, 3]
    return out


def register(source, target, voxel, yaw_only=True, attempts=3):
    """
    전역 정합(RANSAC+FPFH) -> ICP 정밀화. yaw_only면 매 단계 4자유도로 사영한다.

    ⚠️ 왜 여러 번 시도하는가 (실측으로 드러난 문제):
      RANSAC은 확률적이라 **같은 입력에 대해 실행마다 다른 답**을 낸다. 실제로 겹침이
      애매한 두 세션에서 fitness가 0.047(거부)과 0.189(병합)로 갈렸다. 즉 "합치면 안 되는
      것을 가끔 합치는" 상태였다 — 결과가 그럴듯해 보이므로 가장 위험한 실패 모드다.
      (이 버전의 Open3D RANSAC에는 seed 인자가 없어 난수를 고정할 수 없다.)

      그래서 N회 시도해 **최선을 고르고, 시도 간 편차를 함께 보고**한다.
      편차가 크면 그 자체가 "이 두 스캔은 안정적으로 겹치지 않는다"는 신호다.
    """
    results = []
    for _ in range(max(1, attempts)):
        results.append(_register_once(source, target, voxel, yaw_only))
    # fitness 높고 RMSE 낮은 것을 최선으로
    best = max(results, key=lambda r: (r[0].fitness, -r[0].inlier_rmse))
    spread = {
        "attempts": len(results),
        "fitness_min": round(min(r[0].fitness for r in results), 4),
        "fitness_max": round(max(r[0].fitness for r in results), 4),
    }
    return best[0], best[1], spread


def _register_once(source, target, voxel, yaw_only):
    sd, sf = prepare(source, voxel)
    td, tf = prepare(target, voxel)
    coarse = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
        sd, td, sf, tf, True, voxel * 1.5,
        o3d.pipelines.registration.TransformationEstimationPointToPoint(False), 3,
        [o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
         o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(voxel * 1.5)],
        o3d.pipelines.registration.RANSACConvergenceCriteria(400000, 0.999))

    T = coarse.transformation
    est = o3d.pipelines.registration.TransformationEstimationPointToPlane()
    if not yaw_only:
        fine = o3d.pipelines.registration.registration_icp(source, target, voxel * 1.4, T, est)
        return fine, fine.transformation

    # 사영 <-> ICP를 번갈아 돌려 4자유도 해로 수렴시킨다.
    # (Open3D에 yaw 전용 추정기가 없어서 이렇게 교대로 푼다.)
    fine = None
    for _ in range(6):
        T = project_to_yaw(T)
        fine = o3d.pipelines.registration.registration_icp(source, target, voxel * 1.4, T, est)
        T = fine.transformation
    T = project_to_yaw(T)
    # 사영 후의 실제 품질을 다시 잰다 (사영으로 조금 나빠질 수 있으므로 정직하게 재평가)
    return o3d.pipelines.registration.evaluate_registration(source, target, voxel * 1.4, T), T


def decompose(T):
    """정합 결과에서 yaw / roll·pitch / 평행이동을 뽑아 건전성을 검사한다."""
    R = T[:3, :3]
    yaw = np.degrees(np.arctan2(R[0, 2], R[2, 2]))
    # 중력축(Y)이 얼마나 기울었는가 — 커지면 정합이 엉뚱한 해로 빠진 것이다
    tilt = np.degrees(np.arccos(np.clip(R[1, 1], -1, 1)))
    return yaw, tilt, T[:3, 3]


def write_ply(path: Path, V, N, C, F, FC):
    """MeshExporter.swift가 쓰는 것과 **동일한** PLY 포맷으로 내보낸다 (뷰어가 그대로 읽는다)."""
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        "comment Merged from multiple LiDAR_Space3D sessions (scripts/merge_sessions.py)\n"
        "comment Coordinate system: ARKit world of the FIRST session (reference). meters.\n"
        "comment WARNING: moving objects may appear duplicated (ghosting). Static structure only.\n"
        "comment Face 'classification' = ARMeshClassification: "
        + " ".join(f"{i}={n}" for i, n in enumerate(CLASS_NAMES)) + "\n"
        f"element vertex {len(V)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property float nx\nproperty float ny\nproperty float nz\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        f"element face {len(F)}\n"
        "property list uchar uint vertex_indices\nproperty uchar classification\nend_header\n")

    body = bytearray()
    for i in range(len(V)):
        body += np.asarray(V[i], dtype="<f4").tobytes()
        body += np.asarray(N[i], dtype="<f4").tobytes()
        body += bytes(C[i])
    for i in range(len(F)):
        body += b"\x03" + np.asarray(F[i], dtype="<u4").tobytes() + bytes([FC[i]])
    path.write_bytes(header.encode() + bytes(body))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+", type=Path)
    ap.add_argument("--voxel", type=float, default=0.06, help="정합 해상도(m). 크게 하면 빠르고 거칠다")
    ap.add_argument("--out", default=None, help="출력 폴더 이름")
    ap.add_argument("--min-fitness", type=float, default=0.15,
                    help="이 값 미만이면 겹치지 않는 것으로 보고 중단")
    ap.add_argument("--attempts", type=int, default=3,
                    help="전역 정합 시도 횟수. RANSAC이 확률적이라 여러 번 돌려 최선을 고른다")
    ap.add_argument("--max-rmse", type=float, default=0.03,
                    help="이 값(m)을 넘으면 정렬이 헐거운 것으로 보고 거부")
    ap.add_argument("--no-prior", action="store_true",
                    help="START 기준 자세를 쓰지 않고 전역 탐색만 한다 (비교/디버그용)")
    ap.add_argument("--no-yaw-lock", action="store_true",
                    help="중력축 제약을 풀고 일반 6자유도로 정합 (권장하지 않음 — 엉뚱한 해로 잘 빠진다)")
    args = ap.parse_args()

    if len(args.sessions) < 2:
        raise SystemExit("[중단] 세션을 2개 이상 지정하세요")

    paths = [p.resolve() for p in args.sessions]
    ref_mesh, ref_cls, ref_meta = load_session(paths[0])
    has_prior_ref = ref_meta.get("session_start_pose_yaw_rad") is not None
    ref_mesh.compute_vertex_normals()
    print(f"기준 세션: {paths[0].name}")
    print(f"  정점 {len(ref_mesh.vertices):,}  면 {len(ref_mesh.triangles):,}  "
          f"표면 {ref_mesh.get_surface_area():.1f} m^2\n")

    V = [np.asarray(ref_mesh.vertices)]
    N = [np.asarray(ref_mesh.vertex_normals)]
    F = [np.asarray(ref_mesh.triangles)]
    FC = [ref_cls]
    reports = [{"session": paths[0].name, "role": "reference"}]
    ref_pcd = ref_mesh.sample_points_uniformly(number_of_points=60000)

    for p in paths[1:]:
        mesh, cls, src_meta = load_session(p)
        mesh.compute_vertex_normals()
        print(f"정합 중: {p.name} -> {paths[0].name}")
        src = mesh.sample_points_uniformly(number_of_points=60000)

        # ① START 기준 자세가 양쪽에 있으면 그걸 초기값으로 먼저 시도한다 (훨씬 안정적이다).
        prior_res = None
        prior = None if args.no_prior else start_pose_prior(ref_meta, src_meta)
        if prior is not None:
            prior_res, prior_T = refine_from(src, ref_pcd, prior, args.voxel)
            print(f"  [START 기준 정렬] fitness {prior_res.fitness:.3f}  "
                  f"RMSE {prior_res.inlier_rmse*100:.1f} cm")

        # ② 전역 탐색(RANSAC)도 돌려서 더 나은 쪽을 쓴다.
        res, T_final, spread = register(src, ref_pcd, args.voxel,
                                        yaw_only=not args.no_yaw_lock,
                                        attempts=args.attempts)
        print(f"  [전역 탐색]      fitness {res.fitness:.3f}  RMSE {res.inlier_rmse*100:.1f} cm")

        used = "global"
        if prior_res is not None and (prior_res.fitness, -prior_res.inlier_rmse) > (res.fitness, -res.inlier_rmse):
            res, T_final, used = prior_res, prior_T, "start_pose_prior"
            spread = dict(spread, prior_used=True)
        print(f"  -> 채택: {'START 기준 정렬' if used == 'start_pose_prior' else '전역 탐색'}")
        yaw, tilt, t = decompose(T_final)

        print(f"  fitness {res.fitness:.3f}   inlier RMSE {res.inlier_rmse*100:.1f} cm")
        print(f"  시도 {spread['attempts']}회 fitness 범위 "
              f"{spread['fitness_min']:.3f}~{spread['fitness_max']:.3f}")
        print(f"  회복된 yaw {yaw:+.1f}°   중력축 기울기 {tilt:.2f}°   평행이동 {np.round(t,2)}")

        ok = True
        warn = []
        if res.fitness < args.min_fitness:
            warn.append(f"fitness {res.fitness:.3f} < {args.min_fitness} — 두 스캔이 겹치지 않습니다")
            ok = False
        if res.inlier_rmse > args.max_rmse:
            # 경고가 아니라 **거부**다. 헐겁게 맞춘 결과는 벽이 겹쳐 보여서 정상처럼 읽히는데,
            # 실제 좌표는 수 cm씩 틀려 있다. 의료/구조 판단에 쓰기에는 위험하다.
            warn.append(f"RMSE {res.inlier_rmse*100:.1f}cm > {args.max_rmse*100:.0f}cm — 정렬이 헐겁습니다")
            ok = False
        if spread["fitness_max"] - spread["fitness_min"] > 0.10:
            warn.append(f"시도 간 fitness 편차가 큽니다 "
                        f"({spread['fitness_min']:.3f}~{spread['fitness_max']:.3f}) — "
                        f"안정적으로 겹치지 않습니다")
            ok = False
        if tilt > 5.0:
            warn.append(f"중력축 기울기 {tilt:.1f}° — 정합이 엉뚱한 해로 빠졌을 수 있습니다")
            ok = False
        for w in warn:
            print(f"  ⚠️  {w}")
        if not ok:
            print(f"  ❌ {p.name} 병합 제외\n")
            reports.append({"session": p.name, "role": "rejected",
                            "fitness": round(res.fitness, 4),
                            "rmse_m": round(res.inlier_rmse, 4),
                            "attempt_spread": spread, "warnings": warn})
            continue

        moved = copy.deepcopy(mesh).transform(T_final)
        offset = sum(len(v) for v in V)
        V.append(np.asarray(moved.vertices))
        N.append(np.asarray(moved.vertex_normals))
        F.append(np.asarray(moved.triangles) + offset)
        FC.append(cls)
        print(f"  ✅ 병합됨 (+{len(moved.vertices):,} 정점)\n")
        reports.append({"session": p.name, "role": "merged", "fitness": round(res.fitness, 4),
                        "rmse_m": round(res.inlier_rmse, 4), "yaw_deg": round(float(yaw), 2),
                        "gravity_tilt_deg": round(float(tilt), 3),
                        "translation_m": [round(float(x), 3) for x in t],
                        "attempt_spread": spread, "method": used, "warnings": warn})

    V = np.vstack(V); N = np.vstack(N); F = np.vstack(F); FC = np.concatenate(FC)
    # 정점 색 = 분류색. 값이 큰 클래스가 이긴다 (door가 벽에 덮이지 않게 — MeshExporter와 동일 규칙)
    C = np.array([PALETTE[0]] * len(V), dtype=np.uint8)
    vcls = np.zeros(len(V), dtype=np.uint8)
    for tri, c in zip(F, FC):
        if c == 0:
            continue
        for vi in tri:
            if c > vcls[vi]:
                vcls[vi] = c
                C[vi] = PALETTE[c]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = paths[0].parent / (args.out or f"merged_{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)
    write_ply(out_dir / "scene_mesh.ply", V, N, C, F, FC)
    FC.astype(np.uint8).tofile(out_dir / "scene_mesh_faces_class.bin")

    merged = o3d.io.read_triangle_mesh(str(out_dir / "scene_mesh.ply"))
    bb = merged.get_axis_aligned_bounding_box()
    ext = bb.get_extent()
    counts = {CLASS_NAMES[i]: int((FC == i).sum()) for i in range(8) if (FC == i).sum()}

    meta = {
        "session_id": out_dir.name,
        "capture_mode": "lidar_arkit_merged",
        "schema_version": 2,
        "reconstruction_required": False,
        "primary_model_file": "scene_mesh.ply",
        "source_sessions": [p.name for p in paths],
        "registration": reports,
        "registration_voxel_m": args.voxel,
        "registration_dof": 6 if args.no_yaw_lock else 4,
        "registration_note": ("ARKit이 두 기기 모두 중력으로 Y축을 정렬하므로 "
                              "yaw + 평행이동 4자유도로 제약해 정합했다."),
        "coordinate_system": f"ARKit world of {paths[0].name} (reference). Y-up, meters.",
        "mesh_vertex_count": len(V),
        "mesh_face_count": len(F),
        "mesh_extent_meters": [float(x) for x in ext],
        "mesh_bounds_min": [float(x) for x in bb.min_bound],
        "mesh_bounds_max": [float(x) for x in bb.max_bound],
        "mesh_surface_area_m2": round(merged.get_surface_area(), 2),
        "mesh_class_face_counts": counts,
        "mesh_has_classification": bool((FC > 0).any()),
        "mesh_classification_legend": {n: i for i, n in enumerate(CLASS_NAMES)},
        "session_start_wallclock_iso8601": datetime.now(timezone.utc).isoformat(),
        "ghosting_warning": (
            "서로 다른 시각에 촬영된 세션을 병합했다면 움직인 물체(사람 등)가 두 겹으로 "
            "남을 수 있다. 정지 구조물(벽/바닥/출입구) 파악용으로만 신뢰할 것. "
            "documents/warning/0917v1_2148_현장 3D 중첩 문제.md 1번 참고."),
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 60)
    print(f"  병합 완료: {out_dir.name}")
    print(f"  정점 {len(V):,}  면 {len(F):,}  표면 {meta['mesh_surface_area_m2']} m^2")
    print(f"  공간 {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} m")
    print(f"  분류: " + ", ".join(f"{k}={v:,}" for k, v in sorted(counts.items())))
    print(f"\n  ⚠️  움직인 물체는 두 겹으로 남을 수 있습니다 (정지 구조물 파악용)")
    print(f"  뷰어: http://localhost:8000/viewer/?session={out_dir.name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
