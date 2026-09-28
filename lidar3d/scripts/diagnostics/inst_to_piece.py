#!/usr/bin/env python3
"""고신뢰 인스턴스마다 어느 조각이 덮는지 — 놓침/쪼개짐을 직접 센다 (open3d 전용)."""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d, cv2
S=Path(sys.argv[1]); TAG=S.name.split("_")[1]; CONF=0.5; COVER=0.30
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
DW,DH=meta["depth_width"],meta["depth_height"]
sx,sy=DW/meta["video_frame_width"],DH/meta["video_frame_height"]
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
near={int(k):v for k,v in json.load(open(S/"diag_nearest_map.json")).items()}
zi=np.load(S/"diag_inst_nearest.npz"); Z=np.load(f"/tmp/pieces_{TAG}.npz")
Vo=np.asarray(o3d.io.read_triangle_mesh(str(S/"fused_objects.ply")).vertices)
def q2R(a,b,c,d):
    return np.array([[1-2*(b*b+c*c),2*(a*b-c*d),2*(a*c+b*d)],
                     [2*(a*b+c*d),1-2*(a*a+c*c),2*(b*c-a*d)],
                     [2*(a*c-b*d),2*(b*c+a*d),1-2*(a*a+b*b)]])
_c={}
def cam(i):
    if i in _c: return _c[i]
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
    _c[i]=(Rc,tc,K,zb); return _c[i]
def foot(V,i):
    Rc,tc,K,zb=cam(i)
    q=V@Rc.T+tc; f=q[:,2]>0.2
    if not f.any(): return None,None
    u=K[0]*q[f,0]/q[f,2]+K[2]; v=K[1]*q[f,1]/q[f,2]+K[3]; z=q[f,2]
    s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
    if not s.any(): return None,None
    u=u[s].astype(int); v=v[s].astype(int); z=z[s]
    vis=z<=zb[v,u]+0.02
    if vis.sum()<30: return None,None
    raw=np.zeros((DH,DW),bool); raw[v[vis],u[vis]]=True
    d=raw.copy()
    for dy in(-1,0,1):
        for dx in(-1,0,1): d|=np.roll(np.roll(raw,dy,0),dx,1)
    return d,raw
def dedup(I):
    I=sorted(I,key=lambda x:-x[1].sum()); out=[]
    for k,m,c in I:
        if any((m&m2).sum()/max(m.sum(),1)>=0.7 for _,m2,_ in out): continue
        out.append((k,m,c))
    return out
CUR=[n for n in Z.files if "s" not in n]                 # 현행 = 연결성분 조각
UNI=[n for n in Z.files if "s" in n] + \
    [n for n in Z.files if "s" not in n and not any(x.startswith(n+"s") for x in Z.files)]
print(f"===== {TAG} =====\n현행 조각 {sorted(CUR)}\n통합 조각 {sorted(UNI)}")
res={}; miss=[]
for i in sorted(near):
    fi=near[i]
    n=int(zi[f"{fi}_n"][0]) if f"{fi}_n" in zi.files else 0
    I=dedup([(k,zi[f"{fi}_{k}"],float(zi[f"{fi}_{k}_conf"][0])) for k in range(n)
             if float(zi[f"{fi}_{k}_conf"][0])>=CONF])
    if not I: continue
    fps={nm:foot(Z[nm],i)[0] for nm in Z.files}
    for k,m,c in I:
        cov=[nm for nm in Z.files if fps[nm] is not None
             and (m&fps[nm]).sum()/max(m.sum(),1)>=COVER]
        res.setdefault((fi,k),(c,cov))
        if not [x for x in cov if x in CUR]: miss.append((fi,k,c,cov))
from collections import Counter
print(f"\n고신뢰 인스턴스 {len(res)}개 (중복 병합 후)")
cc=Counter()
for (fi,k),(c,cov) in res.items():
    cc[tuple(sorted(x for x in cov if x in CUR))]+=1
print("현행 조각 조합별 인스턴스 수:")
for combo,n in cc.most_common():
    print(f"   {str(combo) if combo else '**어느 조각도 안 덮음**':<28}{n:>5}")
cu=Counter()
for (fi,k),(c,cov) in res.items():
    cu[tuple(sorted(x for x in cov if x in UNI))]+=1
print("통합 조각 조합별 인스턴스 수:")
for combo,n in cu.most_common():
    print(f"   {str(combo) if combo else '**어느 조각도 안 덮음**':<28}{n:>5}")
if miss:
    print(f"\n현행에서 어느 조각도 안 덮는 인스턴스 {len(miss)}개:")
    for fi,k,c,cov in sorted(miss,key=lambda x:-x[2])[:15]:
        print(f"   f{fi}#{k} conf{c:.2f}  (통합에서는 {cov if cov else '없음'})")
    cap=cv2.VideoCapture(str(S/"video.mov")); tiles=[]; seen=set()
    for fi,k,c,cov in sorted(miss,key=lambda x:-x[2]):
        if fi in seen: continue
        seen.add(fi)
        cap.set(cv2.CAP_PROP_POS_FRAMES,fi); okr,img=cap.read()
        if not okr: continue
        Hh,Ww=img.shape[:2]
        r=cv2.resize(zi[f"{fi}_{k}"].astype(np.uint8),(Ww,Hh),
                     interpolation=cv2.INTER_NEAREST).astype(bool)
        o=cv2.convertScaleAbs(img,alpha=1.8,beta=30)
        o[r]=(0.55*o[r]+0.45*np.array([0,0,255])).astype(np.uint8)
        cv2.putText(o,f"f{fi}#{k} {c:.2f}",(25,55),0,1.5,(0,255,255),4)
        tiles.append(cv2.resize(o,(Ww//3,Hh//3)))
        if len(tiles)>=6: break
    if tiles:
        while len(tiles)%3: tiles.append(np.zeros_like(tiles[0]))
        cv2.imwrite(f"/tmp/miss_{TAG}.png",
                    np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,len(tiles),3)]))
        print(f"   → /tmp/miss_{TAG}.png")
json.dump({f"{fi}_{k}":[c,cov] for (fi,k),(c,cov) in res.items()},
          open(f"/tmp/inst2piece_{TAG}.json","w"))
