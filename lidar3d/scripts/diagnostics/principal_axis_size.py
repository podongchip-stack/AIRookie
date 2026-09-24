#!/usr/bin/env python3
"""A. 좌표축 평행 상자 vs 주축(PCA) 기준 크기 비교 (open3d 전용).

현행 크기 필터는 d = pts.max(0)-pts.min(0) 으로 **월드 X·Z축에 평행한 상자**를 쓴다.
ARKit 월드의 X·Z 방향은 촬영 시작 시 폰이 향한 방향으로 정해지므로,
비스듬히 누운 사람은 상자가 부풀어 세장비가 낮게 나온다.

수평면(XZ)에서 주성분을 구해 긴 축 기준으로 다시 잰다.
높이(Y)는 중력 정렬이라 그대로 쓴다.
"""
import sys, json
from pathlib import Path
import numpy as np, open3d as o3d

def pca_xz(P):
    """수평면 주축 기준 길이·폭·회전각(도). 높이는 Y 그대로."""
    Q = P[:, [0, 2]] - P[:, [0, 2]].mean(0)
    # 공분산 고유벡터 = 주축
    w, v = np.linalg.eigh(np.cov(Q.T))
    order = np.argsort(-w)
    v = v[:, order]
    proj = Q @ v
    L = proj[:, 0].max() - proj[:, 0].min()
    Wd = proj[:, 1].max() - proj[:, 1].min()
    ang = np.degrees(np.arctan2(v[1, 0], v[0, 0])) % 180
    return L, Wd, P[:, 1].max() - P[:, 1].min(), ang

def axis_box(P):
    d = P.max(0) - P.min(0)
    return max(d[0], d[2]), min(d[0], d[2]), d[1]

# 현행 필터 (좌표축 상자 기준)
def pass_axis(P):
    d = P.max(0) - P.min(0)
    return 0.30 < d[1] < 2.2 and 0.15 < d[0] < 2.0 and 0.15 < d[2] < 2.0
# 주축 기준으로 같은 임계값 적용
def pass_pca(P):
    L, Wd, Hh, _ = pca_xz(P)
    return 0.30 < Hh < 2.2 and 0.15 < Wd < 2.0 and 0.15 < L < 2.0

def show(tag, P):
    aL, aW, aH = axis_box(P)
    pL, pW, pH, ang = pca_xz(P)
    pa, pp = pass_axis(P), pass_pca(P)
    flag = "  ⚠️ 판정 바뀜" if pa != pp else ""
    print(f"  {tag:<26} 축상자 {aL:5.2f}x{aW:5.2f}x{aH:5.2f} 세장비{aL/max(aW,1e-6):4.1f} {'✅' if pa else '❌'}"
          f" | 주축 {pL:5.2f}x{pW:5.2f}x{pH:5.2f} 세장비{pL/max(pW,1e-6):4.1f} 회전{ang:5.1f}° {'✅' if pp else '❌'}{flag}")
    return pa, pp

S_ALL = [Path("server/sessions")/f"session_20260920v{i}_iPhone12Pro" for i in (1,2,3)]

print("="*118)
print("A-1. v3 조각 3의 세 조각 (매트 제거 전/후)")
print("="*118)
S = S_ALL[2]
mob = o3d.io.read_triangle_mesh(str(S/"fused_objects.ply"))
with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
    ci, _, ca = mob.cluster_connected_triangles()
ci=np.asarray(ci); ca=np.asarray(ca); Vo=np.asarray(mob.vertices); To=np.asarray(mob.triangles)
k3=int(np.argsort(-ca)[0]); vi=np.unique(To[np.where(ci==k3)[0]]); P3=Vo[vi]
keepv=np.load("/tmp/keepv.npy"); ad=np.load("/tmp/assign.npy")
assign=ad[0].astype(int); dmin=ad[1]; stable=json.load(open("/tmp/stable2.json"))
for a,c in enumerate(stable):
    s0=(assign==a)&(dmin<=0.30)
    if s0.sum()<200: continue
    show(f"군집{c} 제거전", P3[s0])
    s1=s0&keepv
    if s1.sum()>=100: show(f"군집{c} 제거후", P3[s1])
    print()

print("="*118)
print("A-2/A-3. v1~v3의 모든 사람 조각 + review_blob")
print("="*118)
changed=[]
for S in S_ALL:
    pj=json.loads((S/"persons.json").read_text(encoding="utf-8"))
    print(f"\n[{S.name}]")
    for p_ in pj["persons"]+pj.get("review",[]):
        f=S/p_["file"]
        if not f.exists(): continue
        P=np.asarray(o3d.io.read_triangle_mesh(str(f)).vertices)
        if len(P)<50: continue
        pa,pp=show(p_["file"], P)
        if pa!=pp: changed.append((S.name,p_["file"],pa,pp))
print()
print("="*118)
print(f"판정이 바뀐 조각: {len(changed)}개")
for n,f,pa,pp in changed:
    print(f"  {n}  {f}:  축상자 {'통과' if pa else '탈락'} → 주축 {'통과' if pp else '탈락'}")
