#!/usr/bin/env python3
"""2. 군집 근거 조각의 크기 필터 면제 — v1~v3 시뮬레이션 (open3d 전용).

규칙 변경안:
  - 고신뢰(계층1) 군집이 뒷받침하는 조각 → 사람으로 인정 (크기 필터 미적용)
  - 군집 뒷받침이 없는 조각 → 기존 크기 필터, 범위 밖이면 "확인 필요"

파이프라인은 건드리지 않는다. 결과만 시뮬레이션해 현행과 비교한다.
"""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d
from scipy.spatial import cKDTree

S=Path(sys.argv[1]); RAD=0.374; CONF=0.5; AMIN=0.15
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
DW,DH=meta["depth_width"],meta["depth_height"]
sx,sy=DW/meta["video_frame_width"],DH/meta["video_frame_height"]
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
near={int(k):v for k,v in json.load(open(S/"diag_nearest_map.json")).items()}
zi=np.load(S/"diag_inst_nearest.npz")
zm=np.load(S/"diag_masks_nearest.npz")
ok=lambda d:(0.30<d[1]<2.2 and 0.15<d[0]<2.0 and 0.15<d[2]<2.0)

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

# ── 계층1 뼈대 군집 ────────────────────────────────────────────
obs1=[]
frame_of_row={}
for i,r in enumerate(rows):
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2" or i not in near: continue
    fi=near[i]; frame_of_row[i]=fi
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    I=[(zi[f"{fi}_{k}"],float(zi[f"{fi}_{k}_conf"][0])) for k in range(n)]
    if not any(c>=CONF for _,c in I): continue
    d=clean(np.fromfile(S/"depth"/r["depth_file"],dtype="<f4").reshape(DH,DW))
    R=q2R(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")]); T=R@np.diag([1.,-1.,-1.])
    fx,fy=float(p["fx"])*sx,float(p["fy"])*sy; cx,cy=float(p["cx"])*sx,float(p["cy"])*sy
    for ki,(m,c) in enumerate(I):
        if c<CONF: continue
        vv,uu=np.nonzero(m&(d>0.2)&(d<4.0))
        if len(vv)<120: continue
        zz=d[vv,uu]; med=np.median(zz); s=np.abs(zz-med)<0.6
        if s.sum()<120: continue
        vv,uu,zz=vv[s],uu[s],zz[s]
        X=(uu-cx)/fx*zz; Y=(vv-cy)/fy*zz
        obs1.append((i,fi,np.stack([X,Y,zz],1)@T.T+t,ki))
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
print(f"계층1 관측 {len(obs1)} → 뼈대 군집 {len(members)}개, 안정 {len(stable)}개")

# ── 현행 규칙 재현 ─────────────────────────────────────────────
mob=o3d.io.read_triangle_mesh(str(S/"fused_objects.ply"))
with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
    ci,_,ca=mob.cluster_connected_triangles()
ci=np.asarray(ci); ca=np.asarray(ca)
Vo=np.asarray(mob.vertices); To=np.asarray(mob.triangles)
cand=[k for k in range(len(ca)) if ca[k]>0.05]
cents={k:Vo[To[np.where(ci==k)[0]]].reshape(-1,3).mean(0) for k in cand}
groups=[]; used=set()
for k in sorted(cand,key=lambda x:-ca[x]):
    if k in used: continue
    g=[k]; used.add(k)
    for j in cand:
        if j in used: continue
        if np.linalg.norm(cents[j]-cents[k])<0.8: g.append(j); used.add(j)
    groups.append(g)

def submesh(tri_idx):
    s=o3d.geometry.TriangleMesh(mob)
    s.triangles=o3d.utility.Vector3iVector(To[tri_idx])
    s.remove_unreferenced_vertices()
    return s

cur_p=cur_r=0
for g in groups:
    ti=np.concatenate([np.where(ci==k)[0] for k in g]); s=submesh(ti)
    pts=np.asarray(s.vertices)
    if len(pts)<50: continue
    d=pts.max(0)-pts.min(0); a=s.get_surface_area()
    if not ok(d):
        if a>=AMIN: cur_r+=1
    elif a>=AMIN: cur_p+=1
print(f"[현행] 사람 {cur_p}명 / 확인 필요 {cur_r}개")

# ── 변경안 ─────────────────────────────────────────────────────
TC=To[:,0]*0
tc_pos=Vo[To].mean(1)                       # 삼각형 중심
dist=np.full((len(To),len(stable)),1e9)
for a_,c in enumerate(stable): dist[:,a_],_=trees[c].query(tc_pos,k=1)
asg=dist.argmin(1); dmin=dist.min(1); inR=dmin<=RAD

new_person=[]; new_review=[]
# ⚠️ 한 사람의 몸이 여러 연결 성분(group)으로 끊겨 나온다.
#    group×cluster로 세면 같은 사람을 여러 번 센다 → **군집 단위로 병합**한다.
allt=np.concatenate([np.concatenate([np.where(ci==k)[0] for k in g]) for g in groups])
for a_,c in enumerate(stable):
    sel=allt[(asg[allt]==a_)&inR[allt]]
    if len(sel)<50: continue
    s=submesh(sel); pts=np.asarray(s.vertices)
    if len(pts)<50: continue
    d=pts.max(0)-pts.min(0); ar=s.get_surface_area()
    if ar<AMIN: continue
    new_person.append({"g":"all","c":int(c),"n":len(pts),"d":d,"a":ar,
                       "ok":ok(d),"tri":sel})
rest=allt[~inR[allt]]
if len(rest)>=50:
    # 근거 없는 나머지는 연결 성분으로 나눠 기존 크기 필터를 적용
    sub=submesh(rest)
    with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
        rci,_,rca=sub.cluster_connected_triangles()
    rci=np.asarray(rci); rca=np.asarray(rca)
    rV=np.asarray(sub.vertices); rT=np.asarray(sub.triangles)
    for k in range(len(rca)):
        if rca[k]<AMIN: continue
        ti=np.where(rci==k)[0]
        pts=rV[rT[ti]].reshape(-1,3)
        d=pts.max(0)-pts.min(0)
        e={"g":"rest","c":-1,"n":len(np.unique(rT[ti])),"d":d,"a":float(rca[k]),
           "ok":ok(d),"tri":rest[ti]}
        (new_person if ok(d) else new_review).append(e)
print(f"[변경안] 사람 {len(new_person)}명 / 확인 필요 {len(new_review)}개")
print(f"\n  {'조각':>10}{'근거군집':>9}{'정점':>8}{'면적':>8}{'가로x높이x깊이':>23}  크기필터")
for p in new_person+new_review:
    tag=(f"c{p['c']}" if p['c']>=0 else "무근거")
    d=p["d"]
    st=("통과" if p["ok"] else ("**면제로 인정**" if p["c"]>=0 else "확인 필요"))
    print(f"  {tag:>10}{('O' if p['c']>=0 else '-'):>9}{p['n']:>8}{p['a']:>7.2f}\u33a1"
          f"   {d[0]:5.2f}x{d[1]:5.2f}x{d[2]:5.2f}m  {st}")

# ── 2-3. 새로 인정된 조각의 투영 검증 ──────────────────────────
newly=new_person   # 면제분만이 아니라 전부 — 비교 기준이 필요하다
print(f"\n2-3. 인정된 조각 {len(newly)}개의 투영 검증 (면제분 ★)")
if newly:
    print(f"  {'조각':>10}{'검사프레임':>10}{'사람마스크 적중률':>18}")
for p in newly:
    V=np.asarray(submesh(p["tri"]).vertices)
    hit=tot=0; nf=0
    for i,fi in frame_of_row.items():
        if str(fi) not in zm.files: continue
        pp=poses[rows[i]["timestamp"]]
        R=q2R(*[float(pp[x]) for x in ("qx","qy","qz","qw")])
        t=np.array([float(pp[x]) for x in ("tx","ty","tz")])
        Rc=np.diag([1.,-1.,-1.])@R.T; tc=-Rc@t
        fx,fy=float(pp["fx"])*sx,float(pp["fy"])*sy
        cx,cy=float(pp["cx"])*sx,float(pp["cy"])*sy
        def proj(X):
            q=X@Rc.T+tc; mm=q[:,2]>0.2
            u=fx*q[mm,0]/q[mm,2]+cx; v=fy*q[mm,1]/q[mm,2]+cy; z=q[mm,2]
            s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
            return u[s].astype(int),v[s].astype(int),z[s]
        ua,va,za=proj(Vo)
        if len(ua)==0: continue
        zb=np.full((DH,DW),np.inf,np.float32); np.minimum.at(zb,(va,ua),za)
        u,v,z=proj(V)
        if len(u)<50: continue
        vis=z<=zb[v,u]+0.02
        if vis.sum()<50: continue
        m=zm[str(fi)]
        hit+=int(m[v[vis],u[vis]].sum()); tot+=int(vis.sum()); nf+=1
    tag=(f"c{p['c']}" if p['c']>=0 else "무근거")+("" if p["ok"] else " \u2605")
    print(f"  {tag:>10}{nf:>10}{(hit/max(tot,1))*100:>17.1f}%")

# ── 0. "조각 하나 = 한 사람" 투영 대응 판정 ────────────────────
# 각 계층1 인스턴스의 마스크를, 조각들이 각각 몇 % 덮는지 보고
# **정확히 한 조각**이 덮는지 센다. (세장비 대신 쓰는 직접 판정)
def piece_sets(tag):
    if tag=="cur":
        out=[]
        for f in sorted(S.glob("fused_person_*.ply")):
            V=np.asarray(o3d.io.read_triangle_mesh(str(f)).vertices)
            out.append((f.stem[-2:],V))
        return out
    return [((f"c{p['c']}" if p['c']>=0 else "무근거"),
             np.asarray(submesh(p["tri"]).vertices)) for p in new_person]

for tag,name in (("cur","현행 fused_person_*"),("new","변경안 조각")):
    PS=piece_sets(tag)
    cnt={0:0,1:0,2:0,3:0}
    for i,fi,P3,ki in obs1:
        if f"{fi}_{ki}" not in zi.files: continue
        m=zi[f"{fi}_{ki}"]
        pp=poses[rows[i]["timestamp"]]
        R=q2R(*[float(pp[x]) for x in ("qx","qy","qz","qw")])
        t=np.array([float(pp[x]) for x in ("tx","ty","tz")])
        Rc=np.diag([1.,-1.,-1.])@R.T; tc=-Rc@t
        fx,fy=float(pp["fx"])*sx,float(pp["fy"])*sy
        cx,cy=float(pp["cx"])*sx,float(pp["cy"])*sy
        def pj(X):
            q=X@Rc.T+tc; mm2=q[:,2]>0.2
            u=fx*q[mm2,0]/q[mm2,2]+cx; v=fy*q[mm2,1]/q[mm2,2]+cy; z=q[mm2,2]
            s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
            return u[s].astype(int),v[s].astype(int),z[s]
        ua,va,za=pj(Vo)
        if len(ua)==0: continue
        zb=np.full((DH,DW),np.inf,np.float32); np.minimum.at(zb,(va,ua),za)
        hits=0
        for _,V in PS:
            u,v,z=pj(V)
            if len(u)==0: continue
            vis=z<=zb[v,u]+0.02
            if vis.sum()==0: continue
            img=np.zeros((DH,DW),bool); img[v[vis],u[vis]]=True
            d2=img.copy()
            for dy in(-1,0,1):
                for dx in(-1,0,1): d2|=np.roll(np.roll(img,dy,0),dx,1)
            if (m&d2).sum()/max(m.sum(),1)>=0.30: hits+=1
        cnt[min(hits,3)]=cnt.get(min(hits,3),0)+1
    tot=sum(cnt.values())
    print(f"\n0. 대응 판정 [{name}]  고신뢰 인스턴스 {tot}개")
    print(f"   덮는 조각 0개 {cnt[0]:>4} ({cnt[0]/max(tot,1)*100:4.1f}%)  ← 놓침")
    print(f"   덮는 조각 1개 {cnt[1]:>4} ({cnt[1]/max(tot,1)*100:4.1f}%)  ← 정상")
    print(f"   덮는 조각 2개 {cnt[2]:>4} ({cnt[2]/max(tot,1)*100:4.1f}%)")
    print(f"   덮는 조각 3+  {cnt[3]:>4} ({cnt[3]/max(tot,1)*100:4.1f}%)")
