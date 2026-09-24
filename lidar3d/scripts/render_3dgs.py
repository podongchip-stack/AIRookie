#!/usr/bin/env python3
"""학습된 3DGS를 특정 학습 카메라 포즈에서 렌더해 실제 프레임과 나란히 저장한다.

같은 포즈·같은 내부 파라미터로 렌더하므로 "3DGS가 사진에 얼마나 가까운가"를
공정하게 볼 수 있다. (메시 비교 때 점 스플래팅 대신 삼각형 래스터화를 썼던 것과
같은 이유 — 비교 조건을 맞추지 않으면 결론이 왜곡된다.)
"""
import argparse
from pathlib import Path

import cv2
import numpy as np
import torch
from gsplat import rasterization

import sys
sys.path.insert(0, str(Path(__file__).parent))
from train_3dgs import read_colmap


def load_gs_ply(path: Path, device):
    with open(path, "rb") as f:
        header, line = [], b""
        while line.strip() != b"end_header":
            line = f.readline(); header.append(line)
        n = next(int(l.split()[2]) for l in header if l.startswith(b"element vertex"))
        props = [l.split()[2].decode() for l in header if l.startswith(b"property float")]
        d = np.frombuffer(f.read(n * len(props) * 4), np.float32).reshape(n, len(props))
    idx = {p: i for i, p in enumerate(props)}
    g = lambda pre, k: d[:, [idx[f"{pre}{i}"] for i in range(k)]]
    n_rest = sum(1 for p in props if p.startswith("f_rest_"))
    K = n_rest // 3 + 1                              # SH 계수 개수
    t = lambda a: torch.tensor(np.ascontiguousarray(a), device=device)
    # f_rest는 채널 우선(INRIA 규약)으로 저장돼 있다: [N,3,K-1] -> [N,K-1,3]
    shN = g("f_rest_", n_rest).reshape(n, 3, K - 1).transpose(0, 2, 1)
    return dict(
        means=t(d[:, :3]),
        sh0=t(g("f_dc_", 3)).reshape(n, 1, 3),
        shN=t(shN),
        opacities=torch.sigmoid(t(d[:, idx["opacity"]])),
        scales=torch.exp(t(g("scale_", 3))),
        quats=t(g("rot_", 4)),
        sh_degree=int(round(K ** 0.5)) - 1,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ply", type=Path)
    ap.add_argument("data", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--frames", type=int, nargs="+", required=True)
    ap.add_argument("--factor", type=int, default=2)
    args = ap.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("❌ CUDA 필요 (3DGS 래스터화는 CUDA 전용)")
    dev = "cuda"
    args.out.mkdir(parents=True, exist_ok=True)

    views, imgs, _, _ = read_colmap(args.data, args.factor)
    by_frame = {int(v["name"].split("_")[1].split(".")[0]): k for k, v in enumerate(views)}
    gs = load_gs_ply(args.ply, dev)
    print(f"가우시안 {gs['means'].shape[0]:,}개, SH {gs['sh_degree']}차")

    for fr in args.frames:
        if fr not in by_frame:
            print(f"  프레임 {fr}: 학습 뷰에 없음 — 건너뜀"); continue
        k = by_frame[fr]; v = views[k]; c = v["cam"]
        Vm = torch.tensor(v["viewmat"][None], dtype=torch.float32, device=dev)
        Ks = torch.tensor([[[c["fx"], 0, c["cx"]], [0, c["fy"], c["cy"]], [0, 0, 1]]],
                          dtype=torch.float32, device=dev)
        with torch.no_grad():
            img, _, _ = rasterization(
                means=gs["means"], quats=gs["quats"], scales=gs["scales"],
                opacities=gs["opacities"], colors=torch.cat([gs["sh0"], gs["shN"]], 1),
                viewmats=Vm, Ks=Ks, width=c["w"], height=c["h"],
                sh_degree=gs["sh_degree"], packed=False)
        ren = (img[0].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)[:, :, ::-1]
        gt = imgs[k][:, :, ::-1]
        lab = lambda im, s: cv2.putText(im.copy(), s, (14, 34),
                                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
        cv2.imwrite(str(args.out / f"compare_frame_{fr:05d}.jpg"),
                    np.hstack([lab(gt, "PHOTO"), lab(ren, "3DGS")]),
                    [cv2.IMWRITE_JPEG_QUALITY, 92])
        err = np.abs(ren.astype(float) - gt.astype(float)).mean()
        print(f"  프레임 {fr}: 저장 완료, 평균 화소오차 {err:.1f}/255")


if __name__ == "__main__":
    main()
