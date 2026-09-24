"""4D 고정 녹화 세션 → 시간대별 3D(배경 1개 + 프레임별 움직이는 점) — live4d 4단계.

한 대로 고정 녹화한 세션(capture_mode=lidar_arkit_fixed4d)을 읽어, 웹 뷰어(live4d/viewer/)가
슬라이더로 넘겨 볼 수 있는 형태로 만든다.

원리 — **측정값만 쓴다(AI 추정 없음)**:
  1. 배경: 카메라가 고정이라 같은 화소의 뎁스를 전 구간에서 모아 중앙값을 내면, 사람이 지나가도
     배경 거리가 남는다(한 화소를 사람이 가리는 시간은 대개 절반 미만). 색도 같은 방식으로 중앙값.
  2. 움직이는 대상: 매 프레임에서 **배경보다 FG_MIN_M 이상 앞에 있는** 화소. 작은 잡음 덩어리는 버린다.
     사람이 비켜서 배경이 다시 드러나는 화소는 배경이므로 따로 뽑지 않는다.
  3. 3D 좌표: 프레임마다 그 순간의 포즈로 역투영한다(고정이라 거의 같지만 미세 흔들림도 반영).
  4. 색: 같은 프레임의 영상(뎁스와 1:1로 짝지어 기록됨)을 뎁스 해상도로 줄여 입힌다.

뎁스 정리는 lidar3d의 fuse_depth.clean_depth를 그대로 쓴다(4.0m 초과·경계 튐·스치는 각도 제거)
— 정적 3D와 같은 기준으로 걸러야 두 결과를 겹쳐 볼 때 어긋나지 않는다.

한계(뷰어에도 표시한다): 고정 시점 1대라 **카메라가 본 면만** 있다(사람 뒷면은 비어 있다).
사람이 한 화소를 절반 넘게 가린 곳은 배경 중앙값이 사람 쪽으로 끌려간다.

사용법 (저장소 루트에서):
  python3 live4d/scripts/build_4d.py lidar3d/server/sessions/<세션>_4D [--fg-min 0.10] [--min-blob 40]
출력: live4d/data/4d/<세션>/ — manifest.json, bg_pos.bin, bg_col.bin, fr_pos.bin, fr_col.bin
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

LIVE4D_DIR = Path(__file__).resolve().parents[1]
OUT_ROOT = LIVE4D_DIR / "data" / "4d"
FUSE_DEPTH = LIVE4D_DIR.parent / "lidar3d" / "scripts" / "fuse_depth.py"
MAX_DEPTH_M = 4.0


def _load_clean_depth():
    """lidar3d의 뎁스 정리 함수를 가져온다(같은 필터 기준을 쓰기 위해)."""
    spec = importlib.util.spec_from_file_location("fuse_depth", FUSE_DEPTH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.clean_depth, mod.quat_to_R


def _backproject(depth: np.ndarray, K: tuple[float, float, float, float], R: np.ndarray, t: np.ndarray,
                 mask: np.ndarray) -> np.ndarray:
    """mask 화소를 ARKit 월드 좌표(미터)로. ARKit 카메라는 -Z를 보고 +Y가 위다."""
    fx, fy, cx, cy = K
    v, u = np.nonzero(mask)
    d = depth[v, u]
    cam = np.stack([(u - cx) / fx * d, -(v - cy) / fy * d, -d], axis=1)
    return cam @ R.T + t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path)
    ap.add_argument("--fg-min", type=float, default=0.10, help="배경보다 이만큼(m) 앞이면 움직이는 대상")
    ap.add_argument("--min-blob", type=int, default=40, help="이보다 작은 화소 덩어리는 잡음으로 버림")
    args = ap.parse_args()

    sess = args.session.resolve()
    meta = json.loads((sess / "metadata.json").read_text(encoding="utf-8"))
    if meta.get("capture_mode") != "lidar_arkit_fixed4d":
        print(f"⚠ capture_mode={meta.get('capture_mode')} — 4D 고정 녹화 세션이 아닙니다. 결과가 흔들릴 수 있습니다.")
    W, H = meta["depth_width"], meta["depth_height"]
    sx, sy = W / meta["video_frame_width"], H / meta["video_frame_height"]
    clean_depth, quat_to_R = _load_clean_depth()
    started = time.time()

    poses = {r["timestamp"]: r for r in csv.DictReader(open(sess / "arkit_pose.csv"))}
    rows = [r for r in csv.DictReader(open(sess / "depth" / "index.csv"))
            if r["timestamp"] in poses and poses[r["timestamp"]]["tracking_state"] == "2"]
    if not rows:
        sys.exit("❌ 사용할 뎁스 프레임이 없습니다 (포즈 불일치 또는 트래킹 실패).")

    # --- 영상: 뎁스와 짝지어진 프레임만 뎁스 해상도로 줄여 둔다 ---
    want = {int(r["video_frame_index"]) for r in rows if r["video_frame_index"] != "-1"}
    colors: dict[int, np.ndarray] = {}
    cap = cv2.VideoCapture(str(sess / "video.mov"))
    idx = 0
    while want:
        ok, frame = cap.read()
        if not ok:
            break
        if idx in want:
            colors[idx] = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)[:, :, ::-1]  # BGR→RGB
            want.discard(idx)
        idx += 1
    cap.release()

    # --- 뎁스 정리 + 프레임별 포즈 ---
    depths, Ks, Rs, ts, rgbs, times = [], [], [], [], [], []
    for r in rows:
        p = poses[r["timestamp"]]
        K = (float(p["fx"]) * sx, float(p["fy"]) * sy, float(p["cx"]) * sx, float(p["cy"]) * sy)
        d = np.fromfile(sess / "depth" / r["depth_file"], dtype="<f4").reshape(H, W)
        depths.append(clean_depth(d, K, MAX_DEPTH_M))
        Ks.append(K)
        Rs.append(quat_to_R(*[float(p[k]) for k in ("qx", "qy", "qz", "qw")]))
        ts.append(np.array([float(p[k]) for k in ("tx", "ty", "tz")]))
        vfi = int(r["video_frame_index"])
        rgbs.append(colors.get(vfi))
        times.append(float(r["timestamp"]))
    D = np.stack(depths)
    times = np.array(times) - times[0]

    # --- 1) 배경: 화소별 유효 뎁스의 중앙값, 색도 중앙값 ---
    Dn = np.where(D > 0, D, np.nan)
    with np.errstate(all="ignore"):
        bg = np.nanmedian(Dn, axis=0)
    bg_valid = np.isfinite(bg)
    color_stack = np.stack([c for c in rgbs if c is not None])
    bg_rgb = np.median(color_stack, axis=0).astype(np.uint8)
    mid = len(rows) // 2  # 고정 녹화라 가운데 프레임 포즈를 배경 기준으로 쓴다
    bg_pts = _backproject(np.nan_to_num(bg), Ks[mid], Rs[mid], ts[mid], bg_valid)
    bg_col = bg_rgb[bg_valid]

    # --- 2) 프레임별 움직이는 대상 ---
    kernel = np.ones((3, 3), np.uint8)
    fr_pts, fr_col, counts = [], [], []
    for i in range(len(rows)):
        m = (D[i] > 0) & bg_valid & ((np.nan_to_num(bg) - D[i]) > args.fg_min)
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, kernel)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        keep = np.zeros(n, bool)
        keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= args.min_blob
        m = keep[lab]
        pts = _backproject(D[i], Ks[i], Rs[i], ts[i], m)
        col = rgbs[i][m] if rgbs[i] is not None else np.full((len(pts), 3), 200, np.uint8)
        fr_pts.append(pts); fr_col.append(col); counts.append(len(pts))

    # --- 3) 저장: 장면 중심 기준 int16 밀리미터(±32m) + uint8 RGB ---
    allp = np.concatenate([bg_pts] + [p for p in fr_pts if len(p)])
    origin = (allp.min(0) + allp.max(0)) / 2
    span = allp.max(0) - allp.min(0)
    if np.any(span / 2 > 32.0):
        sys.exit(f"❌ 장면이 너무 큽니다({span}) — int16 밀리미터 범위(±32m)를 넘습니다.")
    q = lambda p: np.round((p - origin) * 1000).astype(np.int16)

    out = OUT_ROOT / sess.name
    out.mkdir(parents=True, exist_ok=True)
    q(bg_pts).tofile(out / "bg_pos.bin")
    bg_col.astype(np.uint8).tofile(out / "bg_col.bin")
    fr_all = np.concatenate([p for p in fr_pts if len(p)]) if sum(counts) else np.zeros((0, 3))
    fr_call = np.concatenate([c for c in fr_col if len(c)]) if sum(counts) else np.zeros((0, 3), np.uint8)
    q(fr_all).tofile(out / "fr_pos.bin")
    fr_call.astype(np.uint8).tofile(out / "fr_col.bin")

    offsets = np.concatenate([[0], np.cumsum(counts)[:-1]]).astype(int).tolist()
    cam_R, cam_t = Rs[mid], ts[mid]
    manifest = {
        "session": sess.name,
        "device": meta.get("device"),
        "ios": meta.get("ios_version"),
        "capture_mode": meta.get("capture_mode"),
        "source": "measured",
        "source_note": "LiDAR 측정값만 사용(AI 추정 없음). 고정 시점 1대라 카메라가 본 면만 있다.",
        "frame_count": len(rows),
        "duration_s": round(float(times[-1]), 3),
        "depth_hz": round(len(rows) / max(float(times[-1]), 1e-6), 2),
        "times_s": [round(float(x), 4) for x in times],
        "frame_offsets": offsets,
        "frame_counts": [int(c) for c in counts],
        "background_count": int(len(bg_pts)),
        "encoding": {
            "position": "int16 밀리미터, origin 기준 (x,y,z) — 실제 좌표 = int16 / 1000 + origin",
            "color": "uint8 RGB",
            "origin": [float(x) for x in origin],
        },
        "camera": {  # 녹화 카메라 자세(ARKit 월드, camera-to-world) — 뷰어의 "촬영 시점" 버튼용
            "position": [float(x) for x in cam_t],
            "rotation": [[float(x) for x in row] for row in cam_R],
            "fx": Ks[mid][0], "fy": Ks[mid][1], "cx": Ks[mid][2], "cy": Ks[mid][3],
            "width": W, "height": H,
        },
        "params": {"fg_min_m": args.fg_min, "min_blob_px": args.min_blob, "max_depth_m": MAX_DEPTH_M},
        "mount": {k: meta.get(k) for k in ("fixed4d_mount_max_translation_m", "fixed4d_mount_max_rotation_deg",
                                            "fixed4d_mount_drift_event_count")},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    size_mb = sum(f.stat().st_size for f in out.glob("*.bin")) / 1e6
    print(f"✅ {sess.name}")
    print(f"   프레임 {len(rows)}장 / {times[-1]:.1f}초 ({manifest['depth_hz']}Hz)")
    print(f"   배경 점 {len(bg_pts):,}개 · 움직이는 점 프레임 평균 {np.mean(counts):,.0f}개 (최대 {max(counts):,})")
    print(f"   출력 {out} ({size_mb:.1f} MB, {time.time() - started:.1f}초)")


if __name__ == "__main__":
    main()
