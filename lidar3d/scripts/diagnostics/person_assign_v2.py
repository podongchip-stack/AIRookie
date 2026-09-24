#!/usr/bin/env python3
"""B. 중복 검출을 먼저 병합한 뒤 cannot-link 군집화 (진단 전용).

6차 실패 원인: 같은 사람의 **중복 검출**을 cannot-link가 "다른 사람"으로
강제해 3D 조각을 찢었다. (실측: 프레임398 인스턴스3이 인스턴스1에 99.3% 포함)

두 방식을 비교한다.
  B-1) 포함비율 기준 중복 병합 후 cannot-link
  B-2) 신뢰도 0.5 이상끼리만 cannot-link

C-2(최근접 점 배정)는 성공했으므로 그대로 쓴다.
"""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d
from scipy.spatial import cKDTree

S=Path(sys.argv[1]); MODE=sys.argv[2] if len(sys.argv)>2 else "merge"
FLOOR=-0.71
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
W,H=meta["depth_width"],meta["depth_height"]; VW,VH=meta["video_frame_width"],meta["video_frame_height"]
sx,sy=W/VW,H/VH
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
near={int(k):v for k,v in json.load(open(S/"diag_nearest_map.json")).items()}
zi=np.load(S/"diag_inst_nearest.npz")

# ── B-1 임계값 근거 ──────────────────────────────────────────────
#   실측 분포(856쌍): 포함비율 중앙 0.011 / 75% 0.913
#   → 두 무리가 확연히 갈리고 그 사이가 비어 있다. 0.7은 그 골짜기에 있다.
CONTAIN=0.70
CONF_MIN=0.50

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

def instances(fi):
    """반환: [(마스크, 신뢰도, 계층)] — 계층 1=뼈대, 3=불확실"""
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    I=[(zi[f"{fi}_{k}"], float(zi[f"{fi}_{k}_conf"][0])) for k in range(n)]
    if MODE=="tier":
        # 3계층: 뼈대 / 중복 제거 / 불확실 보존
        hi=[x for x in I if x[1]>=CONF_MIN]
        out=[]
        for m,c in I:
            if c>=CONF_MIN: out.append((m,c,1)); continue
            dup=any((m&hm).sum() and (m&hm).sum()/m.sum()>=CONTAIN for hm,_ in hi)
            if not dup: out.append((m,c,3))     # 계층2(중복)는 버린다
        return out
    if MODE=="conf":
        return [(m,c,1) for m,c in I if c>=CONF_MIN]
    if MODE!="merge": return [(m,c,1) for m,c in I]
    # 포함비율이 높은 쌍을 union-find로 묶는다
    par=list(range(len(I)))
    def find(x):
        while par[x]!=x: par[x]=par[par[x]]; x=par[x]
        return x
    for a in range(len(I)):
        for b in range(a+1,len(I)):
            ma,mb=I[a][0],I[b][0]
            inter=(ma&mb).sum()
            if inter==0: continue
            if inter/min(ma.sum(),mb.sum())>=CONTAIN:
                par[find(a)]=find(b)
    grp={}
    for i in range(len(I)):
        grp.setdefault(find(i),[]).append(i)
    out=[]
    for g in grp.values():
        m=np.zeros_like(I[0][0])
        for i in g: m|=I[i][0]
        out.append((m,max(I[i][1] for i in g),1))
    return out

print(f"모드: {MODE}  (CONTAIN={CONTAIN}, CONF_MIN={CONF_MIN})\n")
obs=[]
for i,r in enumerate(rows):
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2" or i not in near: continue
    fi=near[i]; I=instances(fi)
    if not I: continue
    d=clean(np.fromfile(S/"depth"/r["depth_file"],dtype="<f4").reshape(H,W))
    R=R_(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")]); T=R@np.diag([1.,-1.,-1.])
    fx,fy=float(p["fx"])*sx,float(p["fy"])*sy; cx,cy=float(p["cx"])*sx,float(p["cy"])*sy
    for m,cf,tier in I:
        vv,uu=np.nonzero(m&(d>0.2)&(d<4.0))
        if len(vv)<120: continue
        zz=d[vv,uu]; med=np.median(zz); s=np.abs(zz-med)<0.6
        if s.sum()<120: continue
        vv,uu,zz=vv[s],uu[s],zz[s]
        X=(uu-cx)/fx*zz; Y=(vv-cy)/fy*zz
        P=np.stack([X,Y,zz],1)@T.T+t
        obs.append((fi,P.mean(0),P,tier))
C=np.array([o[1] for o in obs]); FR=np.array([o[0] for o in obs])
print(f"인스턴스 관측 {len(obs)}개 (6차 병합 전: 946개)")
cnt=[len(instances(f)) for f in sorted({v for v in near.values()})]
print(f"프레임당 인스턴스: 중앙 {np.median(cnt):.0f}  최대 {max(cnt)}  "
      f"3 초과 {(np.array(cnt)>3).sum()}프레임\n")

RAD=0.374
order=np.argsort([-len(o[2]) for o in obs])
lbl=-np.ones(len(obs),int); members=[]; frames_of=[]
TIER=np.array([o[3] for o in obs])
for i in order:
    best=-1; bestd=1e9
    for c,mem in enumerate(members):
        # cannot-link는 **계층1끼리만** 적용한다.
        # 계층3(불확실)은 같은 사람의 저신뢰 재검출일 수 있으므로 강제 분리하지 않는다.
        if TIER[i]==1 and any(TIER[j]==1 for j in mem) and FR[i] in frames_of[c]: continue
        dmin=min(np.linalg.norm(C[i]-C[j]) for j in mem)
        if dmin<RAD and dmin<bestd: best,bestd=c,dmin
    if best<0: members.append([i]); frames_of.append({FR[i]}); lbl[i]=len(members)-1
    else: members[best].append(i); frames_of[best].add(FR[i]); lbl[i]=best
stable=[c for c,mem in enumerate(members) if len(mem)>=8]
print(f"군집 {len(members)}개, 안정 군집 {len(stable)}개 (6차: 32/16)")
for c in stable:
    s=C[members[c]]
    print(f"  군집{c:>3} 관측{len(members[c]):>4}  중심({s.mean(0)[0]:+.2f},{s.mean(0)[1]:+.2f},{s.mean(0)[2]:+.2f})"
          f"  흩어짐({s.std(0)[0]:.2f},{s.std(0)[1]:.2f},{s.std(0)[2]:.2f})")

mob=o3d.io.read_triangle_mesh(str(S/"fused_objects.ply"))
with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
    ci,_,ca=mob.cluster_connected_triangles()
ci=np.asarray(ci);ca=np.asarray(ca);Vo=np.asarray(mob.vertices);To=np.asarray(mob.triangles)
k3=int(np.argsort(-ca)[0]); tri=np.where(ci==k3)[0]
vi=np.unique(To[tri]); P=Vo[vi]
print(f"\n대상 조각 {k3}: {ca[k3]:.2f}㎡ 정점 {len(P):,}")
trees={c:cKDTree(np.vstack([obs[j][2] for j in members[c]])) for c in stable}
dist=np.full((len(P),len(stable)),1e9)
for a,c in enumerate(stable): dist[:,a],_=trees[c].query(P,k=1)
assign=dist.argmin(1); dmin=dist.min(1)
ok=lambda dd:(0.30<dd[1]<2.2 and 0.15<dd[0]<2.0 and 0.15<dd[2]<2.0)
print(f"\n{'군집':>5}{'정점':>9}{'비율':>8}{'가로x높이x깊이':>24}{'세장비':>7}  판정")
nlying=0
for a,c in enumerate(stable):
    sel=(assign==a)&(dmin<=0.30)
    if sel.sum()<200: continue
    Q=P[sel]; dd=Q.max(0)-Q.min(0)
    L=max(dd[0],dd[2]); Wd=min(dd[0],dd[2]); el=L/max(Wd,1e-6)
    lying=1.3<L<2.2 and 0.25<Wd<0.8 and el>=2.5
    nlying+=lying
    print(f"  {c:>5}{sel.sum():>9}{sel.sum()/len(P)*100:>7.1f}%   {dd[0]:5.2f}x{dd[1]:5.2f}x{dd[2]:5.2f}m"
          f"{el:>7.1f}  {'✅ 누운사람' if lying else ('△ 크기통과' if ok(dd) else '❌ 범위밖')}")
print(f"\n  누운 사람 형태(세장비≥2.5) 조각: {nlying}개   미배정: {(dmin>0.30).mean()*100:.1f}%")
# 투영 검증용으로 저장
import glob as _g, os as _o
for f in _g.glob(str(S/f"diag_v2_{MODE}_*.ply")): _o.remove(f)
for a,c in enumerate(stable):
    sel=(assign==a)&(dmin<=0.30)
    if sel.sum()<200: continue
    keep=np.array([all(sel[np.searchsorted(vi,v)] for v in t) for t in To[tri]])
    if keep.sum()<50: continue
    m2=o3d.geometry.TriangleMesh(mob)
    m2.triangles=o3d.utility.Vector3iVector(To[tri][keep])
    m2.remove_unreferenced_vertices(); m2.compute_vertex_normals()
    o3d.io.write_triangle_mesh(str(S/f"diag_v2_{MODE}_{c}.ply"), m2)
print(f"  저장: diag_v2_{MODE}_*.ply")
