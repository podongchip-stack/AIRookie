"""4D 고정 녹화 세션 → 시간대별 3D(배경 + 프레임별 움직이는 점) — live4d 4단계.

두 가지 모드:
  · 1대:  build_4d.py <4D 세션>                     → live4d/data/4d/<세션>/
  · 여러 대: build_4d.py --align <정합 이름>          → live4d/data/4d/<정합 이름>/
    (align_sessions.py가 만든 정합 결과로 두 폰의 점을 **판 좌표계·공통 시각**에 합치고,
     3D 스캔 세션이 있으면 그것을 배경으로 쓴다)

원리 — **측정값만 쓴다(AI 추정 없음)**:
  1. 움직이는 대상: 카메라가 고정이라 화소별 뎁스 중앙값이 그 카메라의 배경이 된다. 매 프레임에서
     배경보다 "그 화소의 문턱" 이상 앞에 있는 화소를 뽑고 작은 잡음 덩어리는 버린다. 그 순간 포즈로 3D에
     놓고 같은 프레임 영상의 색을 입힌다.
     화소별 문턱 = max(--fg-min, --noise-k × 그 화소의 센서 흔들림).
     센서 흔들림은 **연속한 두 프레임 차이**의 중앙값으로 잰다(σ ≈ 1.4826·median|ΔD|/√2). 전 구간 중앙값과의
     차이로 재면 사람이 오래 머문 화소에서 "있음↔없음"이 흔들림으로 잡혀 정작 사람을 지워 버렸다.
     사람의 움직임은 1/15초 사이엔 대부분 작아서, 프레임 간 차이는 센서 잡음을 주로 반영한다. 가만히 있는 장면에서도
     뎁스가 크게 흔들리는 기기(0925 실측: 15 Pro 흔들림 중앙 161mm, 12 Pro 17mm)는 고정 문턱 10cm로는
     벽·책상이 통째로 "움직이는 대상"으로 잡혔다(15 Pro 화면의 26%). 흔들림이 큰 화소는 그만큼 더 앞에
     있어야 인정해 측정값만으로 잡음을 거른다(12 Pro처럼 흔들림이 작은 기기는 결과가 거의 같다).
  2. 배경: 1대 모드는 위 중앙값 배경을 그대로 쓴다(사람이 절반 넘게 머문 자리는 흐릿한 형체가 남는다).
     여러 대 모드에서 3D 스캔 세션이 있으면 **스캔을 배경으로** 쓴다(빈 공간을 따로 찍었으므로 형체가 없다).
     스캔은 뎁스 프레임을 역투영해 2cm 격자로 줄인 색 점이다.
  3. 여러 대 합치기: 기준(첫 4D) 세션의 프레임 시각을 틱으로 삼고, 틱마다 다른 세션에서 공통 시각이
     가장 가까운 프레임(±MATCH_TOL_S 이내)을 골라 점을 합친다.

뎁스 정리는 lidar3d의 fuse_depth.clean_depth를 그대로 쓴다(4.0m 초과·경계 튐·스치는 각도 제거).

출력: manifest.json, bg_pos.bin, bg_col.bin, fr_pos.bin, fr_col.bin
      위치 = int16 밀리미터(origin 기준), 색 = uint8 RGB. manifest의 up은 중력 반대 방향.
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
ALIGN_DIR = LIVE4D_DIR / "data" / "align"
FUSE_DEPTH = LIVE4D_DIR.parent / "lidar3d" / "scripts" / "fuse_depth.py"
MAX_DEPTH_M = 4.0
MATCH_TOL_S = 0.05          # 여러 대 합칠 때 같은 순간으로 보는 시각 차이


def _load_fuse_helpers():
    spec = importlib.util.spec_from_file_location("fuse_depth", FUSE_DEPTH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.clean_depth, mod.quat_to_R


clean_depth, quat_to_R = _load_fuse_helpers()


def _backproject(depth, K, R, t, mask):
    """mask 화소를 ARKit 월드 좌표(미터)로. ARKit 카메라는 -Z를 보고 +Y가 위다."""
    fx, fy, cx, cy = K
    v, u = np.nonzero(mask)
    d = depth[v, u]
    cam = np.stack([(u - cx) / fx * d, -(v - cy) / fy * d, -d], axis=1)
    return cam @ R.T + t


def _read_frames(sess: Path, every: int = 1):
    """트래킹 정상인 뎁스 프레임과 짝 영상(뎁스 해상도로 축소), 포즈를 읽는다."""
    meta = json.loads((sess / "metadata.json").read_text(encoding="utf-8"))
    W, H = meta["depth_width"], meta["depth_height"]
    sx, sy = W / meta["video_frame_width"], H / meta["video_frame_height"]
    poses = {r["timestamp"]: r for r in csv.DictReader(open(sess / "arkit_pose.csv"))}
    rows = [r for r in csv.DictReader(open(sess / "depth" / "index.csv"))
            if r["timestamp"] in poses and poses[r["timestamp"]]["tracking_state"] == "2"][::every]
    if not rows:
        sys.exit(f"❌ {sess.name}: 사용할 뎁스 프레임이 없습니다 (포즈 불일치 또는 트래킹 실패).")
    want = {int(r["video_frame_index"]) for r in rows if r["video_frame_index"] != "-1"}
    colors, cap, idx = {}, cv2.VideoCapture(str(sess / "video.mov")), 0
    while want:
        if not cap.grab():
            break
        if idx in want:
            _, frame = cap.retrieve()
            colors[idx] = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)[:, :, ::-1]
            want.discard(idx)
        idx += 1
    cap.release()
    out = []
    for r in rows:
        p = poses[r["timestamp"]]
        K = (float(p["fx"]) * sx, float(p["fy"]) * sy, float(p["cx"]) * sx, float(p["cy"]) * sy)
        d = np.fromfile(sess / "depth" / r["depth_file"], dtype="<f4").reshape(H, W)
        out.append({
            "t": float(r["timestamp"]), "K": K,
            "R": quat_to_R(*[float(p[k]) for k in ("qx", "qy", "qz", "qw")]),
            "tr": np.array([float(p[k]) for k in ("tx", "ty", "tz")]),
            "depth": clean_depth(d, K, MAX_DEPTH_M),
            "rgb": colors.get(int(r["video_frame_index"])),
        })
    return meta, out, (W, H)


NOISE_K = 3.0


def process_4d(sess: Path, fg_min: float, min_blob: int, noise_k: float = NOISE_K) -> dict:
    """한 4D 세션 → 프레임별 움직이는 점(월드) + 중앙값 배경 + 카메라."""
    meta, fr, (W, H) = _read_frames(sess)
    D = np.stack([f["depth"] for f in fr])
    with np.errstate(all="ignore"):
        bg = np.nanmedian(np.where(D > 0, D, np.nan), axis=0)
    bg_valid = np.isfinite(bg)
    bg0 = np.nan_to_num(bg)
    Dn = np.where(D > 0, D, np.nan)
    with np.errstate(all="ignore"):
        mad = np.nanmedian(np.abs(np.diff(Dn, axis=0)), axis=0) * 1.4826 / np.sqrt(2)
    thresh = np.maximum(fg_min, noise_k * np.nan_to_num(mad, nan=fg_min))
    bg_rgb = np.median(np.stack([f["rgb"] for f in fr if f["rgb"] is not None]), axis=0).astype(np.uint8)
    mid = fr[len(fr) // 2]
    kernel = np.ones((3, 3), np.uint8)
    frames = []
    for f in fr:
        m = (f["depth"] > 0) & bg_valid & ((bg0 - f["depth"]) > thresh)
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, kernel)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        keep = np.zeros(n, bool)
        keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_blob
        m = keep[lab]
        pts = _backproject(f["depth"], f["K"], f["R"], f["tr"], m)
        col = f["rgb"][m] if f["rgb"] is not None else np.full((len(pts), 3), 200, np.uint8)
        frames.append((f["t"], pts, col))
    return {
        "name": sess.name, "meta": meta, "frames": frames,
        "bg_pts": _backproject(bg0, mid["K"], mid["R"], mid["tr"], bg_valid), "bg_col": bg_rgb[bg_valid],
        "camera": {"R": mid["R"], "t": mid["tr"], "K": mid["K"], "W": W, "H": H},
        "depth_jitter_mm": float(np.nanmedian(mad) * 1000),
    }


def scan_background(sess: Path, voxel: float = 0.02, every: int = 3):
    """3D 스캔 세션 → 색 있는 배경 점(월드). 뎁스를 역투영해 voxel 격자당 한 점만 남긴다."""
    _, fr, _ = _read_frames(sess, every=every)
    P, C = [], []
    for f in fr:
        m = f["depth"] > 0
        P.append(_backproject(f["depth"], f["K"], f["R"], f["tr"], m))
        C.append(f["rgb"][m] if f["rgb"] is not None else np.full((int(m.sum()), 3), 200, np.uint8))
    P, C = np.concatenate(P), np.concatenate(C)
    key = np.floor(P / voxel).astype(np.int64)
    _, first = np.unique(key, axis=0, return_index=True)
    return P[first], C[first]


def _xf(T, P):
    return P @ T[:3, :3].T + T[:3, 3]


def write_output(out: Path, bg_pts, bg_col, ticks, frames_pts, frames_col, cameras, up, extra):
    allp = np.concatenate([bg_pts] + [p for p in frames_pts if len(p)])
    origin = (allp.min(0) + allp.max(0)) / 2
    span = allp.max(0) - allp.min(0)
    if np.any(span / 2 > 32.0):
        sys.exit(f"❌ 장면이 너무 큽니다({np.round(span, 1)}m) — int16 밀리미터 범위(±32m)를 넘습니다.")
    q = lambda p: np.round((p - origin) * 1000).astype(np.int16)
    out.mkdir(parents=True, exist_ok=True)
    counts = [len(p) for p in frames_pts]
    q(bg_pts).tofile(out / "bg_pos.bin")
    bg_col.astype(np.uint8).tofile(out / "bg_col.bin")
    nonempty = [p for p in frames_pts if len(p)]
    q(np.concatenate(nonempty) if nonempty else np.zeros((0, 3))).tofile(out / "fr_pos.bin")
    ce = [c for c in frames_col if len(c)]
    (np.concatenate(ce) if ce else np.zeros((0, 3), np.uint8)).astype(np.uint8).tofile(out / "fr_col.bin")
    times = np.array(ticks) - ticks[0]
    manifest = {
        "source": "measured",
        "source_note": "LiDAR 측정값만 사용(AI 추정 없음). 카메라가 본 면만 있다.",
        "frame_count": len(ticks),
        "duration_s": round(float(times[-1]), 3),
        "depth_hz": round(len(ticks) / max(float(times[-1]), 1e-6), 2),
        "times_s": [round(float(x), 4) for x in times],
        "frame_offsets": np.concatenate([[0], np.cumsum(counts)[:-1]]).astype(int).tolist(),
        "frame_counts": [int(c) for c in counts],
        "background_count": int(len(bg_pts)),
        "up": [float(x) for x in up],
        "encoding": {"position": "int16 밀리미터, origin 기준 — 실제 좌표 = int16 / 1000 + origin",
                     "color": "uint8 RGB", "origin": [float(x) for x in origin]},
        "cameras": [{"name": c["name"], "device": c.get("device"),
                     "position": [float(x) for x in c["t"]], "rotation": [[float(x) for x in r] for r in c["R"]],
                     "fx": c["K"][0], "fy": c["K"][1], "cx": c["K"][2], "cy": c["K"][3],
                     "width": c["W"], "height": c["H"]} for c in cameras],
        **extra,
    }
    manifest["camera"] = manifest["cameras"][0]      # 구버전 뷰어 호환
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    size_mb = sum(f.stat().st_size for f in out.glob("*.bin")) / 1e6
    print(f"   틱 {len(ticks)}개 / {times[-1]:.1f}초 · 배경 점 {len(bg_pts):,} · "
          f"움직이는 점 평균 {np.mean(counts):,.0f} (최대 {max(counts):,})")
    print(f"   출력 {out} ({size_mb:.1f} MB)")


def build_single(sess: Path, fg_min: float, min_blob: int) -> None:
    s = process_4d(sess, fg_min, min_blob)
    meta = s["meta"]
    if meta.get("capture_mode") != "lidar_arkit_fixed4d":
        print(f"⚠ capture_mode={meta.get('capture_mode')} — 4D 고정 녹화 세션이 아닙니다.")
    cam = dict(s["camera"], name=s["name"], device=meta.get("device"))
    write_output(OUT_ROOT / sess.name, s["bg_pts"], s["bg_col"],
                 [t for t, _, _ in s["frames"]], [p for _, p, _ in s["frames"]], [c for _, _, c in s["frames"]],
                 [cam], (0.0, 1.0, 0.0), {
                     "session": sess.name, "device": meta.get("device"), "background_source": "median_of_4d",
                     "params": {"fg_min_m": fg_min, "min_blob_px": min_blob, "max_depth_m": MAX_DEPTH_M},
                     "mount": {k: meta.get(k) for k in ("fixed4d_mount_max_translation_m",
                                                        "fixed4d_mount_max_rotation_deg",
                                                        "fixed4d_mount_drift_event_count")}})


def build_multi(align_name: str, fg_min: float, min_blob: int) -> None:
    A = json.loads((ALIGN_DIR / f"{align_name}.json").read_text(encoding="utf-8"))
    four = [s for s in A["sessions"] if s["role"] == "4d" and s.get("T_board_from_world")]
    scans = [s for s in A["sessions"] if s["role"] == "scan" and s.get("T_board_from_world")]
    if not four:
        sys.exit("❌ 좌표가 맞춰진 4D 세션이 없습니다 — align_sessions.py 결과에서 판 검출을 확인하세요.")
    skipped = [s["name"] for s in A["sessions"] if not s.get("T_board_from_world")]
    if skipped:
        print(f"⚠ 판을 못 찾아 제외: {', '.join(skipped)}")

    procs, cameras = [], []
    for s in four:
        print(f"… {s['name']}: 움직이는 점 추출")
        p = process_4d(Path(s["path"]), fg_min, min_blob)
        p["name"] = s["name"]
        T = np.array(s["T_board_from_world"])
        tc = s["time"]["unix_offset"] + s["time"]["refine_s"]           # 공통 시각 = arkit + tc
        p["common"] = [(t + tc, _xf(T, pts), col) for t, pts, col in p["frames"]]
        p["bg_board"] = (_xf(T, p["bg_pts"]), p["bg_col"])
        c = p["camera"]
        cameras.append({"name": s["name"], "device": s.get("device"), "R": T[:3, :3] @ c["R"],
                        "t": _xf(T, c["t"][None])[0], "K": c["K"], "W": c["W"], "H": c["H"]})
        procs.append(p)

    if scans:
        s = scans[0]
        print(f"… {s['name']}: 3D 스캔 배경 생성")
        P, C = scan_background(Path(s["path"]))
        bg_pts, bg_col, bg_src = _xf(np.array(s["T_board_from_world"]), P), C, "scan:" + s["name"]
    else:
        bg_pts = np.concatenate([p["bg_board"][0] for p in procs])
        bg_col = np.concatenate([p["bg_board"][1] for p in procs])
        bg_src = "median_of_4d"

    # 기준 세션의 프레임 시각을 틱으로, 다른 세션은 가장 가까운 프레임을 붙인다.
    ref = procs[0]["common"]
    others = [(np.array([t for t, _, _ in p["common"]]), p["common"]) for p in procs[1:]]
    ticks, fpts, fcol, matched = [], [], [], [0] * len(others)
    for t, pts, col in ref:
        P, C = [pts], [col]
        for k, (ts, fr) in enumerate(others):
            j = int(np.argmin(np.abs(ts - t)))
            if abs(ts[j] - t) <= MATCH_TOL_S:
                P.append(fr[j][1]); C.append(fr[j][2]); matched[k] += 1
        ticks.append(t); fpts.append(np.concatenate(P)); fcol.append(np.concatenate(C))
    for k, p in enumerate(procs[1:]):
        print(f"   {p['name']}: 기준 틱 {len(ref)}개 중 {matched[k]}개와 시각 일치(±{MATCH_TOL_S * 1000:.0f}ms)")

    # 판 좌표계에서의 중력 반대 방향(뷰어 위쪽) — 기준 세션 월드의 +Y를 옮긴다.
    up = np.array(four[0]["T_board_from_world"])[:3, :3] @ np.array([0.0, 1.0, 0.0])
    write_output(OUT_ROOT / align_name, bg_pts, bg_col, ticks, fpts, fcol, cameras, up / np.linalg.norm(up), {
        "session": align_name, "device": " + ".join(filter(None, (c.get("device") for c in cameras))),
        "background_source": bg_src, "alignment": align_name,
        "params": {"fg_min_m": fg_min, "min_blob_px": min_blob, "max_depth_m": MAX_DEPTH_M,
                   "match_tol_s": MATCH_TOL_S},
        "sources": [{"name": s["name"], "role": s["role"], "board": s.get("board"), "time": s["time"]}
                    for s in A["sessions"]]})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", nargs="?", type=Path, help="1대 모드: 4D 세션 경로")
    ap.add_argument("--align", help="여러 대 모드: align_sessions.py --name 값")
    ap.add_argument("--fg-min", type=float, default=0.10, help="배경보다 이만큼(m) 앞이면 움직이는 대상")
    ap.add_argument("--min-blob", type=int, default=40, help="이보다 작은 화소 덩어리는 잡음으로 버림")
    args = ap.parse_args()
    started = time.time()
    if args.align:
        print(f"✅ 여러 대: {args.align}")
        build_multi(args.align, args.fg_min, args.min_blob)
    elif args.session:
        print(f"✅ 1대: {args.session.name}")
        build_single(args.session.resolve(), args.fg_min, args.min_blob)
    else:
        ap.error("세션 경로 또는 --align 이 필요합니다")
    print(f"   {time.time() - started:.1f}초")


if __name__ == "__main__":
    main()
