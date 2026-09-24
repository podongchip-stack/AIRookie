"""여러 세션을 같은 좌표계·같은 시간축으로 맞춘다 — live4d 2·3단계.

대상: 두 폰의 4D 고정 녹화 세션 + (선택) 배경용 3D 스캔 세션. 결과는 build_4d.py --align 이 쓴다.

■ 공간 — 마커판(board.py) 좌표계로 통일
  ARKit은 세션마다 원점·방향이 다르다(세션 시작 자세 기준). 각 세션 영상에서 ChArUco 판을 찾아
  PnP로 "카메라 기준 판 자세"를 구하고, 그 순간의 ARKit 카메라 자세와 곱하면 "그 세션 월드에서의
  판 자세"가 된다. 모든 세션을 판 좌표계로 옮기면 같은 공간에 겹친다.
      T_world_board = T_world_cam(ARKit) · F · T_cam_board(OpenCV),   F = diag(1,-1,-1)
  여러 프레임에서 구한 값을 모아 중앙값으로 정하고, 흩어짐(mm·°)을 품질 지표로 남긴다.

■ 시간 — 1차: 기기 시계, 2차: 움직임 곡선
  1차: 앱이 metadata.clock_sync에 남긴 "경과 시간 ↔ 유닉스 시각" 대응으로 ARKit 시각을 공통 시각으로.
       (기기 시계 동기화 오차 = 보통 수십 ms)
  2차: 두 4D 세션의 "프레임별 움직임 양"(배경보다 앞에 나온 화소 비율) 곡선을 교차상관해 남은 어긋남을
       찾는다. 시점이 달라도 사람이 움직이는 순간은 두 카메라에서 함께 커지기 때문이다. 상관이 약하면
       (0.5 미만) 1차 값을 그대로 쓴다.
  넓은 탐색: 폰 시계가 수십 초 틀린 경우가 실제로 있었다(0925 촬영, 두 폰 시계 차 약 24초 — 1차 기준으로는
       두 녹화가 전혀 겹치지 않았다). ±1초 탐색이 실패하면 ±WIDE_LAG_S 범위를 찾아, 상관이 충분히 높고
       (≥0.6) 1초 넘게 떨어진 다른 후보보다 뚜렷할 때(차이 ≥0.1)만 채택하고 "시계 오차 의심"으로 기록한다.
       시작 신호(두 카메라에 보이는 곳에서 양팔을 빠르게 두 번 들기)를 넣으면 이 봉우리가 뚜렷해진다.

사용법 (저장소 루트에서):
  python3 live4d/scripts/align_sessions.py --name 0925_test \\
      [--scan lidar3d/server/sessions/<3D 스캔 세션>] \\
      lidar3d/server/sessions/<4D 세션 A> lidar3d/server/sessions/<4D 세션 B> [--square-mm 35]
출력: live4d/data/align/<name>.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board as B  # noqa: E402

LIVE4D_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = LIVE4D_DIR / "data" / "align"
F = np.diag([1.0, -1.0, -1.0])       # OpenCV 카메라(y 아래, z 앞) ↔ ARKit 카메라(y 위, -z 앞)
MIN_CORNERS = 8
WIDE_LAG_S = 60.0
MAX_REPROJ_PX = 2.0


def quat_to_R(x, y, z, w):
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def R_to_quat(R):
    w = np.sqrt(max(1e-12, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    return np.array([(R[2, 1] - R[1, 2]) / (4 * w), (R[0, 2] - R[2, 0]) / (4 * w), (R[1, 0] - R[0, 1]) / (4 * w), w])


def mean_rotation(Rs):
    """쿼터니언 평균(최대 고유벡터) — 작은 흩어짐에서 안정적이다."""
    Q = np.array([R_to_quat(R) for R in Rs])
    Q *= np.sign(Q @ Q[0])[:, None]
    _, vecs = np.linalg.eigh(Q.T @ Q)
    x, y, z, w = vecs[:, -1]
    return quat_to_R(x, y, z, w)


def rot_angle_deg(Ra, Rb):
    c = (np.trace(Ra.T @ Rb) - 1) / 2
    return float(np.degrees(np.arccos(np.clip(c, -1, 1))))


def load_session(sess: Path):
    meta = json.loads((sess / "metadata.json").read_text(encoding="utf-8"))
    poses = {r["timestamp"]: r for r in csv.DictReader(open(sess / "arkit_pose.csv"))}
    frames = {int(r["frame_index"]): r["timestamp"] for r in csv.DictReader(open(sess / "video_frames.csv"))}
    return meta, poses, frames


def board_pose(sess: Path, board, stride: int, max_hits: int):
    """세션 월드에서의 판 자세(T_world_board)와 품질."""
    meta, poses, frames = load_session(sess)
    detector = cv2.aruco.CharucoDetector(board)
    cap = cv2.VideoCapture(str(sess / "video.mov"))
    Ts, errs, idx, hits = [], [], 0, 0
    while hits < max_hits:
        ok = cap.grab()
        if not ok:
            break
        if idx % stride == 0 and idx in frames and frames[idx] in poses:
            _, img = cap.retrieve()
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            cc, ci, _, _ = detector.detectBoard(gray)
            if ci is not None and len(ci) >= MIN_CORNERS:
                obj, imgp = board.matchImagePoints(cc, ci)
                p = poses[frames[idx]]
                if p["tracking_state"] == "2":
                    K = np.array([[float(p["fx"]), 0, float(p["cx"])], [0, float(p["fy"]), float(p["cy"])], [0, 0, 1]])
                    ok2, rvec, tvec = cv2.solvePnP(obj, imgp, K, None, flags=cv2.SOLVEPNP_ITERATIVE)
                    if ok2:
                        proj, _ = cv2.projectPoints(obj, rvec, tvec, K, None)
                        err = float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - imgp.reshape(-1, 2)) ** 2, axis=1))))
                        if err <= MAX_REPROJ_PX:
                            T_cb = np.eye(4); T_cb[:3, :3] = cv2.Rodrigues(rvec)[0]; T_cb[:3, 3] = tvec.ravel()
                            T_wc = np.eye(4)
                            T_wc[:3, :3] = quat_to_R(*[float(p[k]) for k in ("qx", "qy", "qz", "qw")])
                            T_wc[:3, 3] = [float(p[k]) for k in ("tx", "ty", "tz")]
                            F4 = np.eye(4); F4[:3, :3] = F
                            Ts.append(T_wc @ F4 @ T_cb); errs.append(err); hits += 1
        idx += 1
    cap.release()
    if not Ts:
        return None
    t = np.median([T[:3, 3] for T in Ts], axis=0)
    R0 = mean_rotation([T[:3, :3] for T in Ts])
    keep = [T for T in Ts if rot_angle_deg(T[:3, :3], R0) < 5 and np.linalg.norm(T[:3, 3] - t) < 0.10]
    R = mean_rotation([T[:3, :3] for T in keep]) if keep else R0
    t = np.median([T[:3, 3] for T in keep], axis=0) if keep else t
    T = np.eye(4); T[:3, :3] = R; T[:3, 3] = t
    spread_mm = float(np.median([np.linalg.norm(K[:3, 3] - t) for K in keep]) * 1000) if keep else None
    spread_deg = float(np.median([rot_angle_deg(K[:3, :3], R) for K in keep])) if keep else None
    return {"T_world_board": T, "detections": len(Ts), "inliers": len(keep),
            "reproj_px": float(np.median(errs)), "spread_mm": spread_mm, "spread_deg": spread_deg}


def unix_offset(meta: dict, poses: dict) -> tuple[float, str]:
    cs = meta.get("clock_sync")
    if cs and "uptime_to_unix_offset_start" in cs:
        return float(cs["uptime_to_unix_offset_start"]), "clock_sync"
    # 구버전 세션: 시작 시각이 초 단위뿐이라 거칠다(±1초) — 경고와 함께 쓴다.
    from datetime import datetime
    wall = datetime.fromisoformat(meta["session_start_wallclock_iso8601"].replace("Z", "+00:00")).timestamp()
    first = min(float(t) for t in poses)
    return wall - first, "wallclock_seconds(거침)"


def motion_curve(sess: Path, fg_min: float = 0.10):
    """프레임별 움직임 양: 화소별 뎁스 중앙값(배경)보다 fg_min 이상 앞에 나온 화소 비율."""
    meta = json.loads((sess / "metadata.json").read_text(encoding="utf-8"))
    W, H = meta["depth_width"], meta["depth_height"]
    rows = list(csv.DictReader(open(sess / "depth" / "index.csv")))
    D = np.stack([np.fromfile(sess / "depth" / r["depth_file"], dtype="<f4").reshape(H, W) for r in rows])
    with np.errstate(all="ignore"):
        bg = np.nanmedian(np.where(D > 0, D, np.nan), axis=0)
    frac = (((np.nan_to_num(bg) - D) > fg_min) & (D > 0)).mean(axis=(1, 2))
    return np.array([float(r["timestamp"]) for r in rows]), frac


def _corr_at(ta, fa, tb, fb, lag, step, min_overlap):
    """곡선 b를 lag만큼 늦춰 겹친 구간에서의 상관계수(겹침이 짧으면 None)."""
    lo, hi = max(ta[0], tb[0] + lag), min(ta[-1], tb[-1] + lag)
    if hi - lo < min_overlap:
        return None
    grid = np.arange(lo, hi, step)
    A = np.interp(grid, ta, fa); A = (A - A.mean()) / (A.std() + 1e-9)
    Bv = np.interp(grid - lag, tb, fb); Bv = (Bv - Bv.mean()) / (Bv.std() + 1e-9)
    return float(np.mean(A * Bv))


def refine_offset(ta, fa, tb, fb, max_lag=1.0, step=0.01, min_overlap=5.0):
    """b의 시각에 더해야 a와 맞는 보정(초)과 상관계수. 못 찾으면 (0, None)."""
    best = (0.0, None)
    for lag in np.arange(-max_lag, max_lag + 1e-9, step):
        c = _corr_at(ta, fa, tb, fb, lag, step, min_overlap)
        if c is not None and (best[1] is None or c > best[1]):
            best = (float(lag), c)
    return best


def wide_offset(ta, fa, tb, fb, max_lag=WIDE_LAG_S):
    """넓은 범위 탐색: 거친 격자(0.05초)로 후보를 찾고 그 주변을 0.01초로 다듬는다.
    반환: (보정 초, 상관, 1초 넘게 떨어진 차선 후보의 상관)"""
    scores = []
    for lag in np.arange(-max_lag, max_lag, 0.05):
        c = _corr_at(ta, fa, tb, fb, lag, 0.02, 5.0)
        if c is not None:
            scores.append((c, float(lag)))
    if not scores:
        return 0.0, None, None
    scores.sort(reverse=True)
    c0, l0 = scores[0]
    runner = next((c for c, l in scores if abs(l - l0) > 1.0), None)
    fine = refine_offset(ta, fa, tb + l0, fb, max_lag=0.1)
    return l0 + fine[0], (fine[1] if fine[1] is not None else c0), runner


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+", type=Path, help="4D 고정 녹화 세션들 (첫 번째가 시간 기준)")
    ap.add_argument("--scan", type=Path, help="배경용 3D 스캔 세션 (선택)")
    ap.add_argument("--name", required=True, help="결과 이름 (live4d/data/align/<name>.json)")
    ap.add_argument("--square-mm", type=float, default=B.SQUARE_MM, help="인쇄된 판의 칸 실측 크기")
    ap.add_argument("--stride", type=int, default=2, help="영상 N프레임마다 판 검출")
    ap.add_argument("--max-hits", type=int, default=60)
    args = ap.parse_args()

    board = B.make_board(args.square_mm)
    entries = [(s.resolve(), "4d") for s in args.sessions] + ([(args.scan.resolve(), "scan")] if args.scan else [])
    result = {"square_mm": args.square_mm, "reference": entries[0][0].name, "sessions": []}
    curves = {}
    ok_all = True

    for sess, role in entries:
        print(f"… {sess.name} ({role}): 판 찾는 중")
        bp = board_pose(sess, board, args.stride, args.max_hits)
        meta, poses, _ = load_session(sess)
        off, off_src = unix_offset(meta, poses)
        item = {"name": sess.name, "path": str(sess), "role": role, "device": meta.get("device"),
                "time": {"unix_offset": off, "unix_offset_source": off_src, "refine_s": 0.0, "corr": None}}
        if bp is None:
            print(f"   ❌ 판을 찾지 못했습니다 — 이 세션은 좌표를 맞출 수 없습니다.")
            item["board"] = None
            ok_all = False
        else:
            T_bw = np.linalg.inv(bp["T_world_board"])
            item["T_board_from_world"] = T_bw.tolist()
            item["board"] = {k: v for k, v in bp.items() if k != "T_world_board"}
            print(f"   판 {bp['detections']}회 검출(채택 {bp['inliers']}), 재투영 {bp['reproj_px']:.2f}px, "
                  f"흩어짐 {bp['spread_mm']:.1f}mm·{bp['spread_deg']:.2f}°")
        if role == "4d":
            curves[sess.name] = motion_curve(sess)
        result["sessions"].append(item)

    # 시간 정밀 보정: 기준(첫 4D) 대비 나머지 4D
    ref = result["sessions"][0]
    tr, fr = curves[ref["name"]]
    for item in result["sessions"][1:]:
        if item["role"] != "4d":
            continue
        tb, fb = curves[item["name"]]
        # 공통 시각(유닉스)으로 옮긴 뒤 비교. 보정값 = b 시각에 더할 초.
        A_t, B_t = tr + ref["time"]["unix_offset"], tb + item["time"]["unix_offset"]
        lag, corr = refine_offset(A_t, fr, B_t, fb)
        if corr is not None and corr >= 0.5:
            item["time"].update(refine_s=lag, corr=corr, method="motion_curve_±1s")
            print(f"… {item['name']}: 움직임 곡선 보정 {lag * 1000:+.0f}ms (상관 {corr:.2f})")
            continue
        wl, wc, runner = wide_offset(A_t, fr, B_t, fb)
        if wc is not None and wc >= 0.6 and (runner is None or wc - runner >= 0.1):
            item["time"].update(refine_s=wl, corr=wc, runner_up_corr=runner, method="motion_curve_wide",
                                clock_error_suspected=True)
            print(f"… {item['name']}: ⚠ 기기 시계가 약 {wl:+.1f}초 어긋남 — 넓은 탐색으로 보정 "
                  f"(상관 {wc:.2f}, 차선 {runner if runner is None else round(runner, 2)})")
        else:
            item["time"].update(corr=corr, wide_corr=wc, method="clock_only")
            print(f"… {item['name']}: 움직임 곡선으로 시각을 확정하지 못함(±1초 {corr}, 넓게 {wc}) — "
                  f"기기 시계 값만 사용. 두 폰 시계 '자동 설정'과 시작 신호를 확인하세요.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{args.name}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'✅' if ok_all else '⚠'} 저장: {out}")


if __name__ == "__main__":
    main()
