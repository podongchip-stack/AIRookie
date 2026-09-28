#!/usr/bin/env python3
"""사람 인식 파이프라인 단계별 손실 추적 (진단 전용, 아무것도 수정하지 않는다).

목적: fused_objects.ply 표면적 중 "사람"으로 분류되는 비율이 낮을 때,
      어느 단계에서 무엇이 걸러지는지 숫자로 특정한다.

사용:
  python3 scripts/diagnostics/trace_person_pipeline.py server/sessions/<세션> [--dump]
  --dump 를 주면 사람으로 분류되지 않은 조각을 별도 PLY로 저장한다 (육안 확인용).
"""
import argparse, json, sys
from pathlib import Path

import numpy as np
import cv2
import open3d as o3d

# stage2_fuse.py 가 쓰는 값과 **반드시 같아야 한다**. 다르면 진단이 거짓말을 한다.
# 2026-09-21: stage2_fuse.py에 "확인 필요(review)" 보존이 추가됐다.
#   범위 밖이어도 표면적 ≥ MIN_AREA 이면 review_blob_NN.ply 로 남는다.
#   판정 임계값 자체는 바뀌지 않았으므로 아래 상수는 그대로다.
MIN_CLUSTER_AREA = 0.05      # 5cm² 미만 조각은 노이즈로 버림
GROUP_RADIUS     = 0.8       # 이 거리 안이면 같은 사람으로 묶음
MIN_VERTS        = 50
MIN_AREA         = 0.15      # 이보다 작으면 사람으로 안 침 (조용히 버려짐)
SIZE_Y           = (0.30, 2.2)
SIZE_X           = (0.15, 2.0)
SIZE_Z           = (0.15, 2.0)


def size_ok(d):
    return (SIZE_Y[0] < d[1] < SIZE_Y[1]
            and SIZE_X[0] < d[0] < SIZE_X[1]
            and SIZE_Z[0] < d[2] < SIZE_Z[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path)
    ap.add_argument("--dump", action="store_true", help="비사람 조각을 PLY로 저장")
    a = ap.parse_args()
    S = a.session
    out = {}

    # ── 1. YOLO 마스크 ────────────────────────────────────────────────
    npz = S / "person_masks.npz"
    if not npz.exists():
        sys.exit(f"❌ {npz} 없음 — 적응형 융합을 먼저 실행하세요")
    z = np.load(npz)
    frames_checked = len(z.files)
    # 2026-09-21: stage1이 "뎁스별 최근접 영상 프레임"으로 마스크를 만든다.
    #   person_masks_map.json 이 있으면 그 방식이고, 없으면 예전 video_frame_index 방식이다.
    _map = S / "person_masks_map.json"
    print(f"  마스크 매칭 방식      : "
          f"{'최근접 타임스탬프' if _map.exists() else 'video_frame_index (예전)'}")
    blob_counts, mask_px = [], 0
    for k in z.files:
        m = z[k]
        mask_px += int(m.sum())
        if m.any():
            n, _ = cv2.connectedComponents(m.astype(np.uint8))
            blob_counts.append(n - 1)          # 배경 라벨 제외
        else:
            blob_counts.append(0)
    bc = np.array(blob_counts)
    frames_with = int((bc > 0).sum())
    print("=" * 64)
    print("1단계 — YOLO 마스크")
    print("=" * 64)
    print(f"  검사 프레임        : {frames_checked}")
    print(f"  사람 있는 프레임    : {frames_with} ({frames_with/frames_checked*100:.1f}%)")
    print(f"  마스크 True 화소 합 : {mask_px:,}")
    print(f"  프레임당 덩어리 수  : 중앙값 {np.median(bc[bc>0]):.0f}  "
          f"최대 {bc.max()}  분포 {dict(zip(*np.unique(bc, return_counts=True)))}")
    out["masks"] = {"frames_checked": frames_checked, "frames_with_person": frames_with,
                    "blob_hist": {int(k): int(v) for k, v in zip(*np.unique(bc, return_counts=True))}}

    # ── 2. 융합된 객체 메시 ───────────────────────────────────────────
    mob_p = S / "fused_objects.ply"
    if not mob_p.exists():
        sys.exit(f"❌ {mob_p} 없음")
    mob = o3d.io.read_triangle_mesh(str(mob_p))
    mob.compute_vertex_normals()
    total_area = mob.get_surface_area()
    print()
    print("=" * 64)
    print("2단계 — 융합된 객체 볼륨 (fused_objects.ply)")
    print("=" * 64)
    print(f"  정점 {len(mob.vertices):,}  삼각형 {len(mob.triangles):,}  표면적 {total_area:.2f}㎡")

    # ── 3. 연결 성분 ─────────────────────────────────────────────────
    with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
        ci, ntri, carea = mob.cluster_connected_triangles()
    ci = np.asarray(ci); carea = np.asarray(carea)
    print()
    print("=" * 64)
    print("3단계 — 연결 성분 분리")
    print("=" * 64)
    print(f"  조각 {len(carea)}개  표면적 합 {carea.sum():.2f}㎡")
    noise = carea[carea <= MIN_CLUSTER_AREA]
    print(f"  노이즈(≤{MIN_CLUSTER_AREA}㎡) {len(noise)}개 = {noise.sum():.2f}㎡ "
          f"({noise.sum()/total_area*100:.1f}%)")
    cand = [k for k in range(len(carea)) if carea[k] > MIN_CLUSTER_AREA]
    print(f"  후보 조각 {len(cand)}개 = {carea[cand].sum():.2f}㎡")

    # ── 4. 근접 그룹화 ───────────────────────────────────────────────
    Vo = np.asarray(mob.vertices); To = np.asarray(mob.triangles)
    cents = {k: Vo[To[np.where(ci == k)[0]]].reshape(-1, 3).mean(0) for k in cand}
    groups, used = [], set()
    for k in sorted(cand, key=lambda x: -carea[x]):
        if k in used: continue
        g = [k]; used.add(k)
        for j in cand:
            if j in used: continue
            if np.linalg.norm(cents[j] - cents[k]) < GROUP_RADIUS:
                g.append(j); used.add(j)
        groups.append(g)
    print()
    print("=" * 64)
    print(f"4단계 — 근접 그룹화 (반경 {GROUP_RADIUS}m)")
    print("=" * 64)
    print(f"  그룹 {len(groups)}개")

    # ── 5. 크기 필터 ─────────────────────────────────────────────────
    print()
    print("=" * 64)
    print("5단계 — 크기 필터 (여기서 무엇이 탈락하는가)")
    print("=" * 64)
    print(f"  기준: {SIZE_X[0]}<가로<{SIZE_X[1]}  {SIZE_Y[0]}<높이<{SIZE_Y[1]}  "
          f"{SIZE_Z[0]}<깊이<{SIZE_Z[1]}  표면적≥{MIN_AREA}㎡  정점≥{MIN_VERTS}")
    print()
    print(f"  {'#':>3} {'표면적':>8} {'가로x높이x깊이':>22} {'정점':>8}  {'판정':<28}")
    kept_area = rej_area = 0.0
    kept = []
    rows = []
    for gi, g in enumerate(groups):
        tri_idx = np.concatenate([np.where(ci == k)[0] for k in g])
        sub = o3d.geometry.TriangleMesh(mob)
        sub.triangles = o3d.utility.Vector3iVector(To[tri_idx])
        sub.remove_unreferenced_vertices(); sub.compute_vertex_normals()
        pts = np.asarray(sub.vertices)
        area = sub.get_surface_area()
        if len(pts) < MIN_VERTS:
            verdict = f"탈락: 정점 {len(pts)}<{MIN_VERTS}"
            rej_area += area; rows.append((gi, area, None, len(pts), verdict, sub)); continue
        d = pts.max(0) - pts.min(0)
        if not size_ok(d):
            bad = []
            if not (SIZE_X[0] < d[0] < SIZE_X[1]): bad.append(f"가로{d[0]:.2f}")
            if not (SIZE_Y[0] < d[1] < SIZE_Y[1]): bad.append(f"높이{d[1]:.2f}")
            if not (SIZE_Z[0] < d[2] < SIZE_Z[1]): bad.append(f"깊이{d[2]:.2f}")
            verdict = "탈락: 크기(" + ",".join(bad) + ")"
            rej_area += area; rows.append((gi, area, d, len(pts), verdict, sub)); continue
        if area < MIN_AREA:
            verdict = f"탈락: 표면적 {area:.3f}<{MIN_AREA} (조용히 버려짐)"
            rej_area += area; rows.append((gi, area, d, len(pts), verdict, sub)); continue
        kept.append((gi, area, d, sub)); kept_area += area
        rows.append((gi, area, d, len(pts), "✅ 사람", sub))

    for gi, area, d, nv, verdict, _ in sorted(rows, key=lambda r: -r[1]):
        ds = f"{d[0]:.2f}x{d[1]:.2f}x{d[2]:.2f}" if d is not None else "—"
        print(f"  {gi:>3} {area:>7.3f}㎡ {ds:>22} {nv:>8}  {verdict:<28}")

    print()
    print("=" * 64)
    print("종합")
    print("=" * 64)
    # stage2_fuse.py와 같은 기준으로 "확인 필요"가 몇 개인지도 보여준다.
    review_n = sum(1 for _, area, d, nv, v, _ in rows
                   if not v.startswith("✅") and area >= MIN_AREA and nv >= MIN_VERTS)
    print(f"  객체 볼륨 전체        : {total_area:7.2f}㎡ (100%)")
    print(f"  └ 노이즈 조각         : {noise.sum():7.2f}㎡ ({noise.sum()/total_area*100:5.1f}%)")
    print(f"  └ 사람으로 인정       : {kept_area:7.2f}㎡ ({kept_area/total_area*100:5.1f}%)  {len(kept)}명")
    print(f"  └ 필터 탈락           : {rej_area:7.2f}㎡ ({rej_area/total_area*100:5.1f}%)")
    print(f"     그중 '확인 필요'로 보존: {review_n}개 "
          f"(review_blob_NN.ply — 사람일 수 있으니 눈으로 확인할 것)")

    if a.dump:
        dump_dir = S / "diag_nonperson"
        dump_dir.mkdir(exist_ok=True)
        for gi, area, d, nv, verdict, sub in rows:
            if verdict.startswith("✅"): continue
            sub.paint_uniform_color([0.2, 0.5, 0.9])
            o3d.io.write_triangle_mesh(str(dump_dir / f"reject_{gi:02d}_{area:.2f}m2.ply"), sub)
        print(f"\n  비사람 조각을 {dump_dir}/ 에 저장했습니다 (육안 확인용)")

    out["summary"] = {"total_area": round(total_area, 3), "noise": round(float(noise.sum()), 3),
                      "person": round(kept_area, 3), "rejected": round(rej_area, 3),
                      "person_count": len(kept)}
    (S / "diag_person_pipeline.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
