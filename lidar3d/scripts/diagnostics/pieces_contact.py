#!/usr/bin/env python3
"""조각별 정답 라벨용 증거 시트 — 서로 다른 시점 5프레임, 조각 위치로 확대."""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d, cv2

S=Path(sys.argv[1]); TAG=S.name.split("_")[1]; ONLY=sys.argv[3].split(",") if len(sys.argv)>3 else None
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
DW,DH=meta["depth_width"],meta["depth_height"]
sx,sy=DW/meta["video_frame_width"],DH/meta["video_frame_height"]
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
near={int(k):v for k,v in json.load(open(S/"diag_nearest_map.json")).items()}
Z=np.load(f"/tmp/pieces_{TAG}.npz"); INFO=json.load(open(f"/tmp/pieces_{TAG}.json"))["pieces"]
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
    _c[i]=(Rc,tc,K,zb,t); return _c[i]
def foot(V,i):
    Rc,tc,K,zb,ct=cam(i)
    q=V@Rc.T+tc; f=q[:,2]>0.2
    if not f.any(): return None,0,ct
    u=K[0]*q[f,0]/q[f,2]+K[2]; v=K[1]*q[f,1]/q[f,2]+K[3]; z=q[f,2]
    s=(u>=0)&(u<DW)&(v>=0)&(v<DH)
    if not s.any(): return None,0,ct
    u=u[s].astype(int); v=v[s].astype(int); z=z[s]
    vis=z<=zb[v,u]+0.02
    if vis.sum()<50: return None,0,ct
    img=np.zeros((DH,DW),np.uint8); img[v[vis],u[vis]]=1
    return img,int(vis.sum()),ct

cap=cv2.VideoCapture(str(S/"video.mov")); sheet=[]
names=[n for n in sorted(Z.files) if (ONLY is None or n in ONLY)]
for name in names:
    V=Z[name]; cen=V.mean(0); cands=[]
    for i in sorted(near):
        fp,n,ct=foot(V,i)
        if fp is None: continue
        d=cen-ct; d/=max(np.linalg.norm(d),1e-6)
        cands.append((n,i,near[i],fp,d))
    if not cands: continue
    cands.sort(key=lambda x:-x[0]); pool=cands[:60]
    pick=[pool[0]]
    while len(pick)<5 and len(pick)<len(pool):
        best=max((c for c in pool if c not in pick),
                 key=lambda c: min(np.arccos(np.clip(c[4]@p[4],-1,1)) for p in pick))
        pick.append(best)
    pick.sort(key=lambda x:x[2]); tiles=[]
    for n,i,fi,fp,_ in pick:
        cap.set(cv2.CAP_PROP_POS_FRAMES,fi); okr,img=cap.read()
        if not okr: continue
        Hh,Ww=img.shape[:2]
        m=cv2.resize(fp,(Ww,Hh),interpolation=cv2.INTER_NEAREST).astype(bool)
        m=cv2.dilate(m.astype(np.uint8),np.ones((11,11),np.uint8)).astype(bool)
        o=img.copy(); o[m]=(0.45*o[m]+0.55*np.array([0,255,0])).astype(np.uint8)
        ys,xs=np.nonzero(m)
        pad=int(0.45*max(xs.ptp(),ys.ptp(),120))
        x0=max(0,xs.min()-pad); x1=min(Ww,xs.max()+pad)
        y0=max(0,ys.min()-pad); y1=min(Hh,ys.max()+pad)
        crop=o[y0:y1,x0:x1]
        if crop.size==0: continue
        crop=cv2.resize(crop,(340,340))
        cv2.putText(crop,f"f{fi}",(8,28),0,0.9,(0,255,255),2)
        tiles.append(crop)
    while len(tiles)<5: tiles.append(np.zeros((340,340,3),np.uint8))
    row=np.hstack(tiles[:5])
    inf=INFO[name]
    lab=np.zeros((46,row.shape[1],3),np.uint8)
    cv2.putText(lab,f"{TAG} {name}  {inf['area']:.2f}m2  "
                f"{inf['size'][0]:.2f}x{inf['size'][1]:.2f}x{inf['size'][2]:.2f}  "
                f"hit{inf['hit']*100:.0f}%  conf{inf['conf_any_max']:.2f}  "
                f"hi{inf['cover_hi']}",(10,32),0,0.95,(255,255,0),2)
    sheet.append(np.vstack([lab,row]))
cv2.imwrite(sys.argv[2],np.vstack(sheet)); print("saved",sys.argv[2],len(sheet),"조각")
