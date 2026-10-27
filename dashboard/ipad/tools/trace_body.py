#!/usr/bin/env python3
"""사람 실루엣 사진 → GoldenLinkPad/BodyShape.swift (외상 부위 그림의 좌표).

쓰는 법:  python3 tools/trace_body.py <사진> > GoldenLinkPad/BodyShape.swift
사진에 사람이 여럿이면 **맨 왼쪽의 검은(채워진) 형태**를 쓴다. 필요한 건 numpy·Pillow뿐.
그림을 바꾸려면 새 사진으로 이 스크립트를 다시 돌린다 — BodyShape.swift는 손으로 고치지 않는다.
"""
import sys, math
import numpy as np
from PIL import Image

DARK = 110          # 이보다 어두우면 몸
MIN_W = 10          # 이보다 좁은 세로 띠는 글자·잡티로 본다

def main(src: str) -> None:
    a = np.array(Image.open(src).convert("L"))
    dark = a < DARK
    cols = dark.sum(axis=0) > 0
    runs, s = [], None
    for x, v in enumerate(cols):
        if v and s is None: s = x
        if not v and s is not None: runs.append((s, x)); s = None
    if s is not None: runs.append((s, len(cols)))
    x0, x1 = next(r for r in runs if r[1] - r[0] > MIN_W)      # 맨 왼쪽 형태
    sub = dark[:, x0:x1]
    ys, xs = np.where(sub)
    m = sub[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    H, W = m.shape

    outline = chaikin(douglas_peucker(trace(m, H, W), 0.0055), 2)
    torso = torso_edges(m, H, W)
    emit(outline, torso, W / H)

def trace(m, H, W):
    """바깥 윤곽선(Moore 이웃 추적) → 0~1 좌표"""
    def nb(y, x):
        return [(y-1,x),(y-1,x+1),(y,x+1),(y+1,x+1),(y+1,x),(y+1,x-1),(y,x-1),(y-1,x-1)]
    def ok(y, x): return 0 <= y < H and 0 <= x < W and m[y, x]
    ys, xs = np.where(m)
    start = (ys[0], xs[np.where(ys == ys[0])[0][0]])
    out, cur, prev = [start], start, (ys[0], xs[0] - 1)
    for _ in range(100000):
        ring = nb(*cur)
        i = ring.index(prev) if prev in ring else 0
        found = None
        for k in range(1, 9):
            c = ring[(i + k) % 8]
            if ok(*c):
                found, prev = c, ring[(i + k - 1) % 8]
                break
        if found is None: break
        cur = found
        if cur == start and len(out) > 10: break
        out.append(cur)
    return [(x / W, y / H) for y, x in out]

def douglas_peucker(p, eps):
    if len(p) < 3: return p
    a, b = p[0], p[-1]
    dmax, idx = 0, 0
    for i in range(1, len(p) - 1):
        px, py = p[i]
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1e-9
        d = abs(dy * px - dx * py + b[0] * a[1] - b[1] * a[0]) / n
        if d > dmax: dmax, idx = d, i
    if dmax <= eps: return [a, b]
    return douglas_peucker(p[:idx + 1], eps)[:-1] + douglas_peucker(p[idx:], eps)

def chaikin(p, n=2):
    for _ in range(n):
        out = []
        for i in range(len(p)):
            a, b = p[i], p[(i + 1) % len(p)]
            out.append((a[0] * .75 + b[0] * .25, a[1] * .75 + b[1] * .25))
            out.append((a[0] * .25 + b[0] * .75, a[1] * .25 + b[1] * .75))
        p = out
    return p

def torso_edges(m, H, W):
    """팔을 뺀 몸통의 좌우 경계. 팔이 몸통에 붙어 있는 어깨 위쪽은 목 너비에서 이어 그린다."""
    def runs(y):
        xr = np.where(m[y])[0]
        if not len(xr): return []
        out, s, p = [], xr[0], xr[0]
        for x in xr[1:]:
            if x > p + 1: out.append((s, p)); s = x
            p = x
        return out + [(s, p)]
    mid = {}
    for y in range(int(.16 * H), int(.585 * H)):
        r = runs(y)
        if len(r) >= 3:
            c = [t for t in r if t[0] <= W // 2 <= t[1]]
            if c: mid[y] = c[0]
    sep = min(mid)
    neck_y = int(.168 * H); neck = runs(neck_y)[0]
    rows = []
    for y in range(neck_y, int(.585 * H)):
        if y in mid:
            l, r = mid[y]
        else:
            t = (y - neck_y) / max(1, sep - neck_y)
            l = neck[0] + (mid[sep][0] - neck[0]) * t
            r = neck[1] + (mid[sep][1] - neck[1]) * t
        rows.append((y / H, l / W, (r + 1) / W))
    step = max(1, len(rows) // 24)
    return rows[::step] + [rows[-1]]

def emit(outline, torso, ratio):
    def block(items, per):
        rows = ["        " + ", ".join(items[i:i + per]) for i in range(0, len(items), per)]
        return ",\n".join(rows)      # 줄 끝 쉼표 — Swift 배열 리터럴
    print("// 이 파일은 사람 그림의 좌표만 담는다 — `tools/trace_body.py`가 만든 생성물이라 손으로 고치지 않는다.")
    print("// 원본: 팀이 고른 2D 인체 실루엣(앞모습 남성) 사진의 맨 왼쪽 검은 형태를 윤곽선으로 딴 것.")
    print("// 좌표는 0~1(그림 칸 기준), 가로:세로 = %.4f : 1." % ratio)
    print("import CoreGraphics\n")
    print("enum BodyShape {")
    print("    /// 그림 비율(가로 ÷ 세로)")
    print("    static let ratio: CGFloat = %.4f\n" % ratio)
    print("    /// 바깥 윤곽선 — 머리 꼭대기에서 시작해 한 바퀴(%d점)" % len(outline))
    print("    static let outline: [(CGFloat, CGFloat)] = [")
    print(block(["(%.4f, %.4f)" % p for p in outline], 6))
    print("    ]\n")
    print("    /// 몸통(팔 제외) 좌우 경계 — (y, 왼쪽 x, 오른쪽 x). 팔·몸통 영역을 가르는 데 쓴다")
    print("    static let torso: [(CGFloat, CGFloat, CGFloat)] = [")
    print(block(["(%.4f, %.4f, %.4f)" % t for t in torso], 4))
    print("    ]")
    print("}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "body.jpg")
