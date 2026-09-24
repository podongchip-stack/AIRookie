#!/usr/bin/env python3
"""2·3·4절 — 면제 단독 / 군집 수 기반 통합 규칙 / 저적중 재분류 (open3d 전용).

통합 규칙: 연결 성분 조각마다, 그 조각을 투영으로 덮는(>=30%) 고신뢰 군집 수를 센다.
  0개  -> 기존 크기 필터, 범위 밖이면 "확인 필요"
  1개  -> 사람으로 인정, 크기 필터 면제, 분리하지 않음
  2개+ -> 이 조각에만 층 분리 배정. 반경 제한 없이 최근접 군집에 전부 배정.

"덮는다"의 정의: 군집 c의 계층1 관측 중, 조각의 가림처리 투영이 그 인스턴스
마스크를 30% 이상 덮는 관측이 **3회 이상**. (1회짜리 우연을 배제하려는 것)
"""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d
from scipy.spatial import cKDTree

S=Path(sys.argv[1]); RAD=0.374; CONF=0.5; AMIN=0.15; COVER=0.30; NEED=3
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
DW,DH=meta["depth_width"],meta["depth_height"]
sx,sy=DW/meta["video_frame_width"],DH/meta["video_frame_height"]
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
near={int(k):v for k,v in json.load(open(S/"diag_nearest_map.json")).items()}
zi=np.load(S/"diag_inst_nearest.npz"); zm=np.load(S/"diag_masks_nearest.npz")
ok=lambda d:(0.30<d[1]<2.2 and 0.15<d[0]<2.0 and 0.15<d[2]<2.0)
print(f"===== {S.name} =====")

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

# ── 계층1 관측 + 뼈대 군집 ────────────────────────────────────
obs1=[]
for i,r in enumerate(rows):
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2" or i not in near: continue
    fi=near[i]
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
print(f"계층1 관측 {len(obs1)} → 뼈대 군집 {len(members)}개, 안정 {len(stable)}개 "
      f"(관측수 {[len(members[c]) for c in stable]})")

# ── 파이프라인과 동일한 조각 만들기 ───────────────────────────
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
def submesh(ti):
    s=o3d.geometry.TriangleMesh(mob); s.triangles=o3d.utility.Vector3iVector(To[ti])
    s.remove_unreferenced_vertices(); return s

# ── 투영 도구 ─────────────────────────────────────────────────
_cache={}
def cam(i):
    if i in _cache: return _cache[i]
    p=poses[rows[i]["timestamp"]]
    R=q2R(*[float(p[x]) for x in ("qx","qy","qz","qw")])
    t=np.array([float(p[x]) for x in ("tx","ty","tz")])
    Rc=np.diag([1.,-1.,-1.])@R.T; tc=-Rc@t
    K=(float(p["fx"])*sx,float(p["fy"])*sy,float(p["cx"])*sx,float(p["cy"])*sy)
    q=Vo@Rc.T+tc; f=q[:,2]>0.2
    u=K[0]*q[f,0]/q[f,2]+K[2]; v=K[1]*q[f,1]/q[f,2]+K[3]
    s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
    zb=np.full((DH,DW),np.inf,np.float32)
    if s.any(): np.minimum.at(zb,(v[s].astype(int),u[s].astype(int)),q[f,2][s])
    _cache[i]=(Rc,tc,K,zb); return _cache[i]
def footprint(V,i):
    Rc,tc,K,zb=cam(i)
    q=V@Rc.T+tc; f=q[:,2]>0.2
    if not f.any(): return None
    u=K[0]*q[f,0]/q[f,2]+K[2]; v=K[1]*q[f,1]/q[f,2]+K[3]; z=q[f,2]
    s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
    if not s.any(): return None
    u=u[s].astype(int); v=v[s].astype(int); z=z[s]
    vis=z<=zb[v,u]+0.02
    if vis.sum()<30: return None
    img=np.zeros((DH,DW),bool); img[v[vis],u[vis]]=True
    d=img.copy()
    for dy in(-1,0,1):
        for dx in(-1,0,1): d|=np.roll(np.roll(img,dy,0),dx,1)
    return d

def backing_clusters(V):
    """이 조각을 덮는 고신뢰 군집 번호 목록."""
    hit={c:0 for c in stable}
    for ci_,c in enumerate(stable):
        for j in members[c]:
            i,fi,_,ki=obs1[j]
            if f"{fi}_{ki}" not in zi.files: continue
            fp=footprint(V,i)
            if fp is None: continue
            m=zi[f"{fi}_{ki}"]
            if (m&fp).sum()/max(m.sum(),1)>=COVER: hit[c]+=1
    return [c for c in stable if hit[c]>=NEED], hit

def hitrate(V):
    """조각의 보이는 투영 화소 중 사람 마스크 안에 든 비율."""
    h=t_=0
    for i,fi in [(i,near[i]) for i in near]:
        if str(fi) not in zm.files: continue
        Rc,tc,K,zb=cam(i)
        q=V@Rc.T+tc; f=q[:,2]>0.2
        if not f.any(): continue
        u=K[0]*q[f,0]/q[f,2]+K[2]; v=K[1]*q[f,1]/q[f,2]+K[3]; z=q[f,2]
        s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
        if not s.any(): continue
        u=u[s].astype(int); v=v[s].astype(int); z=z[s]
        vis=z<=zb[v,u]+0.02
        if vis.sum()<50: continue
        h+=int(zm[str(fi)][v[vis],u[vis]].sum()); t_+=int(vis.sum())
    return h/max(t_,1)

# ── 현행 / 면제 단독 / 통합 규칙 ──────────────────────────────
cur=[]; exempt_only=[]; unified=[]; detail=[]
for gi,g in enumerate(groups):
    ti=np.concatenate([np.where(ci==k)[0] for k in g]); sub=submesh(ti)
    pts=np.asarray(sub.vertices)
    if len(pts)<50: continue
    d=pts.max(0)-pts.min(0); a=sub.get_surface_area()
    if a<AMIN: continue
    bc,hit=backing_clusters(pts)
    hr=hitrate(pts)
    detail.append((gi,len(pts),a,d,bc,hit,hr))
    cur.append(("사람" if ok(d) else "확인", d, a, hr, bc))
    exempt_only.append(("사람" if (bc or ok(d)) else "확인", d, a, hr, bc))
    if len(bc)==0:
        unified.append(("사람" if ok(d) else "확인", d, a, hr, bc, ti))
    elif len(bc)==1:
        unified.append(("사람", d, a, hr, bc, ti))
    else:
        # 2개+ : 이 조각에만 층 분리. 반경 제한 없이 전부 배정.
        tcen=Vo[To[ti]].mean(1)
        dist=np.stack([trees[c].query(tcen,k=1)[0] for c in bc],1)
        asg=dist.argmin(1)
        for a_,c in enumerate(bc):
            sel=ti[asg==a_]
            if len(sel)<50: continue
            s2=submesh(sel); p2=np.asarray(s2.vertices)
            if len(p2)<50: continue
            d2=p2.max(0)-p2.min(0); a2=s2.get_surface_area()
            if a2<AMIN: continue
            unified.append(("사람", d2, a2, hitrate(p2), [c], sel))

print(f"\n3-3. 조각별 근거 군집 수")
print(f"  {'조각':>5}{'정점':>9}{'면적':>8}{'가로x높이x깊이':>23}{'크기':>6}{'근거군집':>10}{'적중률':>8}")
for gi,n,a,d,bc,hit,hr in detail:
    print(f"  g{gi:<4}{n:>9}{a:>7.2f}㎡   {d[0]:5.2f}x{d[1]:5.2f}x{d[2]:5.2f}m"
          f"{'O' if ok(d) else 'X':>6}{str(bc) if bc else '없음':>10}{hr*100:>7.1f}%")
    if len(bc)>1:
        print(f"        ↳ **2개+ → 층 분리 적용**  관측수 "
              f"{ {c:hit[c] for c in bc} }")

def tally(lst):
    return sum(1 for x in lst if x[0]=="사람"), sum(1 for x in lst if x[0]=="확인")
print(f"\n3-1. 세션별 집계")
print(f"  현행      사람 {tally(cur)[0]} / 확인 필요 {tally(cur)[1]}")
print(f"  면제 단독  사람 {tally(exempt_only)[0]} / 확인 필요 {tally(exempt_only)[1]}")
print(f"  통합 규칙  사람 {tally(unified)[0]} / 확인 필요 {tally(unified)[1]}")

# ── 3-2. 투영 대응 표 ─────────────────────────────────────────
def corr(pieces,label):
    cnt={0:0,1:0,2:0,3:0}
    for j in range(len(obs1)):
        i,fi,_,ki=obs1[j]
        if f"{fi}_{ki}" not in zi.files: continue
        m=zi[f"{fi}_{ki}"]; h=0
        for V in pieces:
            fp=footprint(V,i)
            if fp is None: continue
            if (m&fp).sum()/max(m.sum(),1)>=COVER: h+=1
        cnt[min(h,3)]+=1
    t_=sum(cnt.values())
    print(f"  {label:<12}{cnt[0]:>5} ({cnt[0]/max(t_,1)*100:5.1f}%){cnt[1]:>6} "
          f"({cnt[1]/max(t_,1)*100:5.1f}%){cnt[2]:>6}{cnt[3]:>6}")
print(f"\n3-2. 투영 대응 (고신뢰 인스턴스 {len(obs1)}개) — 덮는 조각 수")
print(f"  {'방식':<12}{'0개(놓침)':>12}{'1개(정상)':>13}{'2개':>6}{'3+':>6}")
corr([np.asarray(o3d.io.read_triangle_mesh(str(f)).vertices)
      for f in sorted(S.glob("fused_person_*.ply"))], "현행")
corr([np.asarray(submesh(x[5]).vertices) for x in unified if x[0]=="사람"], "통합 규칙")

# ── 4. 저적중 조각 ────────────────────────────────────────────
print(f"\n4-1. 통합 규칙 '사람' 조각의 적중률 분포")
hrs=sorted([(x[3],x[4]) for x in unified if x[0]=="사람"])
for h,bc in hrs:
    print(f"    {h*100:5.1f}%  근거군집 {bc if bc else '없음'}")
json.dump({"session":S.name,
           "unified":[[x[0],[float(y) for y in x[1]],float(x[2]),float(x[3]),
                       [int(c) for c in x[4]]] for x in unified],
           "detail":[[gi,int(n),float(a),[float(y) for y in d],[int(c) for c in bc],float(hr)]
                     for gi,n,a,d,bc,hit,hr in detail]},
          open(f"/tmp/unified_{S.name[-18:]}.json","w"),ensure_ascii=False)
