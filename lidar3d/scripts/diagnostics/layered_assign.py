#!/usr/bin/env python3
"""B. 층 분리 배정 — 놓치지 않기와 합치지 않기의 양립 (open3d 전용).

8차 실패: 계층3을 **군집 생성 단계**에 넣어 군집이 쪼개졌다.
이번: 계층을 단계별로 분리한다.

  1) 군집 뼈대  = 계층1(conf>=0.5)만, cannot-link 적용   ← 7차 B-2 그대로
  2) 융합 형상  = 기존 fused_objects.ply (모든 계층 마스크로 만들어진 것)
  3) 정점 배정  = 계층1 군집 점들 중 최근접, 반경 R 이내만
  4) R 밖 정점  = 버리지 않고 연결 성분으로 묶어 "불확실한 사람"으로 저장
"""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d
from scipy.spatial import cKDTree

S=Path(sys.argv[1])
# B-4. 반경 근거: 7차와 동일. 분리에 성공했던 군집14의 실측 흩어짐
#      (0.05, 0.10, 0.15)m → 3축 결합 표준편차 0.187m → 그 2배.
#      ⚠️ 군집14는 관측 13회뿐이라 흩어짐이 과소평가됐을 수 있다.
RAD=0.374; CONF=0.5
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
W,H=meta["depth_width"],meta["depth_height"]
sx,sy=W/meta["video_frame_width"],H/meta["video_frame_height"]
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
near={int(k):v for k,v in json.load(open(S/"diag_nearest_map.json")).items()}
zi=np.load(S/"diag_inst_nearest.npz")

def R_(a,b,c,d):
    return np.array([[1-2*(b*b+c*c),2*(a*b-c*d),2*(a*c+b*d)],
                     [2*(a*b+c*d),1-2*(a*a+c*c),2*(b*c-a*d)],
                     [2*(a*c-b*d),2*(b*c+a*d),1-2*(a*a+b*b)]])
def clean(x,mx=4.0,er=0.04):
    x=x.copy(); x[(x<=0)|(x>mx)]=0
    pad=np.pad(x,1,constant_values=0)
    nb=np.stack([pad[:-2,1:-1],pad[2:,1:-1],pad[1:-1,:-2],pad[1:-1,2:]])
    with np.errstate(divide="ignore",invalid="ignore"):
        rel=np.abs(nb-x[None])/np.maximum(x[None],1e-6)
    x[np.nanmax(np.where(nb>0,rel,0),axis=0)>er]=0
    return x

# ── 1) 계층1 관측만으로 뼈대 군집 ──────────────────────────────
obs1=[]; obs3=[]
for i,r in enumerate(rows):
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2" or i not in near: continue
    fi=near[i]
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    I=[(zi[f"{fi}_{k}"],float(zi[f"{fi}_{k}_conf"][0]),k) for k in range(n)]
    hi=[x for x in I if x[1]>=CONF]
    d=clean(np.fromfile(S/"depth"/r["depth_file"],dtype="<f4").reshape(H,W))
    RR=R_(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")]); T=RR@np.diag([1.,-1.,-1.])
    fx,fy=float(p["fx"])*sx,float(p["fy"])*sy; cx,cy=float(p["cx"])*sx,float(p["cy"])*sy
    def lift(m):
        vv,uu=np.nonzero(m&(d>0.2)&(d<4.0))
        if len(vv)<120: return None
        zz=d[vv,uu]; med=np.median(zz); s=np.abs(zz-med)<0.6
        if s.sum()<120: return None
        vv,uu,zz=vv[s],uu[s],zz[s]
        X=(uu-cx)/fx*zz; Y=(vv-cy)/fy*zz
        return np.stack([X,Y,zz],1)@T.T+t
    for m,c,k in I:
        P=lift(m)
        if P is None: continue
        if c>=CONF: obs1.append((fi,P))
        else:
            dup=any((m&hm).sum() and (m&hm).sum()/m.sum()>=0.7 for hm,_,_ in hi)
            if not dup: obs3.append((fi,k,P))
print(f"계층1 관측 {len(obs1)}개 / 계층3 관측 {len(obs3)}개  (반경 R={RAD}m)\n")

C=np.array([o[1].mean(0) for o in obs1]); FR=np.array([o[0] for o in obs1])
order=np.argsort([-len(o[1]) for o in obs1]); members=[]; frames_of=[]
for i in order:
    best=-1; bd=1e9
    for c,mem in enumerate(members):
        if FR[i] in frames_of[c]: continue
        dm=min(np.linalg.norm(C[i]-C[j]) for j in mem)
        if dm<RAD and dm<bd: best,bd=c,dm
    if best<0: members.append([i]); frames_of.append({FR[i]})
    else: members[best].append(i); frames_of[best].add(FR[i])
stable=[c for c,m in enumerate(members) if len(m)>=8]
print(f"뼈대 군집 {len(members)}개, 안정 {len(stable)}개")

# ── 2)3)4) 융합 형상에 배정 ────────────────────────────────────
mob=o3d.io.read_triangle_mesh(str(S/"fused_objects.ply"))
with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
    ci,_,ca=mob.cluster_connected_triangles()
ci=np.asarray(ci);ca=np.asarray(ca);Vo=np.asarray(mob.vertices);To=np.asarray(mob.triangles)
k3=int(np.argsort(-ca)[0]); tri=np.where(ci==k3)[0]
vi=np.unique(To[tri]); P=Vo[vi]
trees={c:cKDTree(np.vstack([obs1[j][1] for j in members[c]])) for c in stable}
dist=np.full((len(P),len(stable)),1e9)
for a,c in enumerate(stable): dist[:,a],_=trees[c].query(P,k=1)
assign=dist.argmin(1); dmin=dist.min(1)
inR=dmin<=RAD
ok=lambda x:(0.30<x[1]<2.2 and 0.15<x[0]<2.0 and 0.15<x[2]<2.0)
print(f"\n대상 조각 {k3}: {ca[k3]:.2f}㎡  정점 {len(P):,}")
print(f"  반경 {RAD}m 이내 배정 {inR.sum():,} ({inR.mean()*100:.1f}%)  "
      f"밖 {(~inR).sum():,} ({(~inR).mean()*100:.1f}%)\n")
print(f"B-1. 조각 3 분리 결과")
print(f"  {'군집':>5}{'정점':>9}{'비율':>8}{'가로x높이x깊이':>24}  판정")
npieces=0
parts={}
for a,c in enumerate(stable):
    sel=(assign==a)&inR
    if sel.sum()<200: continue
    Q=P[sel]; d=Q.max(0)-Q.min(0); npieces+=1
    parts[str(c)]=Q
    print(f"  {c:>5}{sel.sum():>9}{sel.sum()/len(P)*100:>7.1f}%   {d[0]:5.2f}x{d[1]:5.2f}x{d[2]:5.2f}m"
          f"  {'✅' if ok(d) else '❌'}")
print(f"  → 조각 {npieces}개")

# 4) R 밖 정점을 연결 성분으로
print(f"\nB-2. 반경 밖 정점의 '불확실한 사람' 조각")
out=np.nonzero(~inR)[0]
if len(out)>=100:
    sub=cKDTree(P[out])
    lab=-np.ones(len(out),int); cur=0
    for i in range(len(out)):
        if lab[i]>=0: continue
        stack=[i]; lab[i]=cur
        while stack:
            j=stack.pop()
            for k in sub.query_ball_point(P[out[j]],0.05):
                if lab[k]<0: lab[k]=cur; stack.append(k)
        cur+=1
    sizes=[(c,(lab==c).sum()) for c in range(cur)]
    sizes=[x for x in sizes if x[1]>=300]
    sizes.sort(key=lambda x:-x[1])
    print(f"  연결 성분 {cur}개, 300정점 이상 {len(sizes)}개")
    for c,n in sizes[:6]:
        Q=P[out[lab==c]]; d=Q.max(0)-Q.min(0)
        parts[f"U{c}"]=Q
        print(f"    불확실{c}: {n:>7}정점  {d[0]:5.2f}x{d[1]:5.2f}x{d[2]:5.2f}m")
else:
    print("  반경 밖 정점이 거의 없음")
np.save("/tmp/lay_assign.npy",np.stack([assign,dmin]))
json.dump({"stable":[int(c) for c in stable],"R":RAD},open("/tmp/lay_meta.json","w"))
for k,Q in parts.items():
    pc=o3d.geometry.PointCloud(); pc.points=o3d.utility.Vector3dVector(Q)
    o3d.io.write_point_cloud(str(S/f"diag_lay_{k}.ply"),pc)
print(f"\n  저장: diag_lay_*.ply ({len(parts)}개)")
