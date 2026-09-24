#!/usr/bin/env python3
"""C 개선 — 3D 월드 좌표 기반 사람 배정 (진단 전용, 파이프라인 미수정).

5차 검증에서 확인된 한계를 세 가지로 보완한다.

  C-1 동시 출현 제약(cannot-link)
      같은 프레임에서 함께 검출된 인스턴스는 **반드시 서로 다른 사람**이다.
      flood-fill은 이 제약을 무시해 연쇄로 묶었다(군집9 = 2명).
      제약을 지키는 병합으로 바꾼다.

  C-2 최근접 "점" 배정
      군집 중심점까지의 거리로 배정하면 누운 사람의 머리·발끝이 멀어져 미배정된다.
      군집에 속한 인스턴스 점들 중 **가장 가까운 점**을 기준으로 바꾼다.

  C-3 반경 근거
      0.25m는 근거가 없었다. 분리에 성공한 군집14의 실측 흩어짐을 쓴다.

open3d 전용 프로세스 (torch를 import하지 않는다).
"""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d
from scipy.spatial import cKDTree

S=Path(sys.argv[1]); FLOOR=-0.71
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
W,H=meta["depth_width"],meta["depth_height"]; VW,VH=meta["video_frame_width"],meta["video_frame_height"]
sx,sy=W/VW,H/VH
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
near={int(k):v for k,v in json.load(open(S/"diag_nearest_map.json")).items()}
zi=np.load(S/"diag_inst_nearest.npz")

def R_(qx,qy,qz,qw):
    return np.array([[1-2*(qy*qy+qz*qz),2*(qx*qy-qz*qw),2*(qx*qz+qy*qw)],
                     [2*(qx*qy+qz*qw),1-2*(qx*qx+qz*qz),2*(qy*qz-qx*qw)],
                     [2*(qx*qz-qy*qw),2*(qy*qz+qx*qw),1-2*(qx*qx+qy*qy)]])
def clean(d,mx=4.0,er=0.04):
    d=d.copy(); d[(d<=0)|(d>mx)]=0
    pad=np.pad(d,1,constant_values=0)
    nb=np.stack([pad[:-2,1:-1],pad[2:,1:-1],pad[1:-1,:-2],pad[1:-1,2:]])
    with np.errstate(divide="ignore",invalid="ignore"):
        rel=np.abs(nb-d[None])/np.maximum(d[None],1e-6)
    d[np.nanmax(np.where(nb>0,rel,0),axis=0)>er]=0
    return d

# ── 인스턴스별 3D 점구름과 중심 수집 (프레임 번호를 함께 남긴다) ──────
obs=[]     # (frame, centroid, points)
for i,r in enumerate(rows):
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2" or i not in near: continue
    fi=near[i]
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    if n==0: continue
    d=clean(np.fromfile(S/"depth"/r["depth_file"],dtype="<f4").reshape(H,W))
    R=R_(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")]); T=R@np.diag([1.,-1.,-1.])
    fx,fy=float(p["fx"])*sx,float(p["fy"])*sy; cx,cy=float(p["cx"])*sx,float(p["cy"])*sy
    for k in range(n):
        m=zi[f"{fi}_{k}"]
        vv,uu=np.nonzero(m&(d>0.2)&(d<4.0))
        if len(vv)<120: continue
        zz=d[vv,uu]; med=np.median(zz); s=np.abs(zz-med)<0.6
        if s.sum()<120: continue
        vv,uu,zz=vv[s],uu[s],zz[s]
        X=(uu-cx)/fx*zz; Y=(vv-cy)/fy*zz
        P=np.stack([X,Y,zz],1)@T.T+t
        obs.append((fi,P.mean(0),P))
print(f"인스턴스 관측 {len(obs)}개\n")
C=np.array([o[1] for o in obs]); FR=np.array([o[0] for o in obs])

# ── C-3. 반경 근거 ────────────────────────────────────────────────
print("="*68); print("C-3. 군집 반경 근거"); print("="*68)
print("  5차에서 분리에 성공한 군집14의 실측 흩어짐: (0.05, 0.10, 0.15) m")
RAD=float(np.linalg.norm([0.05,0.10,0.15]))*2
print(f"  3축 결합 표준편차 = {np.linalg.norm([0.05,0.10,0.15]):.3f}m,  반경 = 그 2배 = {RAD:.3f}m")
print("  ⚠️ 한계: 군집14는 **관측 13회뿐**이다. 표본이 적어 흩어짐이 과소평가됐을 수 있다.")
print(f"  (이전 0.25m는 근거 없는 값이었다)")

# ── C-1. 동시 출현 제약을 지키는 병합 ────────────────────────────
print(); print("="*68); print("C-1. 동시 출현 제약(cannot-link) 병합"); print("="*68)
order=np.argsort([-len(o[2]) for o in obs])      # 큰 관측부터 씨앗으로
lbl=-np.ones(len(obs),int); members=[]           # members[c] = 관측 인덱스 목록
frames_of=[]                                     # frames_of[c] = 그 군집이 쓴 프레임 집합
for i in order:
    best=-1; bestd=1e9
    for c,mem in enumerate(members):
        if FR[i] in frames_of[c]:                # ← 같은 프레임 = 다른 사람. 병합 금지
            continue
        dmin=min(np.linalg.norm(C[i]-C[j]) for j in mem)
        if dmin<RAD and dmin<bestd: best,bestd=c,dmin
    if best<0:
        members.append([i]); frames_of.append({FR[i]}); lbl[i]=len(members)-1
    else:
        members[best].append(i); frames_of[best].add(FR[i]); lbl[i]=best
stable=[c for c,mem in enumerate(members) if len(mem)>=8]
print(f"  군집 {len(members)}개, 관측 8회 이상 안정 군집 {len(stable)}개")
print(f"  {'군집':>5}{'관측':>7}{'중심':>26}{'흩어짐':>22}")
for c in stable:
    s=C[members[c]]
    print(f"  {c:>5}{len(members[c]):>7}   ({s.mean(0)[0]:+.2f},{s.mean(0)[1]:+.2f},{s.mean(0)[2]:+.2f})"
          f"   ({s.std(0)[0]:.2f},{s.std(0)[1]:.2f},{s.std(0)[2]:.2f})")

# ── C-2. 최근접 점 배정으로 조각 3 쪼개기 ────────────────────────
print(); print("="*68); print("C-2. 최근접 '점' 기준 배정"); print("="*68)
mob=o3d.io.read_triangle_mesh(str(S/"diag_objects_nearest.ply"))
with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
    ci,_,ca=mob.cluster_connected_triangles()
ci=np.asarray(ci);ca=np.asarray(ca);Vo=np.asarray(mob.vertices);To=np.asarray(mob.triangles)
k3=int(np.argsort(-ca)[0])
vi=np.unique(To[np.where(ci==k3)[0]]); P=Vo[vi]
print(f"  대상: 조각 {k3}  {ca[k3]:.2f}㎡  정점 {len(P):,}")
trees={c:cKDTree(np.vstack([obs[j][2] for j in members[c]])) for c in stable}
dist=np.full((len(P),len(stable)),1e9)
for a,c in enumerate(stable):
    dist[:,a],_=trees[c].query(P,k=1)
assign=dist.argmin(1); dmin=dist.min(1)
print(f"  가장 가까운 군집 점까지: 중앙 {np.median(dmin):.3f}m  90% {np.percentile(dmin,90):.3f}m")
for thr in (0.10,0.20,0.30):
    print(f"    {thr*100:.0f}cm 초과(미배정 후보): {(dmin>thr).mean()*100:5.1f}%")
print()
ok=lambda dd:(0.30<dd[1]<2.2 and 0.15<dd[0]<2.0 and 0.15<dd[2]<2.0)
print(f"  {'군집':>5}{'정점':>9}{'비율':>8}{'가로x높이x깊이':>24}{'세장비':>7}  판정")
outs=[]
for a,c in enumerate(stable):
    sel=(assign==a)&(dmin<=0.30)
    if sel.sum()<200: print(f"  {c:>5}{sel.sum():>9}       —"); continue
    Q=P[sel]; dd=Q.max(0)-Q.min(0)
    L=max(dd[0],dd[2]); Wd=min(dd[0],dd[2]); el=L/max(Wd,1e-6)
    lying = 1.3<L<2.2 and 0.25<Wd<0.8 and el>=2.5
    print(f"  {c:>5}{sel.sum():>9}{sel.sum()/len(P)*100:>7.1f}%   {dd[0]:5.2f}x{dd[1]:5.2f}x{dd[2]:5.2f}m"
          f"{el:>7.1f}  {'✅ 누운사람' if lying else ('✅ 크기통과' if ok(dd) else '❌ 범위밖')}")
    outs.append((c,sel,dd))
unass=(dmin>0.30).mean()*100
print(f"\n  미배정(30cm 초과): {unass:.1f}%   (5차 중심점 기준은 14.8%였다)")
# 미배정 정점이 어디에 몰려 있나
if (dmin>0.30).any():
    U=P[dmin>0.30]; h=U[:,1]-FLOOR
    print(f"  미배정 정점 높이: 중앙 {np.median(h):.2f}m  범위 {h.min():.2f}~{h.max():.2f}m")
for c,sel,dd in outs:
    m2=o3d.geometry.TriangleMesh(mob)
    keep=np.array([all(sel[np.searchsorted(vi,v)] for v in t) for t in To[np.where(ci==k3)[0]]])
    if keep.sum()<50: continue
    m2.triangles=o3d.utility.Vector3iVector(To[np.where(ci==k3)[0]][keep])
    m2.remove_unreferenced_vertices(); m2.compute_vertex_normals()
    o3d.io.write_triangle_mesh(str(S/f"diag_person3d_{c}.ply"), m2)
np.save("/tmp/assign_members.npy", np.array([len(members[c]) for c in stable]))
json.dump({"stable":[int(c) for c in stable]}, open("/tmp/stable.json","w"))
print(f"\n  저장: diag_person3d_*.ply")
