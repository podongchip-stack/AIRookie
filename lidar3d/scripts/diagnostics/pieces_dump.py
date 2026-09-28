#!/usr/bin/env python3
"""모든 조각(현행 + 11차 통합 규칙)을 한 곳에 모아 저장한다 (open3d 전용).

정답 라벨을 붙이려면 조각마다 같은 기준으로 증거를 봐야 한다.
여기서는 조각의 정점·크기·적중률·근거군집·덮는 인스턴스 신뢰도까지 한 번에 뽑는다.

저장: /tmp/pieces_<세션>.npz  (조각별 정점)
      /tmp/pieces_<세션>.json (조각별 수치)
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
tag=S.name.split("_")[1]

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

# ── 모든 인스턴스(계층 구분 없이) + 계층1 관측 ────────────────
allinst={}     # i -> [(k, mask, conf)]
obs1=[]
for i,r in enumerate(rows):
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2" or i not in near: continue
    fi=near[i]
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    I=[(k,zi[f"{fi}_{k}"],float(zi[f"{fi}_{k}_conf"][0])) for k in range(n)]
    allinst[i]=I
    if not any(c>=CONF for _,_,c in I): continue
    d=clean(np.fromfile(S/"depth"/r["depth_file"],dtype="<f4").reshape(DH,DW))
    R=q2R(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")]); T=R@np.diag([1.,-1.,-1.])
    fx,fy=float(p["fx"])*sx,float(p["fy"])*sy; cx,cy=float(p["cx"])*sx,float(p["cy"])*sy
    for k,m,c in I:
        if c<CONF: continue
        vv,uu=np.nonzero(m&(d>0.2)&(d<4.0))
        if len(vv)<120: continue
        zz=d[vv,uu]; med=np.median(zz); s=np.abs(zz-med)<0.6
        if s.sum()<120: continue
        vv,uu,zz=vv[s],uu[s],zz[s]
        X=(uu-cx)/fx*zz; Y=(vv-cy)/fy*zz
        obs1.append((i,fi,np.stack([X,Y,zz],1)@T.T+t,k))
C=np.array([o[2].mean(0) for o in obs1]); FR=np.array([o[1] for o in obs1])
order=np.argsort([-len(o[2]) for o in obs1]); members=[]; fo=[]
for i in order:
    best=-1;bd=1e9
    for c,mem in enumerate(members):
        if FR[i] in fo[c]: continue
        dm=min(np.linalg.norm(C[i]-C[j]) for j in mem)
        if dm<RAD and dm<bd: best,bd=c,dm
    if best<0: members.append([i]); fo.append({FR[i]})
    else: members[best].append(i); fo[best].add(FR[i])
stable=[c for c,m in enumerate(members) if len(m)>=8]
trees={c:cKDTree(np.vstack([obs1[j][2] for j in members[c]])) for c in stable}
unstable_obs=[j for c,m in enumerate(members) if c not in stable for j in m]
print(f"[{tag}] 계층1 관측 {len(obs1)} / 군집 {len(members)} / 안정 {len(stable)} "
      f"{[len(members[c]) for c in stable]} / 불안정 관측 {len(unstable_obs)}")

# ── 조각 만들기 ───────────────────────────────────────────────
mob=o3d.io.read_triangle_mesh(str(S/"fused_objects.ply"))
with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
    ci,_,ca=mob.cluster_connected_triangles()
ci=np.asarray(ci); ca=np.asarray(ca)
Vo=np.asarray(mob.vertices); To=np.asarray(mob.triangles)
cand=[k for k in range(len(ca)) if ca[k]>0.05]
cents={k:Vo[To[np.where(ci==k)[0]]].reshape(-1,3).mean(0) for k in cand}
groups=[];used=set()
for k in sorted(cand,key=lambda x:-ca[x]):
    if k in used: continue
    g=[k];used.add(k)
    for j in cand:
        if j in used: continue
        if np.linalg.norm(cents[j]-cents[k])<0.8: g.append(j);used.add(j)
    groups.append(g)
def submesh(ti):
    s=o3d.geometry.TriangleMesh(mob); s.triangles=o3d.utility.Vector3iVector(To[ti])
    s.remove_unreferenced_vertices(); return s

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
    _cache[i]=(Rc,tc,K,zb,t); return _cache[i]
def foot(V,i):
    Rc,tc,K,zb,_=cam(i)
    q=V@Rc.T+tc; f=q[:,2]>0.2
    if not f.any(): return None,0
    u=K[0]*q[f,0]/q[f,2]+K[2]; v=K[1]*q[f,1]/q[f,2]+K[3]; z=q[f,2]
    s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
    if not s.any(): return None,0
    u=u[s].astype(int); v=v[s].astype(int); z=z[s]
    vis=z<=zb[v,u]+0.02
    if vis.sum()<30: return None,0
    img=np.zeros((DH,DW),bool); img[v[vis],u[vis]]=True
    d=img.copy()
    for dy in(-1,0,1):
        for dx in(-1,0,1): d|=np.roll(np.roll(img,dy,0),dx,1)
    return d,int(vis.sum())

def dedup(I):
    """같은 프레임 안의 중복 검출 병합 — 포함비율 0.7 이상이면 큰 쪽만 남긴다."""
    I=sorted(I,key=lambda x:-x[1].sum()); out=[]
    for k,m,c in I:
        if any((m&m2).sum()/max(m.sum(),1)>=0.7 for _,m2,_ in out): continue
        out.append((k,m,c))
    return out

def analyze(V):
    """조각 하나에 대해: 적중률 / 덮는 인스턴스 / 프레임별 동시 인스턴스 수."""
    h=t_=0; covered=[]; per_frame=[]
    for i in sorted(near):
        fi=near[i]
        fp,nvis=foot(V,i)
        if fp is None: continue
        if str(fi) in zm.files:
            mm=zm[str(fi)]
            # 적중률은 보이는 화소 기준 — foot()의 팽창 전 값을 쓰려고 다시 센다
            h+=int((fp&mm).sum()); t_+=int(fp.sum())
        hi=dedup([x for x in allinst.get(i,[]) if x[2]>=CONF])
        cnt=0
        for k,m,c in hi:
            if (m&fp).sum()/max(m.sum(),1)>=COVER:
                covered.append((fi,k,c)); cnt+=1
        lo=[x for x in allinst.get(i,[]) if x[2]<CONF]
        locnt=sum(1 for k,m,c in lo if (m&fp).sum()/max(m.sum(),1)>=COVER)
        per_frame.append((fi,cnt,locnt))
    return h/max(t_,1), covered, per_frame

pieces={}; info={}
def add(name, ti):
    s=submesh(ti); V=np.asarray(s.vertices)
    if len(V)<50: return
    d=V.max(0)-V.min(0); a=s.get_surface_area()
    hr,cov,pf=analyze(V)
    hit={}
    for fi,k,c in cov: hit.setdefault(fi,[]).append(c)
    confs=[c for _,_,c in cov]
    # 저신뢰까지 포함해 이 조각을 덮는 최고 신뢰도
    allc=[]
    for i in sorted(near):
        fp,_=foot(V,i)
        if fp is None: continue
        for k,m,c in allinst.get(i,[]):
            if (m&fp).sum()/max(m.sum(),1)>=COVER: allc.append(c)
    bc=[]
    for c in stable:
        n=sum(1 for j in members[c]
              if obs1[j][1] in hit and any(abs(x-1)<9 for x in [1]))
    # 근거군집: 군집 관측 중 이 조각이 마스크를 30% 이상 덮은 횟수
    for c in stable:
        n=0
        for j in members[c]:
            i,fi,_,k=obs1[j]
            fp,_=foot(V,i)
            if fp is None: continue
            m=zi[f"{fi}_{k}"]
            if (m&fp).sum()/max(m.sum(),1)>=COVER: n+=1
        if n>=NEED: bc.append((int(c),n))
    pieces[name]=V
    info[name]={"n":int(len(V)),"area":float(a),"size":[float(x) for x in d],
                "size_ok":bool(ok(d)),"hit":float(hr),
                "cover_hi":len(cov),"cover_frames":len(hit),
                "conf_hi_max":float(max(confs)) if confs else 0.0,
                "conf_any_max":float(max(allc)) if allc else 0.0,
                "backing":bc,
                "multi_frames":int(sum(1 for _,c,_ in pf if c>=2)),
                "single_frames":int(sum(1 for _,c,_ in pf if c==1)),
                "zero_frames":int(sum(1 for _,c,_ in pf if c==0)),
                "per_frame":[[int(a_),int(b_),int(c_)] for a_,b_,c_ in pf]}

for gi,g in enumerate(groups):
    ti=np.concatenate([np.where(ci==k)[0] for k in g])
    s=submesh(ti)
    if len(np.asarray(s.vertices))<50 or s.get_surface_area()<AMIN: continue
    add(f"g{gi}", ti)
    info[f"g{gi}"]["tri"]=len(ti)

# 통합 규칙 분할 (근거군집 2개 이상인 조각만)
for gi,g in enumerate(groups):
    nm=f"g{gi}"
    if nm not in info: continue
    bc=[c for c,_ in info[nm]["backing"]]
    if len(bc)<2: continue
    ti=np.concatenate([np.where(ci==k)[0] for k in g])
    tcen=Vo[To[ti]].mean(1)
    dist=np.stack([trees[c].query(tcen,k=1)[0] for c in bc],1)
    asg=dist.argmin(1)
    for a_,c in enumerate(bc):
        sel=ti[asg==a_]
        if len(sel)<50: continue
        s2=submesh(sel)
        if len(np.asarray(s2.vertices))<50 or s2.get_surface_area()<AMIN: continue
        add(f"{nm}s{c}", sel)

np.savez_compressed(f"/tmp/pieces_{tag}.npz", **pieces)
json.dump({"session":S.name,"stable":[int(c) for c in stable],
           "stable_obs":{str(int(c)):len(members[c]) for c in stable},
           "unstable_obs":[[int(obs1[j][1]),int(obs1[j][3])] for j in unstable_obs],
           "pieces":info}, open(f"/tmp/pieces_{tag}.json","w"), ensure_ascii=False, indent=1)
print(f"  조각 {len(pieces)}개 저장: {sorted(pieces)}")
for k in sorted(info):
    v=info[k]
    print(f"   {k:<8}{v['n']:>7}정점 {v['area']:>6.2f}㎡ "
          f"{v['size'][0]:5.2f}x{v['size'][1]:5.2f}x{v['size'][2]:5.2f} "
          f"크기{'O' if v['size_ok'] else 'X'} 적중{v['hit']*100:5.1f}% "
          f"고신뢰덮음{v['cover_hi']:>4} 최고conf{v['conf_any_max']:.2f} "
          f"근거{v['backing']} 동시2+{v['multi_frames']:>3}")
