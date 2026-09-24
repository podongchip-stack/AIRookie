"""두 기기(예: iPhone 15 Pro vs 12 Pro)로 찍은 세션을 같은 조건으로 재구성해 나란히 비교한다.

live4d 0단계 — 4D 고정 녹화에 두 기기를 모두 써도 되는지 판단하는 근거를 만든다.
ARKit이 폰 안에서 만든 메시(scene_mesh.ply)는 iOS 버전·기기마다 판정이 크게 갈리므로
(15 Pro 26.6.1은 뎁스 신뢰도 "높음" 0% → 메시가 거의 안 생김, 0918 실측), 비교의 본체는
**원자료(뎁스·포즈)를 Mac에서 같은 조건으로 융합한 결과**다. ARKit 메시는 참고로만 싣는다.

live4d는 lidar3d와 별개 모듈이다. 촬영 원본은 lidar3d 서버가 받은 세션 폴더를 **읽기만** 하고,
재구성은 lidar3d의 fuse_depth.py를 그대로 불러 쓴다(2cm 균일 TSDF, 4.0m, 기본 필터).
만들어지는 파일은 전부 live4d/data/ 아래에 둔다 — lidar3d 세션 폴더에는 아무것도 쓰지 않는다.
비교용 메시는 있으면 재사용한다(--refuse로 다시).

사용법 (저장소 루트에서):
  python3 live4d/scripts/compare_devices.py <세션A> <세션B> [--voxel 0.02] [--refuse]
  예) python3 live4d/scripts/compare_devices.py \
        lidar3d/server/sessions/session_A_iPhone15Pro lidar3d/server/sessions/session_B_iPhone12Pro

같은 장소·같은 경로·비슷한 시간 길이로 찍어야 공정하다. 결과는 표로 출력하고
live4d/data/compare/compare_<A>_vs_<B>.json 에도 남긴다.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

LIVE4D_DIR = Path(__file__).resolve().parents[1]
# 재구성은 lidar3d의 스크립트를 재사용한다(같은 조건 비교가 목적이라 따로 만들지 않는다).
LIDAR3D_SCRIPTS = LIVE4D_DIR.parent / "lidar3d" / "scripts"
OUT_DIR = LIVE4D_DIR / "data" / "compare"
COMPARE_MESH = "fused_compare.ply"


def _mesh_path(sess: Path) -> Path:
    """세션별 비교용 메시 위치 — live4d/data/compare/<세션이름>/fused_compare.ply"""
    return OUT_DIR / sess.name / COMPARE_MESH


def _ply_counts_and_area(path: Path) -> dict | None:
    """PLY의 정점·면 수와 표면적(m²). open3d가 없거나 파일이 없으면 None."""
    if not path.exists():
        return None
    import open3d as o3d  # 이 스크립트는 torch를 부르지 않으므로 같은 프로세스에서 안전하다

    mesh = o3d.io.read_triangle_mesh(str(path))
    if len(mesh.triangles) == 0:
        return {"vertices": len(mesh.vertices), "faces": 0, "area_m2": 0.0, "extent_m": [0, 0, 0]}
    bb = mesh.get_axis_aligned_bounding_box()
    return {
        "vertices": len(mesh.vertices),
        "faces": len(mesh.triangles),
        "area_m2": round(float(mesh.get_surface_area()), 1),
        "extent_m": [round(float(x), 2) for x in bb.get_extent()],
    }


def _capture_stats(sess: Path) -> dict:
    """촬영 품질: 트래킹·타임스탬프 정합·뎁스 유효/신뢰도·포즈 흔들림."""
    meta = json.loads((sess / "metadata.json").read_text(encoding="utf-8"))
    W, H = meta["depth_width"], meta["depth_height"]

    poses = list(csv.DictReader(open(sess / "arkit_pose.csv")))
    ts = np.array([float(p["timestamp"]) for p in poses])
    normal = np.array([p["tracking_state"] == "2" for p in poses])
    pos = np.array([[float(p[k]) for k in ("tx", "ty", "tz")] for p in poses])
    # 흔들림 지표: 위치의 2차 차분(가속 성분) 중앙값. 부드러운 이동이면 작고, 트래킹이 튀면 커진다.
    jitter_mm = float(np.median(np.linalg.norm(np.diff(pos, n=2, axis=0), axis=1)) * 1000) if len(pos) > 2 else None

    rows = list(csv.DictReader(open(sess / "depth" / "index.csv")))
    pose_ts = {p["timestamp"] for p in poses}
    joined = sum(1 for r in rows if r["timestamp"] in pose_ts)

    # 뎁스는 최대 60장만 고르게 뽑아 본다(전부 읽으면 느리고 경향은 같다).
    pick = rows[:: max(1, len(rows) // 60)]
    valid = within4 = total = 0
    depths: list[np.ndarray] = []
    conf_hist = np.zeros(3, dtype=np.int64)
    for r in pick:
        d = np.fromfile(sess / "depth" / r["depth_file"], dtype="<f4").reshape(H, W)
        total += d.size
        v = d > 0
        valid += int(v.sum())
        within4 += int(((d > 0) & (d <= 4.0)).sum())
        depths.append(d[v])
        cf = sess / "depth" / (r.get("conf_file") or "")
        if r.get("conf_file") and cf.exists():
            c = np.fromfile(cf, dtype=np.uint8)
            conf_hist += np.bincount(np.clip(c, 0, 2), minlength=3)
    alld = np.concatenate(depths) if depths else np.array([0.0])
    conf_total = int(conf_hist.sum()) or 1

    return {
        "device": meta.get("device", "?"),
        "ios": meta.get("ios_version", "?"),
        "duration_s": round(float(ts[-1] - ts[0]), 1) if len(ts) > 1 else 0.0,
        "pose_count": len(poses),
        "tracking_normal_pct": round(100 * float(normal.mean()), 1) if len(poses) else 0.0,
        "pose_jitter_mm": round(jitter_mm, 2) if jitter_mm is not None else None,
        "depth_frames": len(rows),
        "depth_hz": round(float(meta.get("depth_saved_hz_measured", 0)), 1),
        "depth_pose_join_pct": round(100 * joined / max(1, len(rows)), 1),
        "depth_res": f"{W}x{H}",
        "depth_valid_pct": round(100 * valid / max(1, total), 1),
        "depth_within4m_pct": round(100 * within4 / max(1, total), 1),
        "depth_median_m": round(float(np.median(alld)), 2),
        "depth_p95_m": round(float(np.percentile(alld, 95)), 2),
        "conf_low_pct": round(100 * conf_hist[0] / conf_total, 1),
        "conf_mid_pct": round(100 * conf_hist[1] / conf_total, 1),
        "conf_high_pct": round(100 * conf_hist[2] / conf_total, 1),
    }


def _fuse(sess: Path, voxel: float, refuse: bool) -> float | None:
    """fuse_depth.py로 비교용 메시를 만든다. 걸린 초를 돌려준다(재사용이면 None)."""
    out = _mesh_path(sess)
    if out.exists() and not refuse:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    # fuse_depth.py는 --out을 세션 폴더 기준으로 이어 붙이는데, 절대 경로를 주면 그 위치에 쓴다.
    cmd = [sys.executable, str(LIDAR3D_SCRIPTS / "fuse_depth.py"), str(sess),
           "--voxel", str(voxel), "--maxd", "4.0", "--out", str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ 융합 실패: {sess.name}\n{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        sys.exit(1)
    return round(time.time() - started, 1)


ROWS = [
    ("기기", "device"), ("iOS", "ios"),
    ("촬영 길이(초)", "duration_s"), ("포즈 수", "pose_count"),
    ("트래킹 정상 비율(%)", "tracking_normal_pct"), ("포즈 흔들림(mm, 작을수록 안정)", "pose_jitter_mm"),
    ("뎁스 프레임 수", "depth_frames"), ("뎁스 저장 Hz", "depth_hz"),
    ("뎁스↔포즈 시각 정확 일치(%)", "depth_pose_join_pct"), ("뎁스 해상도", "depth_res"),
    ("뎁스 유효 화소(%)", "depth_valid_pct"), ("뎁스 4m 이내 화소(%)", "depth_within4m_pct"),
    ("뎁스 중앙값(m)", "depth_median_m"), ("뎁스 95%(m)", "depth_p95_m"),
    ("ARKit 신뢰도 낮음(%)", "conf_low_pct"), ("ARKit 신뢰도 중간(%)", "conf_mid_pct"),
    ("ARKit 신뢰도 높음(%)", "conf_high_pct"),
    ("[참고] ARKit 메시 표면적(m²)", "arkit_area_m2"), ("[참고] ARKit 메시 면 수", "arkit_faces"),
    ("[본체] Mac 재구성 표면적(m²)", "fused_area_m2"), ("[본체] Mac 재구성 면 수", "fused_faces"),
    ("[본체] Mac 재구성 크기(m, x·y·z)", "fused_extent_m"), ("Mac 재구성 소요(초)", "fuse_seconds"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session_a", type=Path)
    ap.add_argument("session_b", type=Path)
    ap.add_argument("--voxel", type=float, default=0.02)
    ap.add_argument("--refuse", action="store_true", help="비교용 메시가 있어도 다시 융합")
    args = ap.parse_args()

    results = {}
    for sess in (args.session_a.resolve(), args.session_b.resolve()):
        print(f"… {sess.name}: 촬영 품질 분석")
        stats = _capture_stats(sess)
        print(f"… {sess.name}: Mac 재구성 (voxel {args.voxel}m)")
        stats["fuse_seconds"] = _fuse(sess, args.voxel, args.refuse) or "재사용"
        arkit = _ply_counts_and_area(sess / "scene_mesh.ply") or {}
        fused = _ply_counts_and_area(_mesh_path(sess)) or {}
        stats.update({
            "arkit_area_m2": arkit.get("area_m2"), "arkit_faces": arkit.get("faces"),
            "fused_area_m2": fused.get("area_m2"), "fused_faces": fused.get("faces"),
            "fused_extent_m": fused.get("extent_m"),
        })
        results[sess.name] = stats

    (a, sa), (b, sb) = results.items()
    width = max(len(label) for label, _ in ROWS)
    print()
    print(f"{'항목':<{width}} | {a[:34]:<34} | {b[:34]:<34}")
    print("-" * (width + 76))
    for label, key in ROWS:
        print(f"{label:<{width}} | {str(sa.get(key)):<34} | {str(sb.get(key)):<34}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"compare_{a}_vs_{b}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out}")
    print("읽는 법: 같은 장소·경로라면 [본체] 표면적·면 수가 비슷하고 트래킹·흔들림이 안정적인 기기가 4D 녹화에 적합하다.")
    print("        ARKit 신뢰도·ARKit 메시는 폰 내부 판정이라 참고만 — 재구성은 신뢰도맵을 쓰지 않는다.")


if __name__ == "__main__":
    main()
