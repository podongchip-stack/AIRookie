#!/usr/bin/env python3
"""조각별 정답 라벨용 증거 시트 (open3d 전용).
서로 다른 시점 5프레임, 조각 위치로 확대, 어두운 영상 보정.
사용: label_sheet.py <세션> <_new|_legacy> <출력png> [프레임수]
"""
import sys, csv, json
from pathlib import Path
import numpy as np, open3d as o3d, cv2
S=Path(sys.argv[1]); MODE=sys.argv[2]; OUT=sys.argv[3]
NF=int(sys.argv[4]) if len(sys.argv)>4 else 5
TAG=S.name.split("_")[1]; D=S/MODE
meta=json.loads((S/"metadata.json").read_text(encoding="utf-8"))
W,H=meta["depth_width"],meta["depth_height"]
sx,sy=W/meta["video_frame_width"],H/meta["video_frame_height"]
poses={r["timestamp"]:r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows=list(csv.DictReader(open(S/"depth"/"index.csv")))
mask_map={int(k):int(v) for k,v in json.load(open(S/"person_masks_map.json")).items()}
Vo=np.asarray(o3d.io.read_triangle_mesh(str(S/"fused_objects.ply")).vertices)
def q2R(a,b,c,d):
    return np.array([[1-2*(b*b+c*c),2*(a*b-c*d),2*(a*c+b*d)],
                     [2*(a*b+c*d),1-2*(a*a+c*c),2*(b*c-a*d)],
                     [2*(a*c-b*d),2*(b*c+a*d),1-2*(a*a+b*b)]])
frames=[]
for r in rows:
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2": continue
    fi=mask_map.get(int(r["depth_index"]))
    if fi is None: continue
    R=q2R(*[float(p[k]) for k in ("qx","qy","qz","qw")])
    t=np.array([float(p[k]) for k in ("tx","ty","tz")])
    Rc=np.diag([1.,-1.,-1.])@R.T; tc=-Rc@t
    K=(float(p["fx"])*sx,float(p["fy"])*sy,float(p["cx"])*sx,float(p["cy"])*sy)
    q=Vo@Rc.T+tc; f=q[:,2]>0.2
    u=K[0]*q[f,0]/q[f,2]+K[2]; v=K[1]*q[f,1]/q[f,2]+K[3]
    ok=(u>=0)&(u<W)&(v>=0)&(v<H)
    zb=np.full((H,W),np.inf,np.float32)
    if ok.any(): np.minimum.at(zb,(v[ok].astype(int),u[ok].astype(int)),q[f,2][ok])
    frames.append((fi,Rc,tc,K,zb,t))
def foot(V,fr):
    _,Rc,tc,K,zb,ct=fr
    q=V@Rc.T+tc; f=q[:,2]>0.2
    if not f.any(): return None,0,ct
    u=K[0]*q[f,0]/q[f,2]+K[2]; v=K[1]*q[f,1]/q[f,2]+K[3]; z=q[f,2]
    s=(u>=0)&(u<W)&(v>=0)&(v<H)
    if not s.any(): return None,0,ct
    u=u[s].astype(int); v=v[s].astype(int); z=z[s]
    vis=z<=zb[v,u]+0.02
    if vis.sum()<50: return None,0,ct
    img=np.zeros((H,W),np.uint8); img[v[vis],u[vis]]=1
    return img,int(vis.sum()),ct
files=[f for f in sorted(list(D.glob("fused_person_*.ply"))+list(D.glob("review_blob_*.ply")))
       if "confidence" not in f.name]
cap=cv2.VideoCapture(str(S/"video.mov")); sheet=[]
for f in files:
    m=o3d.io.read_triangle_mesh(str(f)); V=np.asarray(m.vertices)
    if len(V)<10: continue
    cen=V.mean(0); cands=[]
    for fr in frames:
        fp,n,ct=foot(V,fr)
        if fp is None: continue
        d=cen-ct; d/=max(np.linalg.norm(d),1e-6)
        cands.append((n,fr[0],fp,d))
    if not cands: continue
    cands.sort(key=lambda x:-x[0]); pool=cands[:60]; pick=[pool[0]]
    while len(pick)<NF and len(pick)<len(pool):
        pick.append(max((c for c in pool if c not in pick),
                        key=lambda c: min(np.arccos(np.clip(c[3]@p[3],-1,1)) for p in pick)))
    pick.sort(key=lambda x:x[1]); tiles=[]
    for n,fi,fp,_ in pick:
        cap.set(cv2.CAP_PROP_POS_FRAMES,fi); ok,img=cap.read()
        if not ok: continue
        Hh,Ww=img.shape[:2]
        mm=cv2.resize(fp,(Ww,Hh),interpolation=cv2.INTER_NEAREST).astype(bool)
        mm=cv2.dilate(mm.astype(np.uint8),np.ones((9,9),np.uint8)).astype(bool)
        br=float(img.mean()); al=1.0 if br>70 else (2.2 if br<35 else 1.6)
        o=cv2.convertScaleAbs(img,alpha=al,beta=(35 if al>1 else 0))
        o[mm]=(0.5*o[mm]+0.5*np.array([0,255,0])).astype(np.uint8)
        cnt,_=cv2.findContours(mm.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(o,cnt,-1,(0,255,255),3)
        ys,xs=np.nonzero(mm); pad=int(0.55*max(xs.ptp(),ys.ptp(),180))
        x0=max(0,xs.min()-pad); x1=min(Ww,xs.max()+pad)
        y0=max(0,ys.min()-pad); y1=min(Hh,ys.max()+pad)
        cr=o[y0:y1,x0:x1]
        if cr.size==0: continue
        cr=cv2.resize(cr,(320,320)); cv2.putText(cr,f"f{fi}",(8,26),0,0.85,(0,255,255),2)
        tiles.append(cr)
    while len(tiles)<NF: tiles.append(np.zeros((320,320,3),np.uint8))
    d2=V.max(0)-V.min(0)
    lab=np.zeros((42,320*NF,3),np.uint8)
    cv2.putText(lab,f"{TAG}{MODE} {f.stem}  {m.get_surface_area():.2f}m2  "
                f"{d2[0]:.2f}x{d2[1]:.2f}x{d2[2]:.2f}",(10,30),0,0.95,(255,255,0),2)
    sheet.append(np.vstack([lab,np.hstack(tiles[:NF])]))
if sheet: cv2.imwrite(OUT,np.vstack(sheet)); print("saved",OUT,len(sheet),"조각")
else: print("조각 없음")
