#!/usr/bin/env python3
"""세션 하나를 정답 라벨 채점용으로 분석한다 (open3d 전용).

조각(사람 + 확인 필요) 각각에 대해:
  - 크기/면적/투영 적중률
  - 덮는 고신뢰(>=0.5) 인스턴스 수, 최고 conf, 동시 2+ 프레임, **동시 검출 비율**
  - 덮는 저신뢰 인스턴스 수  (13차: 실제 인물은 수십~수백 개를 동반한다)
고신뢰 인스턴스마다 어느 조각이 덮는지도 세어 "놓침"을 본다.

사용: score_session.py <세션> <_new|_legacy>
저장: /tmp/score_<태그>_<모드>.json
"""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d
S=Path(sys.argv[1]); MODE=sys.argv[2]
TAG=S.name.split("_")[1]; CONF=0.5; COVER=0.30
D=S/MODE
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
W,H=meta["depth_width"],meta["depth_height"]
sx,sy=W/meta["video_frame_width"],H/meta["video_frame_height"]
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
mp=json.load(open(S/"person_masks_map.json"))
mask_map={int(k):int(v) for k,v in mp.items()}
zi=np.load(S/"person_instances.npz")
zm=np.load(S/"person_masks.npz")
Vo=np.asarray(o3d.io.read_triangle_mesh(str(S/"fused_objects.ply")).vertices)
def q2R(a,b,c,d):
    return np.array([[1-2*(b*b+c*c),2*(a*b-c*d),2*(a*c+b*d)],
                     [2*(a*b+c*d),1-2*(a*a+c*c),2*(b*c-a*d)],
                     [2*(a*c-b*d),2*(b*c+a*d),1-2*(a*a+b*b)]])
def clean(d,mx=4.0):
    d=d.copy(); d[(d<=0)|(d>mx)]=0
    pad=np.pad(d,1,mode="edge")
    nb=np.stack([pad[:-2,1:-1],pad[2:,1:-1],pad[1:-1,:-2],pad[1:-1,2:]])
    with np.errstate(divide="ignore",invalid="ignore"):
        rel=np.abs(nb-d[None])/np.maximum(d[None],1e-6)
    d[np.nanmax(np.where(nb>0,rel,0),axis=0)>0.04]=0
    return d
def dedup(I):
    I=sorted(I,key=lambda x:-x[1].sum()); out=[]
    for k,m,c in I:
        if any((m&m2).sum()/max(m.sum(),1)>=0.7 for _,m2,_ in out): continue
        out.append((k,m,c))
    return out
frames=[]
for r in rows:
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2": continue
    fi=mask_map.get(int(r["depth_index"]))
    if fi is None or f"{fi}_n" not in zi.files: continue
    nk=int(zi[f"{fi}_n"][0])
    I=[(k,zi[f"{fi}_{k}"],float(zi[f"{fi}_{k}_conf"][0])) for k in range(nk)]
    hi=dedup([x for x in I if x[2]>=CONF]); lo=dedup([x for x in I if x[2]<CONF])
    R=q2R(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")])
    Rc=np.diag([1.,-1.,-1.])@R.T; tc=-Rc@t
    K=(float(p["fx"])*sx,float(p["fy"])*sy,float(p["cx"])*sx,float(p["cy"])*sy)
    q=Vo@Rc.T+tc; f=q[:,2]>0.2
    u=K[0]*q[f,0]/q[f,2]+K[2]; v=K[1]*q[f,1]/q[f,2]+K[3]
    ok=(u>=0)&(u<W)&(v>=0)&(v<H)
    zb=np.full((H,W),np.inf,np.float32)
    if ok.any(): np.minimum.at(zb,(v[ok].astype(int),u[ok].astype(int)),q[f,2][ok])
    mm=zm[str(fi)] if str(fi) in zm.files else None
    frames.append((r["depth_file"],fi,Rc,tc,K,zb,hi,lo,mm))
def foot(V,fr):
    _,_,Rc,tc,K,zb,_,_,_=fr
    q=V@Rc.T+tc; f=q[:,2]>0.2
    if not f.any(): return None
    u=K[0]*q[f,0]/q[f,2]+K[2]; v=K[1]*q[f,1]/q[f,2]+K[3]; z=q[f,2]
    s=(u>=0)&(u<W)&(v>=0)&(v<H)
    if not s.any(): return None
    u=u[s].astype(int); v=v[s].astype(int); z=z[s]
    vis=z<=zb[v,u]+0.02
    if vis.sum()<30: return None
    img=np.zeros((H,W),bool); img[v[vis],u[vis]]=True
    d2=img.copy()
    for dy in(-1,0,1):
        for dx in(-1,0,1): d2|=np.roll(np.roll(img,dy,0),dx,1)
    return d2
files=sorted(list(D.glob("fused_person_*.ply"))+list(D.glob("review_blob_*.ply")))
files=[f for f in files if "confidence" not in f.name]
out={}; inst_cov={}
for f in files:
    m=o3d.io.read_triangle_mesh(str(f)); V=np.asarray(m.vertices)
    if len(V)<10: continue
    d=V.max(0)-V.min(0); a=m.get_surface_area()
    one=two=0; hh=tt=0; nhi=0; nlo=0; cmax=0.0; cmaxlo=0.0
    for fr in frames:
        fp=foot(V,fr)
        if fp is None: continue
        if fr[8] is not None: hh+=int((fp&fr[8]).sum()); tt+=int(fp.sum())
        k2=0
        for k,mk,c in fr[6]:
            if (mk&fp).sum()/max(mk.sum(),1)>=COVER:
                k2+=1; nhi+=1; cmax=max(cmax,c)
                inst_cov.setdefault((fr[1],k),[]).append(f.name)
        for k,mk,c in fr[7]:
            if (mk&fp).sum()/max(mk.sum(),1)>=COVER: nlo+=1; cmaxlo=max(cmaxlo,c)
        if k2>=1: one+=1
        if k2>=2: two+=1
    out[f.name]={"kind":"person" if f.name.startswith("fused") else "review",
                 "size":[float(x) for x in d],"area":float(a),"verts":len(V),
                 "hit":hh/max(tt,1),"one":one,"two":two,
                 "ratio":(two/one if one else 0.0),
                 "n_hi":nhi,"n_lo":nlo,"conf_hi_max":cmax,"conf_lo_max":cmaxlo}
# 놓침: 어느 조각도 안 덮는 고신뢰 인스턴스
allhi=[]
for fr in frames:
    for k,mk,c in fr[6]: allhi.append((fr[1],k,c))
orphan=[(fi,k,c) for fi,k,c in allhi if (fi,k) not in inst_cov]
res={"session":S.name,"mode":MODE,"frames":len(frames),
     "n_hi_inst":len(allhi),"orphan_hi":len(orphan),
     "orphan_list":[[int(a_),int(b_),float(c_)] for a_,b_,c_ in sorted(orphan,key=lambda x:-x[2])[:15]],
     "pieces":out}
json.dump(res,open(f"/tmp/score_{TAG}_{MODE}.json","w"),ensure_ascii=False,indent=1)
print(f"=== {TAG} {MODE}  프레임 {len(frames)}  고신뢰 인스턴스 {len(allhi)}  "
      f"어느 조각도 안 덮음 {len(orphan)}")
print(f"  {'조각':<22}{'종류':>7}{'면적':>7}{'가로x높이x깊이':>22}{'적중':>7}"
      f"{'덮는프레임':>9}{'동시2+':>7}{'비율':>7}{'고신뢰':>7}{'저신뢰':>7}{'maxconf':>8}")
for n,v in out.items():
    s_=v["size"]
    print(f"  {n:<22}{v['kind']:>7}{v['area']:>6.2f}㎡ {s_[0]:5.2f}x{s_[1]:5.2f}x{s_[2]:5.2f}"
          f"{v['hit']*100:>6.1f}%{v['one']:>9}{v['two']:>7}{v['ratio']*100:>6.1f}%"
          f"{v['n_hi']:>7}{v['n_lo']:>7}{v['conf_hi_max']:>8.2f}")
