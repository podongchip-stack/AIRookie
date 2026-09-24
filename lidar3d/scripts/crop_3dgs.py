#!/usr/bin/env python3
"""장면 전체 3DGS(.ply)를 사람별 영역으로 잘라낸다.

persons.json의 center_xyz/size_m은 ARKit 월드 좌표이고, 3DGS도 ARKit 포즈로
학습했으므로 좌표계가 동일하다. 따라서 축 정렬 경계상자(AABB)로 바로 자른다.

3DGS는 **보기 전용**이다. 거리·크기 측정은 계속 메트릭 메시(fused_person_*.ply)로
해야 한다. 3DGS는 표면이 아니라 반투명 점 분포라 측정 대상이 아니다.
"""
import argparse, json
from pathlib import Path

import numpy as np


def read_gs_ply(path: Path):
    """INRIA 3DGS PLY 읽기. 헤더에서 속성 순서를 그대로 보존한다."""
    with open(path, "rb") as f:
        header, line = [], b""
        while line.strip() != b"end_header":
            line = f.readline()
            if not line:
                raise SystemExit(f"❌ 헤더가 끝나지 않음: {path}")
            header.append(line)
        n = next(int(l.split()[2]) for l in header if l.startswith(b"element vertex"))
        props = [l.split()[2].decode() for l in header if l.startswith(b"property float")]
        if len(props) * 4 * n == 0:
            raise SystemExit(f"❌ 빈 PLY: {path}")
        data = np.frombuffer(f.read(n * len(props) * 4), np.float32).reshape(n, len(props))
    return header, props, data


def write_gs_ply(path: Path, props, data):
    with open(path, "wb") as f:
        f.write(b"ply\nformat binary_little_endian 1.0\n")
        f.write(f"element vertex {len(data)}\n".encode())
        for p in props:
            f.write(f"property float {p}\n".encode())
        f.write(b"end_header\n")
        f.write(np.ascontiguousarray(data, np.float32).tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene_ply", type=Path, help="학습된 장면 전체 3DGS")
    ap.add_argument("session", type=Path, help="persons.json이 있는 세션 폴더")
    ap.add_argument("--margin", type=float, default=0.15,
                    help="경계상자 여유(m). 메시보다 3DGS가 조금 더 퍼져 있다.")
    args = ap.parse_args()

    pj = args.session / "persons.json"
    if not pj.exists():
        raise SystemExit(f"❌ {pj} 없음 — 적응형 융합을 먼저 실행하세요")
    persons = json.loads(pj.read_text())["persons"]

    props, data = read_gs_ply(args.scene_ply)[1:]
    xyz = data[:, :3]
    print(f"장면 3DGS: {len(data):,}개 가우시안")

    out = []
    for p in persons:
        c = np.array(p["center_xyz"]); s = np.array(p["size_m"]) / 2 + args.margin
        m = np.all((xyz >= c - s) & (xyz <= c + s), axis=1)
        name = f"gs_person_{p['index']:02d}.ply"
        dst = args.session / name
        if m.sum() < 100:
            print(f"  사람 {p['index']}: 가우시안 {m.sum()}개뿐 — 건너뜀 "
                  f"(이 사람은 3DGS 학습 중 움직였을 가능성이 높다)")
            continue
        write_gs_ply(dst, props, data[m])
        print(f"  사람 {p['index']}: {m.sum():>7,}개 -> {name} ({dst.stat().st_size/1e6:.1f}MB)")
        out.append({"index": p["index"], "file": name, "gaussians": int(m.sum())})

    (args.session / "gs_persons.json").write_text(
        json.dumps({"scene_gaussians": len(data), "persons": out}, indent=2, ensure_ascii=False))
    print(f"\n✅ {len(out)}명 잘라냄 -> gs_persons.json")


if __name__ == "__main__":
    main()
