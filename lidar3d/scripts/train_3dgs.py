#!/usr/bin/env python3
"""COLMAP 포맷 -> 3D Gaussian Splatting 학습 (gsplat, CUDA 필수).

A100 같은 CUDA GPU에서만 돈다. 맥(MPS)에는 3DGS 래스터화 커널이 없다.

gsplat 공식 예제(examples/simple_trainer.py)는 torch 2.9.1과 viser/nerfview/
fused-ssim/ppisp 등 무거운 의존성을 요구한다. 여기서는 gsplat 라이브러리의
핵심 API(rasterization + DefaultStrategy)만 직접 써서 같은 알고리즘을 돌린다.

출력 .ply는 INRIA 3DGS 표준 포맷이라 웹 뷰어가 그대로 읽는다.
"""
import argparse, json, math, time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from gsplat import DefaultStrategy, rasterization


# ---------------------------------------------------------------- COLMAP 읽기
def read_colmap(root: Path, factor: int):
    sparse = root / "sparse" / "0"
    cams = {}
    for line in (sparse / "cameras.txt").read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        p = line.split()
        cams[int(p[0])] = dict(w=int(p[2]), h=int(p[3]),
                               fx=float(p[4]), fy=float(p[5]),
                               cx=float(p[6]), cy=float(p[7]))

    views, lines = [], [l for l in (sparse / "images.txt").read_text().splitlines()
                        if not l.startswith("#")]
    i = 0
    while i < len(lines):
        p = lines[i].split()
        i += 2  # 두 번째 줄은 2D 대응점(우리는 비어 있음)
        if len(p) < 10:
            continue
        qw, qx, qy, qz = map(float, p[1:5])
        t = np.array(list(map(float, p[5:8])))
        c = cams[int(p[8])]
        R = np.array([
            [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
            [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
            [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
        ])
        viewmat = np.eye(4); viewmat[:3, :3] = R; viewmat[:3, 3] = t
        views.append(dict(viewmat=viewmat, cam=c, name=p[9]))

    pts, cols = [], []
    for line in (sparse / "points3D.txt").read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        p = line.split()
        pts.append(list(map(float, p[1:4]))); cols.append(list(map(int, p[4:7])))

    # 이미지 적재 (factor로 축소; 내부 파라미터도 같은 비율로 줄인다)
    imgs = []
    for v in views:
        im = cv2.imread(str(root / "images" / v["name"]))
        if im is None:
            raise SystemExit(f"❌ 이미지를 읽을 수 없음: {v['name']}")
        if factor > 1:
            im = cv2.resize(im, (im.shape[1] // factor, im.shape[0] // factor),
                            interpolation=cv2.INTER_AREA)
            for k in ("fx", "fy", "cx", "cy"):
                v["cam"][k] /= factor
        v["cam"]["w"], v["cam"]["h"] = im.shape[1], im.shape[0]
        imgs.append(im[:, :, ::-1].copy())  # BGR -> RGB
    return views, imgs, np.array(pts, np.float32), np.array(cols, np.float32) / 255.0


# ------------------------------------------------------------------- 초기화
def init_splats(pts, cols, sh_degree, device, init_scale_k=3):
    N = len(pts)
    from scipy.spatial import cKDTree
    # 이웃까지의 거리로 초기 가우시안 크기를 정한다 (조밀한 곳은 작게).
    d, _ = cKDTree(pts).query(pts, k=init_scale_k + 1)
    dist = np.clip(d[:, 1:].mean(1), 1e-4, None)

    means = torch.tensor(pts, device=device)
    scales = torch.log(torch.tensor(dist, dtype=torch.float32, device=device))[:, None].repeat(1, 3)
    quats = torch.zeros(N, 4, device=device); quats[:, 0] = 1.0
    opacities = torch.logit(torch.full((N,), 0.1, device=device))

    # SH 0차 = 기본색. C0는 SH 정규화 상수.
    C0 = 0.28209479177387814
    sh0 = ((torch.tensor(cols, dtype=torch.float32, device=device) - 0.5) / C0)[:, None, :]
    shN = torch.zeros(N, (sh_degree + 1) ** 2 - 1, 3, device=device)

    return torch.nn.ParameterDict({
        "means": torch.nn.Parameter(means),
        "scales": torch.nn.Parameter(scales),
        "quats": torch.nn.Parameter(quats),
        "opacities": torch.nn.Parameter(opacities),
        "sh0": torch.nn.Parameter(sh0),
        "shN": torch.nn.Parameter(shN),
    }).to(device)


def make_optimizers(splats, lr_scale):
    # 위치 학습률만 장면 크기에 비례시킨다 (원 논문과 동일한 관행).
    spec = {"means": 1.6e-4 * lr_scale, "scales": 5e-3, "quats": 1e-3,
            "opacities": 5e-2, "sh0": 2.5e-3, "shN": 2.5e-3 / 20}
    return {k: torch.optim.Adam([{"params": splats[k], "lr": v, "name": k}], eps=1e-15)
            for k, v in spec.items()}


# ---------------------------------------------------------------------- SSIM
def _win(ch, ws, device):
    g = torch.tensor([math.exp(-((x - ws // 2) ** 2) / 4.5) for x in range(ws)], device=device)
    g = (g / g.sum())[:, None]
    return (g @ g.T).expand(ch, 1, ws, ws).contiguous()


def ssim(a, b, win):
    ch = a.shape[1]; pad = win.shape[-1] // 2
    mu1 = F.conv2d(a, win, padding=pad, groups=ch)
    mu2 = F.conv2d(b, win, padding=pad, groups=ch)
    m1s, m2s, m12 = mu1 * mu1, mu2 * mu2, mu1 * mu2
    s1 = F.conv2d(a * a, win, padding=pad, groups=ch) - m1s
    s2 = F.conv2d(b * b, win, padding=pad, groups=ch) - m2s
    s12 = F.conv2d(a * b, win, padding=pad, groups=ch) - m12
    C1, C2 = 0.01 ** 2, 0.03 ** 2
    return (((2 * m12 + C1) * (2 * s12 + C2)) / ((m1s + m2s + C1) * (s1 + s2 + C2))).mean()


# ---------------------------------------------------------------- PLY 내보내기
def save_ply(splats, path: Path):
    """INRIA 3DGS 표준 PLY. 웹 뷰어(antimatter15/splat 등)가 그대로 읽는다."""
    n = splats["means"].shape[0]
    means = splats["means"].detach().cpu().numpy()
    sh0 = splats["sh0"].detach().cpu().numpy().reshape(n, -1)
    shN = splats["shN"].detach().transpose(1, 2).flatten(1).cpu().numpy()
    op = splats["opacities"].detach().cpu().numpy().reshape(n, 1)
    sc = splats["scales"].detach().cpu().numpy()
    rt = splats["quats"].detach().cpu().numpy()

    names = ["x", "y", "z", "nx", "ny", "nz"]
    names += [f"f_dc_{i}" for i in range(sh0.shape[1])]
    names += [f"f_rest_{i}" for i in range(shN.shape[1])]
    names += ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    data = np.concatenate([means, np.zeros((n, 3), np.float32), sh0, shN, op, sc, rt], 1).astype(np.float32)

    with open(path, "wb") as f:
        f.write(b"ply\nformat binary_little_endian 1.0\n")
        f.write(f"element vertex {n}\n".encode())
        for nm in names:
            f.write(f"property float {nm}\n".encode())
        f.write(b"end_header\n")
        f.write(data.tobytes())
    print(f"저장: {path}  ({n:,}개 가우시안, {path.stat().st_size/1e6:.0f}MB)")


# ---------------------------------------------------------------------- 학습
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--iters", type=int, default=30_000)
    ap.add_argument("--factor", type=int, default=2, help="이미지 축소 배율")
    ap.add_argument("--sh-degree", type=int, default=3)
    ap.add_argument("--save-every", type=int, default=7000)
    args = ap.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("❌ CUDA가 없다. 3DGS 래스터화는 CUDA 전용이라 맥에서는 돌지 않는다.")
    dev = "cuda"
    args.out.mkdir(parents=True, exist_ok=True)

    print("데이터 적재 중...", flush=True)
    views, imgs, pts, cols = read_colmap(args.data, args.factor)
    print(f"  뷰 {len(views)}개, 이미지 {imgs[0].shape[1]}x{imgs[0].shape[0]}, 초기점 {len(pts):,}개")

    cam_pos = np.array([-v["viewmat"][:3, :3].T @ v["viewmat"][:3, 3] for v in views])
    scene_scale = float(np.linalg.norm(cam_pos - cam_pos.mean(0), axis=1).max())
    print(f"  장면 반경 {scene_scale:.2f}m (ARKit 실측 미터 단위)")

    splats = init_splats(pts, cols, args.sh_degree, dev)
    opts = make_optimizers(splats, scene_scale)

    strategy = DefaultStrategy(verbose=False)
    strategy.check_sanity(splats, opts)
    state = strategy.initialize_state(scene_scale=scene_scale)

    gt = [torch.tensor(im, dtype=torch.float32, device=dev).permute(2, 0, 1)[None] / 255.0 for im in imgs]
    Vm = torch.tensor(np.stack([v["viewmat"] for v in views]), dtype=torch.float32, device=dev)
    Ks = torch.tensor(np.stack([[[v["cam"]["fx"], 0, v["cam"]["cx"]],
                                 [0, v["cam"]["fy"], v["cam"]["cy"]],
                                 [0, 0, 1]] for v in views]), dtype=torch.float32, device=dev)
    W, H = views[0]["cam"]["w"], views[0]["cam"]["h"]
    win = _win(3, 11, dev)

    rng = np.random.default_rng(0)
    order, ptr = rng.permutation(len(views)), 0
    t0 = time.time()
    for step in range(args.iters):
        if ptr >= len(order):
            order, ptr = rng.permutation(len(views)), 0
        i = int(order[ptr]); ptr += 1

        # SH 차수를 서서히 올린다. 처음부터 고차를 쓰면 발산한다.
        sh_deg = min(step // 1000, args.sh_degree)

        img, alpha, info = rasterization(
            means=splats["means"],
            quats=splats["quats"],
            scales=torch.exp(splats["scales"]),
            opacities=torch.sigmoid(splats["opacities"]),
            colors=torch.cat([splats["sh0"], splats["shN"]], 1),
            viewmats=Vm[i:i + 1], Ks=Ks[i:i + 1], width=W, height=H,
            sh_degree=sh_deg, packed=False, absgrad=strategy.absgrad,
        )
        strategy.step_pre_backward(params=splats, optimizers=opts, state=state, step=step, info=info)

        pred = img.permute(0, 3, 1, 2).clamp(0, 1)
        l1 = (pred - gt[i]).abs().mean()
        loss = 0.8 * l1 + 0.2 * (1.0 - ssim(pred, gt[i], win))

        loss.backward()
        strategy.step_post_backward(params=splats, optimizers=opts, state=state,
                                    step=step, info=info, packed=False)
        for o in opts.values():
            o.step(); o.zero_grad(set_to_none=True)

        if step % 500 == 0 or step == args.iters - 1:
            el = time.time() - t0
            eta = el / max(step + 1, 1) * (args.iters - step - 1)
            print(f"  step {step:6d}/{args.iters}  L1 {l1.item():.4f}  "
                  f"가우시안 {splats['means'].shape[0]:,}  "
                  f"경과 {el/60:.1f}분  남은 {eta/60:.0f}분", flush=True)
        if args.save_every and step > 0 and step % args.save_every == 0:
            save_ply(splats, args.out / f"point_cloud_{step}.ply")

    save_ply(splats, args.out / "point_cloud.ply")
    (args.out / "train_info.json").write_text(json.dumps({
        "iters": args.iters, "factor": args.factor, "sh_degree": args.sh_degree,
        "views": len(views), "gaussians": int(splats["means"].shape[0]),
        "scene_scale_m": scene_scale, "minutes": (time.time() - t0) / 60,
    }, indent=2))
    print(f"\n✅ 학습 완료 ({(time.time()-t0)/60:.0f}분)")


if __name__ == "__main__":
    main()
