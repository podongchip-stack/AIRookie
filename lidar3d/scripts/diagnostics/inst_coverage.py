#!/usr/bin/env python3
"""1. B-3 재측정 — 중심점이 아니라 형상으로 (open3d 전용).

9차 B-3은 계층3 인스턴스를 "중심점이 계층1 군집 반경 안인가"로 판정했다.
그런데 정점 배정률은 100%였다. 놓친 것들은 화면 가장자리의 부분 검출이라
중심점이 몸통에서 치우쳤을 수 있다.

이번 측정: 각 계층3 인스턴스의 마스크 영역을, **사람 조각들**이 가림(z-buffer)
처리를 거쳐 실제로 몇 % 덮는지 본다. 덮음이 높으면 "몸은 이미 결과물에 있다".

판정 기준(실행 전 확정): 계층3 인스턴스 중 덮음 < 10% 인 것 = 0개
"""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d
from scipy.spatial import cKDTree

S=Path(sys.argv[1]); RAD=0.374; CONF=0.5
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
DW,DH=meta["depth_width"],meta["depth_height"]
VW,VH=meta["video_frame_width"],meta["video_frame_height"]
sx,sy=DW/VW,DH/VH
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
near={int(k):v for k,v in json.load(open(S/"diag_nearest_map.json")).items()}
zi=np.load(S/"diag_inst_nearest.npz")

def q2R(a,b,c,d):
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

# ── 계층 나누기 (9차와 동일 규칙) ──────────────────────────────
obs1=[]; obs3=[]
for i,r in enumerate(rows):
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2" or i not in near: continue
    fi=near[i]
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    I=[(zi[f"{fi}_{k}"],float(zi[f"{fi}_{k}_conf"][0]),k) for k in range(n)]
    hi=[x for x in I if x[1]>=CONF]
    d=clean(np.fromfile(S/"depth"/r["depth_file"],dtype="<f4").reshape(DH,DW))
    R=q2R(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")]); T=R@np.diag([1.,-1.,-1.])
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
        if c>=CONF: obs1.append((i,fi,P))
        else:
            dup=any((m&hm).sum() and (m&hm).sum()/m.sum()>=0.7 for hm,_,_ in hi)
            if not dup: obs3.append((i,fi,k,c,P))
print(f"계층1 관측 {len(obs1)} / 계층3 관측 {len(obs3)}  (R={RAD}m)")

# ── 계층1 뼈대 군집 ────────────────────────────────────────────
C=np.array([o[2].mean(0) for o in obs1]); FR=np.array([o[1] for o in obs1])
order=np.argsort([-len(o[2]) for o in obs1]); members=[]; frames_of=[]
for i in order:
    best=-1; bd=1e9
    for c,mem in enumerate(members):
        if FR[i] in frames_of[c]: continue
        dm=min(np.linalg.norm(C[i]-C[j]) for j in mem)
        if dm<RAD and dm<bd: best,bd=c,dm
    if best<0: members.append([i]); frames_of.append({FR[i]})
    else: members[best].append(i); frames_of[best].add(FR[i])
stable=[c for c,m in enumerate(members) if len(m)>=8]
trees={c:cKDTree(np.vstack([obs1[j][2] for j in members[c]])) for c in stable}
print(f"뼈대 군집 {len(members)}개, 안정 {len(stable)}개\n")

# ── 9차 방식(중심점) 재현 ──────────────────────────────────────
missed=[]
for oi,(di,fi,k,cf,P) in enumerate(obs3):
    cen=P.mean(0)
    dm=min(t.query(cen[None],k=1)[0][0] for t in trees.values())
    if dm>RAD: missed.append((oi,di,fi,k,cf,dm))
print(f"[9차 재현] 중심점 기준 흡수 {len(obs3)-len(missed)} / "
      f"어디에도 없음 {len(missed)}\n")

# ── 사람 조각 점집합 ───────────────────────────────────────────
def verts(p):
    m=o3d.io.read_triangle_mesh(str(p))
    V=np.asarray(m.vertices)
    if len(V)==0:
        V=np.asarray(o3d.io.read_point_cloud(str(p)).points)
    return V
lay=sorted(S.glob("diag_lay_[0-9]*.ply")); per=sorted(S.glob("fused_person_*.ply"))
Ppl=[verts(p) for p in lay+per]
PERSON=np.vstack(Ppl)
print(f"사람 조각 {len(lay)}(층분리)+{len(per)}(기존) = 정점 {len(PERSON):,}")
OCC=np.asarray(o3d.io.read_triangle_mesh(str(S/"fused_objects.ply")).vertices)
tp=cKDTree(PERSON)

# ── 가림 처리 투영으로 덮음 측정 ────────────────────────────────
def cover(di,fi,k):
    """인스턴스 마스크를 사람 조각이 덮는 비율."""
    p=poses[rows[di]["timestamp"]]
    R=q2R(*[float(p[x]) for x in ("qx","qy","qz","qw")])
    t=np.array([float(p[x]) for x in ("tx","ty","tz")])
    Rc=np.diag([1.,-1.,-1.])@R.T; tc=-Rc@t
    fx,fy=float(p["fx"])*sx,float(p["fy"])*sy
    cx,cy=float(p["cx"])*sx,float(p["cy"])*sy
    def proj(V):
        pc=V@Rc.T+tc; mm=pc[:,2]>0.2
        u=fx*pc[mm,0]/pc[mm,2]+cx; v=fy*pc[mm,1]/pc[mm,2]+cy; z=pc[mm,2]
        s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
        return u[s].astype(int),v[s].astype(int),z[s]
    ua,va,za=proj(OCC)
    zb=np.full((DH,DW),np.inf,np.float32); np.minimum.at(zb,(va,ua),za)
    up,vp,zp=proj(PERSON)
    vis=zp<=zb[vp,up]+0.02
    img=np.zeros((DH,DW),bool); img[vp[vis],up[vis]]=True
    # 투영은 점이라 구멍이 생긴다 — 3x3 팽창으로 메운다
    d=img.copy()
    for dy in(-1,0,1):
        for dx in(-1,0,1):
            d|=np.roll(np.roll(img,dy,0),dx,1)
    m=zi[f"{fi}_{k}"]
    return (m&d).sum()/max(m.sum(),1), m.sum()

print("\n"+"="*72)
print("1-1/1-2. 9차가 놓친 인스턴스의 덮음")
print("="*72)
print(f"  {'프레임':>7}{'인스':>5}{'conf':>7}{'중심거리':>9}{'마스크px':>9}{'덮음':>8}")
for oi,di,fi,k,cf,dm in missed:
    cv,npx=cover(di,fi,k)
    print(f"  {fi:>7}{k:>5}{cf:>7.2f}{dm:>8.2f}m{npx:>9}{cv*100:>7.1f}%")

print("\n"+"="*72)
print("1-3. 계층3 인스턴스 359개 전체 덮음 분포")
print("="*72)
cov=np.array([cover(di,fi,k)[0] for di,fi,k,cf,P in
              [(o[0],o[1],o[2],o[3],o[4]) for o in obs3]])
hist,edges=np.histogram(cov,bins=10,range=(0,1))
for i in range(10):
    bar="█"*int(hist[i]/max(hist.max(),1)*44)
    print(f"  {edges[i]:.1f}~{edges[i+1]:.1f}: {hist[i]:>5} {bar}")
print(f"\n  중앙 {np.median(cov)*100:.1f}%  평균 {cov.mean()*100:.1f}%")
for t in (0.10,0.30,0.50):
    print(f"    덮음<{t*100:.0f}%: {(cov<t).sum():>4}개 ({(cov<t).mean()*100:.1f}%)")
print(f"\n  ▶ 판정 기준(덮음<10% = 0개): "
      f"{'통과' if (cov<0.10).sum()==0 else f'실패 — {(cov<0.10).sum()}개'}")
np.save("/tmp/inst_cov.npy",cov)
json.dump([[int(o[1]),int(o[2]),float(o[3])] for o in obs3],open("/tmp/obs3.json","w"))
