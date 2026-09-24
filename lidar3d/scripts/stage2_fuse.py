"""
2단계 — 적응형 해상도 융합 (open3d 전용 프로세스)

배경은 거친 복셀, 관심 객체(부상자)는 정밀 복셀로 따로 융합한 뒤 합친다.
1단계가 만든 person_masks.npz를 읽는다. torch를 import하지 않는다 (1단계 주석 참고).

실측 (뎁스 249프레임, iPhone 12 Pro):
  전체 4cm      111,529정점  1.2초   사람 뭉개짐
  전체 1cm    2,785,645정점 10.0초   사람 선명
  적응형        146,924정점  1.2초   사람 선명   <- 정점 19배↓, 시간 8.3배↓

⚠️ 동적 객체 한계: TSDF는 여러 프레임을 누적하므로 움직이는 대상은 겹쳐 흐려진다.
   객체 영역은 <창(초)> 안의 프레임만 융합한다. 짧을수록 선명하고 구멍이 는다.

사용법:
  python3 scripts/stage2_fuse.py <세션경로> <배경복셀m> <객체복셀m> [창초]
  예) python3 scripts/stage2_fuse.py server/sessions/session_XXX 0.04 0.01 3.0

생성: <세션>/fused_adaptive.ply (배경 회색 + 객체 빨강), <세션>/fused_objects.ply
"""
import sys, time, csv, json, numpy as np, open3d as o3d, cv2
S,BGV,OBV = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
# 시간창(초). 0이면 제한 없음.
# ⚠️ 전역 창의 함정: "첫 사람이 보인 시각부터 N초"라서, 사람들이 촬영 내내 등장하면
#    대부분의 프레임이 잘린다 (실측: 마스크 73프레임 중 8프레임만 사용됨).
#    움직임에 의한 겹침(ghosting)은 아래 사람별 분리 단계의 크기 필터가 상당 부분 걸러내므로
#    기본을 '제한 없음'으로 둔다. 대상이 많이 움직이면 값을 주어 제한한다.
WIN = float(sys.argv[4]) if len(sys.argv)>4 else 0.0
t0=time.time()
def mark(s): print(f"[{time.time()-t0:5.1f}s] {s}", flush=True)
def _progress(name, done_, total_, extra=""):
    """진행 상황 파일 — 뷰어가 읽는다. 실패해도 본 작업은 계속한다."""
    try:
        import os as _po, tempfile
        d = {"stage": 2, "name": name, "done": int(done_), "total": int(total_),
             "pct": round(done_/max(total_,1)*100, 1), "extra": extra, "t": time.time()}
        fd, tmp = tempfile.mkstemp(dir=S, suffix=".tmp")
        with _po.fdopen(fd, "w") as fh: json.dump(d, fh, ensure_ascii=False)
        _po.replace(tmp, f"{S}/_progress.json")
    except Exception: pass
m=json.load(open(f"{S}/metadata.json",encoding="utf-8"))
W,H=m["depth_width"],m["depth_height"]; vw,vh=m["video_frame_width"],m["video_frame_height"]
sx,sy=W/vw,H/vh
poses={r["timestamp"]:r for r in csv.DictReader(open(f"{S}/arkit_pose.csv"))}
rows=list(csv.DictReader(open(f"{S}/depth/index.csv")))
z=np.load(f"{S}/person_masks.npz"); masks={int(k):z[k] for k in z.files}
# 1단계가 남긴 "뎁스 행 -> 영상 프레임" 매핑.
# 없으면 예전 방식(video_frame_index)으로 폴백한다.
# ⚠️ 이 매핑을 쓰지 않으면 절반의 뎁스 프레임이 직전 마스크를 재사용하게 되어
#    1단계의 최근접 매칭 개선이 통째로 무효가 된다.
import os as _os2, json as _json2
_mp=f"{S}/person_masks_map.json"
mask_map={int(k):int(v) for k,v in _json2.load(open(_mp)).items()} if _os2.path.exists(_mp) else None
mark(f"로드: 뎁스 {len(rows)}, 마스크 {len(masks)}")
def R_(x,y,z_,w):
    return np.array([[1-2*(y*y+z_*z_),2*(x*y-z_*w),2*(x*z_+y*w)],[2*(x*y+z_*w),1-2*(x*x+z_*z_),2*(y*z_-x*w)],
                     [2*(x*z_-y*w),2*(y*z_+x*w),1-2*(x*x+y*y)]])
def clean(d,maxd=4.0):
    d=d.copy(); d[(d<=0)|(d>maxd)]=0
    if not (d>0).any(): return d
    pad=np.pad(d,1,mode="edge")
    nb=np.stack([pad[:-2,1:-1],pad[2:,1:-1],pad[1:-1,:-2],pad[1:-1,2:]])
    with np.errstate(divide="ignore",invalid="ignore"):
        rel=np.abs(nb-d[None])/np.maximum(d[None],1e-6)
    d[np.nanmax(np.where(nb>0,rel,0),axis=0)>0.04]=0
    return d
mk=lambda v: o3d.pipelines.integration.ScalableTSDFVolume(voxel_length=v,sdf_trunc=v*3,
    color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor)
def mask_for(r):
    """이 뎁스 행에 쓸 마스크. 최근접 매핑이 있으면 그것을, 없으면 예전 방식."""
    if mask_map is not None:
        k=mask_map.get(int(r["depth_index"]))
        return masks.get(k) if k is not None else None
    k=int(r["video_frame_index"])
    return masks.get(k)

obj_ts=[float(r["timestamp"]) for r in rows
        if (mask_for(r) is not None and mask_for(r).any())]
t_start=min(obj_ts) if obj_ts else None
bg,ob=mk(BGV),mk(OBV); nb=no=0; last=np.zeros((H,W),bool)
tf=time.time(); _nrow=0
_progress("융합(TSDF)", 0, len(rows))
for r in rows:
    _nrow+=1
    if _nrow%25==0: _progress("융합(TSDF)", _nrow, len(rows))
    p=poses.get(r["timestamp"])
    if p is None or p["tracking_state"]!="2": continue
    d=clean(np.fromfile(f"{S}/depth/{r['depth_file']}",dtype="<f4").reshape(H,W))
    if (d>0).sum()<200: continue
    K=[float(p["fx"])*sx,float(p["fy"])*sy,float(p["cx"])*sx,float(p["cy"])*sy]
    R=R_(*[float(p[k]) for k in ("qx","qy","qz","qw")]); t=np.array([float(p[k]) for k in ("tx","ty","tz")])
    T=np.eye(4); T[:3,:3]=R@np.diag([1.,-1.,-1.]); T[:3,3]=t
    intr=o3d.camera.PinholeCameraIntrinsic(W,H,*K); Ti=np.linalg.inv(T)
    _m=mask_for(r)
    if _m is not None: last=_m
    def integ(vol,dd):
        rgbd=o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.zeros((H,W,3),dtype=np.uint8)),o3d.geometry.Image(np.ascontiguousarray(dd)),
            depth_scale=1.0,depth_trunc=4.0,convert_rgb_to_intensity=False)
        vol.integrate(rgbd,intr,Ti)
    db=d.copy(); db[last]=0
    if (db>0).sum()>=200: integ(bg,db); nb+=1
    if last.any() and (WIN<=0 or (t_start is not None and float(r["timestamp"])-t_start<=WIN)):
        do=d.copy(); do[~last]=0
        # 깊이 게이트 — **사람 덩어리마다 따로** 적용한다.
        #
        #   세그멘테이션이 윤곽을 정확히 따도, 팔·다리 사이 틈으로 뒤쪽 벽이 보인다.
        #   그걸 걸러내려면 "이 사람의 깊이" 기준이 필요하다.
        #
        #   ⚠️ 마스크 전체에 한 번만 적용하면 안 된다 (실측으로 확인한 실패):
        #      화면에 사람이 여럿이면 중앙값이 **사람들 사이 허공**에 잡혀
        #      양쪽 사람이 모두 잘려 나가고 줄무늬 형태의 조각만 남는다.
        #   그래서 마스크를 연결 덩어리로 나눈 뒤 각 덩어리의 중앙값을 쓴다.
        nlab, lab = cv2.connectedComponents(last.astype(np.uint8))
        for li in range(1, nlab):
            blob = (lab == li) & (do > 0)
            if blob.sum() < 50:
                do[lab == li] = 0
                continue
            med = float(np.median(do[blob]))
            bad = (lab == li) & ((do < med - 0.6) | (do > med + 0.6))
            do[bad] = 0
        if (do>0).sum()>=100: integ(ob,do); no+=1
t_fuse=time.time()-tf
mbg=bg.extract_triangle_mesh(); mbg.compute_vertex_normals(); mbg.paint_uniform_color([.55,.57,.60])
mob=ob.extract_triangle_mesh(); mob.compute_vertex_normals(); mob.paint_uniform_color([.90,.16,.16])
o3d.io.write_triangle_mesh(f"{S}/fused_adaptive.ply", mbg+mob)
o3d.io.write_triangle_mesh(f"{S}/fused_objects.ply", mob)

# ── 사람별로 분리 저장 ───────────────────────────────────────────────
# 왜 필요한가: 객체 볼륨에는 방 안의 **여러 사람이 한 덩어리로** 들어 있다.
#   실측에서 전체 크기가 4.4 x 1.4 x 2.5 m로 나왔는데, 이는 사람 5명이 흩어져 있어서였다.
#   모달에 한 명씩 띄우려면 개인별로 잘라야 한다.
#
# 방법: 연결 성분(끊긴 덩어리)을 구하고, 가까운 것끼리 묶은 뒤, 사람 크기인 것만 남긴다.
#   프레임 간 추적(tracking)을 하지 않아도 되므로 훨씬 단순하고 실패가 적다.
import json as _json, glob as _glob, os as _os
for old in _glob.glob(f"{S}/fused_person_*.ply"): _os.remove(old)
for old in _glob.glob(f"{S}/review_blob_*.ply"): _os.remove(old)
for old in _glob.glob(f"{S}/fused_person_*_confidence.bin"): _os.remove(old)
person_verts=[]

persons=[]
if len(mob.triangles)>0:
    with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
        ci,ntri,carea=mob.cluster_connected_triangles()
    ci=np.asarray(ci); carea=np.asarray(carea)
    Vo=np.asarray(mob.vertices); To=np.asarray(mob.triangles)
    # 의미 있는 조각만 (5cm² 미만은 노이즈)
    cand=[k for k in range(len(carea)) if carea[k]>0.05]
    cents={k: Vo[To[np.where(ci==k)[0]]].reshape(-1,3).mean(0) for k in cand}
    # 0.8m 안쪽 조각은 같은 사람으로 본다 (팔·다리가 끊겨 나오는 경우를 묶는다)
    groups=[]; used=set()
    for k in sorted(cand, key=lambda x:-carea[x]):
        if k in used: continue
        g=[k]; used.add(k)
        for j in cand:
            if j in used: continue
            if np.linalg.norm(cents[j]-cents[k])<0.8: g.append(j); used.add(j)
        groups.append(g)

    rv=0; rejected=[]; review=[]
    person_verts=[]
    # ── 사람 판정 규칙 (12차 채점 결과 반영) ───────────────────────────
    #
    # 되돌리기: 환경변수 LIDAR_PERSON_RULE=legacy 를 주면 아래를 전부 건너뛰고
    #           예전(크기 필터만) 동작으로 돌아간다. 파일을 되돌릴 필요가 없다.
    #
    # 규칙 (a) 분리 판단 = 프레임 내 동시 인스턴스 **비율**
    #     조각을 덮는 고신뢰 인스턴스가 1개 이상인 프레임 중,
    #     2개 이상인 프레임의 비율.
    #       >= 0.10  -> 여러 명이 뭉친 것으로 보고 층 분리 배정
    #       그 외 1개+ -> 사람으로 인정 (크기 필터 면제)
    #       0개        -> 기존 크기 필터
    #     실측 근거(세션 3개): 단독 인물 조각 0.0~6.9% vs 3명 뭉친 조각 22.4%.
    #     빈 구간 6.9~22.4% 의 아래쪽에서 골랐다 — 사람을 인정하는 쪽이
    #     쪼개지 않는 쪽보다 우선이기 때문이다.
    #     ⚠️ 빈 구간을 만드는 데이터 점이 둘뿐이다. 잠정값이다.
    #
    # 규칙 (b) 뒷받침(고신뢰 인스턴스) 없는 조각 중 투영 적중률 20% 미만
    #          -> "확인 필요". **삭제가 아니다.**
    #     실측: 정답 인물 조각의 최저 적중률이 28.9%(배경에 누운 사람)였다.
    #     20%는 그 아래로 8.9%p 여유를 둔 값이다.
    _progress("사람 판정", 0, 1)
    RULE = _os.environ.get("LIDAR_PERSON_RULE", "new").lower() != "legacy"
    RATIO_K = 0.10; HIT_MIN = 0.20; RAD = 0.374; CONF_HI = 0.5; COVER = 0.30
    decide = {}
    _inst_path = f"{S}/person_instances.npz"
    if RULE and _os.path.exists(_inst_path):
        zi = np.load(_inst_path)
        Vo_ = np.asarray(mob.vertices); To_ = np.asarray(mob.triangles)

        def _cam(p):
            R = R_(*[float(p[k]) for k in ("qx","qy","qz","qw")])
            t = np.array([float(p[k]) for k in ("tx","ty","tz")])
            Rc = np.diag([1.,-1.,-1.]) @ R.T
            return Rc, -Rc @ t, (float(p["fx"])*sx, float(p["fy"])*sy,
                                 float(p["cx"])*sx, float(p["cy"])*sy), R@np.diag([1.,-1.,-1.]), t

        # 프레임마다 카메라·z버퍼·인스턴스를 한 번만 준비한다
        frames = []
        for r in rows:
            p = poses.get(r["timestamp"])
            if p is None or p["tracking_state"] != "2": continue
            fi = mask_map.get(int(r["depth_index"])) if mask_map is not None else None
            if fi is None or f"{fi}_n" not in zi.files: continue
            nk = int(zi[f"{fi}_n"][0])
            I = [(zi[f"{fi}_{k}"], float(zi[f"{fi}_{k}_conf"][0])) for k in range(nk)]
            hi = [(m, c) for m, c in I if c >= CONF_HI]
            if not hi and mask_for(r) is None: continue
            Rc, tc, K, T, tv = _cam(p)
            q = Vo_ @ Rc.T + tc; f = q[:,2] > 0.2
            u = K[0]*q[f,0]/q[f,2] + K[2]; v = K[1]*q[f,1]/q[f,2] + K[3]
            ok2 = (u>=0)&(u<W)&(v>=0)&(v<H)
            zb = np.full((H,W), np.inf, np.float32)
            if ok2.any(): np.minimum.at(zb, (v[ok2].astype(int), u[ok2].astype(int)), q[f,2][ok2])
            frames.append((r, Rc, tc, K, T, tv, zb, hi, mask_for(r)))

        def _foot(V, fr):
            _, Rc, tc, K, _, _, zb, _, _ = fr
            q = V @ Rc.T + tc; f = q[:,2] > 0.2
            if not f.any(): return None
            u = K[0]*q[f,0]/q[f,2] + K[2]; v = K[1]*q[f,1]/q[f,2] + K[3]; z = q[f,2]
            s2 = (u>=0)&(u<W)&(v>=0)&(v<H)
            if not s2.any(): return None
            u = u[s2].astype(int); v = v[s2].astype(int); z = z[s2]
            vis = z <= zb[v,u] + 0.02
            if vis.sum() < 30: return None
            img = np.zeros((H,W), bool); img[v[vis], u[vis]] = True
            d2 = img.copy()
            for dy in (-1,0,1):
                for dx in (-1,0,1): d2 |= np.roll(np.roll(img,dy,0),dx,1)
            return d2

        def _dedup(I):
            """같은 프레임의 중복 검출 병합 — 포함비율 0.7 이상이면 큰 쪽만."""
            I = sorted(I, key=lambda x: -x[0].sum()); out = []
            for m, c in I:
                if any((m & m2).sum()/max(m.sum(),1) >= 0.7 for m2, _ in out): continue
                out.append((m, c))
            return out
        for fr in frames: fr[7][:] = _dedup(fr[7])

        # 계층1(고신뢰) 관측을 3D로 올려 뼈대 군집을 만든다 — 분리 배정에 쓴다
        obs = []
        for fr in frames:
            r, Rc, tc, K, T, tv, zb, hi, _ = fr
            if not hi: continue
            dd = clean(np.fromfile(f"{S}/depth/{r['depth_file']}", dtype="<f4").reshape(H,W))
            for m, c in hi:
                vv, uu = np.nonzero(m & (dd>0.2) & (dd<4.0))
                if len(vv) < 120: continue
                zz = dd[vv,uu]; med = np.median(zz); sl = np.abs(zz-med) < 0.6
                if sl.sum() < 120: continue
                vv, uu, zz = vv[sl], uu[sl], zz[sl]
                X = (uu-K[2])/K[0]*zz; Y = (vv-K[3])/K[1]*zz
                obs.append((id(fr), np.stack([X,Y,zz],1) @ T.T + tv))
        members = []; fset = []
        if obs:
            C0 = np.array([o[1].mean(0) for o in obs]); FRid = [o[0] for o in obs]
            for i2 in np.argsort([-len(o[1]) for o in obs]):
                best = -1; bd = 1e9
                for ci2, mem in enumerate(members):
                    if FRid[i2] in fset[ci2]: continue
                    dm = min(np.linalg.norm(C0[i2]-C0[j]) for j in mem)
                    if dm < RAD and dm < bd: best, bd = ci2, dm
                if best < 0: members.append([i2]); fset.append({FRid[i2]})
                else: members[best].append(i2); fset[best].add(FRid[i2])
        stable = [c for c, m in enumerate(members) if len(m) >= 8]
        # 군집 점은 관측당 수천 점이라 그대로 두면 최근접 계산이 무겁다.
        # 군집마다 최대 2만 점으로 균등 추출한다 (배정 결과는 실측상 바뀌지 않았다).
        cpts = {}
        for c in stable:
            q_ = np.vstack([obs[j][1] for j in members[c]])
            if len(q_) > 20000: q_ = q_[::max(1, len(q_)//20000)]
            cpts[c] = q_
        from scipy.spatial import cKDTree as _KD
        _ktrees = {c: _KD(cpts[c]) for c in stable}
        mark(f"판정 규칙: 프레임 {len(frames)}, 계층1 관측 {len(obs)}, 안정 군집 {len(stable)}")

        for gi, g in enumerate(groups):
            ti = np.concatenate([np.where(ci==k)[0] for k in g])
            sb = o3d.geometry.TriangleMesh(mob)
            sb.triangles = o3d.utility.Vector3iVector(To_[ti]); sb.remove_unreferenced_vertices()
            V = np.asarray(sb.vertices)
            if len(V) < 50: continue
            one = two = 0; hh = tt = 0; hit_c = {}
            for fr in frames:
                fp = _foot(V, fr)
                if fp is None: continue
                mm = fr[8]
                if mm is not None: hh += int((fp & mm).sum()); tt += int(fp.sum())
                k2 = 0
                for m, c in fr[7]:
                    if (m & fp).sum()/max(m.sum(),1) >= COVER: k2 += 1
                if k2 >= 1: one += 1
                if k2 >= 2: two += 1
            hit = hh/max(tt,1)
            ratio = two/one if one else 0.0
            if one and ratio >= RATIO_K and len(stable) >= 2:
                # 이 조각 근처에 실제로 관측이 모인 군집에만 배정한다.
                # (반경 제한은 두지 않는다 — 이미 사람들로만 이뤄진 덩어리이므로
                #  반경 밖을 버리면 몸 일부를 잃는다. 11차 B-3에서 확인한 실패다.)
                bb0 = V.min(0) - 0.25; bb1 = V.max(0) + 0.25
                near_c = [c for c in stable
                          if ((cpts[c] >= bb0) & (cpts[c] <= bb1)).all(1).sum() >= 8]
                if len(near_c) >= 2:
                    decide[gi] = ("split", near_c, one, two, hit)
                else:
                    decide[gi] = ("person", [], one, two, hit)
            elif one:
                decide[gi] = ("person", [], one, two, hit)
            elif hit < HIT_MIN:
                decide[gi] = ("review", [], one, two, hit)
            else:
                decide[gi] = ("legacy", [], one, two, hit)
            mark(f"  조각 g{gi}: 덮는프레임 {one}, 동시2+ {two} ({ratio*100:.1f}%), "
                 f"적중 {hit*100:.1f}% -> {decide[gi][0]}")

    def _emit_person(sub, pts, note=""):
        """사람 조각 하나를 파일과 목록에 남긴다."""
        nonlocal_n[0] += 1; k = nonlocal_n[0]
        d2 = pts.max(0)-pts.min(0); c2 = pts.mean(0); a2 = sub.get_surface_area()
        sub.paint_uniform_color([.90,.16,.16])
        o3d.io.write_triangle_mesh(f"{S}/fused_person_{k:02d}.ply", sub)
        person_verts.append((f"fused_person_{k:02d}", np.asarray(sub.vertices).copy()))
        e = {"file":f"fused_person_{k:02d}.ply","index":k,
             "surface_m2":round(float(a2),3),
             "size_m":[round(float(x),3) for x in d2],
             "center_xyz":[round(float(x),3) for x in c2],
             "vertices":len(pts)}
        if note: e["note"] = note
        persons.append(e)
    nonlocal_n=[0]

    for gi_, g in enumerate(groups):
        tri_idx=np.concatenate([np.where(ci==k)[0] for k in g])
        sub=o3d.geometry.TriangleMesh(mob)
        sub.triangles=o3d.utility.Vector3iVector(To[tri_idx])
        sub.remove_unreferenced_vertices(); sub.compute_vertex_normals()
        pts=np.asarray(sub.vertices)
        if len(pts)<50: continue
        d=pts.max(0)-pts.min(0); c=pts.mean(0); a=sub.get_surface_area()
        dec=decide.get(gi_)
        if dec is not None and a>=0.15:
            kind, cl, one_, two_, hit_ = dec
            if kind=="split":
                tc_=Vo[To[tri_idx]].mean(1)
                # ⚠️ 거리 행렬을 통째로 만들면 안 된다 (삼각형 23만 x 군집점 10만 = 메모리 폭발).
                #    KD-트리로 최근접만 구한다.
                dist=np.stack([_ktrees[c2_].query(tc_,k=1)[0] for c2_ in cl],1)
                asg=dist.argmin(1); made=0
                for a2_ in range(len(cl)):
                    sel=tri_idx[asg==a2_]
                    if len(sel)<50: continue
                    s2=o3d.geometry.TriangleMesh(mob)
                    s2.triangles=o3d.utility.Vector3iVector(To[sel])
                    s2.remove_unreferenced_vertices(); s2.compute_vertex_normals()
                    p2=np.asarray(s2.vertices)
                    if len(p2)<50 or s2.get_surface_area()<0.15: continue
                    _emit_person(s2,p2,f"동시 검출 {two_}/{one_}프레임 — 뭉친 덩어리를 분리")
                    made+=1
                if made: continue
                # 분리에 실패하면 통째로 사람으로 남긴다 (버리지 않는다)
                _emit_person(sub,pts,"분리 실패 — 통째로 유지"); continue
            if kind=="person":
                _emit_person(sub,pts,f"고신뢰 검출 {one_}프레임 — 크기 필터 면제"); continue
            if kind=="review":
                rv+=1
                sub.paint_uniform_color([.95,.75,.20])
                o3d.io.write_triangle_mesh(f"{S}/review_blob_{rv:02d}.ply", sub)
                review.append({"file":f"review_blob_{rv:02d}.ply","index":rv,
                               "surface_m2":round(float(a),3),
                               "size_m":[round(float(x),3) for x in d],
                               "center_xyz":[round(float(x),3) for x in c],
                               "vertices":len(pts),
                               "reason":f"사람 검출 뒷받침 없음, 투영 적중률 {hit_*100:.0f}%"})
                continue
        # 사람 크기 필터.
        # ⚠️ 이전에 가로 상한을 1.3m로 잡았더니 **가장 온전한 사람(3.17㎡, 가로 1.55m)이
        #    통째로 제외**됐다 (실측). 앉은 사람은 의자·책상과 붙어 잡혀 1.5m를 넘는다.
        #    상한을 넓히고, 대신 제외한 큰 조각은 아래에서 보고해 조용히 잃지 않게 한다.
        if not (0.30<d[1]<2.2 and 0.15<d[0]<2.0 and 0.15<d[2]<2.0):
            # ⚠️ 버리지 않고 **확인 필요**로 남긴다.
            #   실측(session_20260920v3): 범위 밖으로 탈락한 큰 조각 2개가 **둘 다 사람**이었다.
            #     7.37㎡ 2.15x0.68x2.36m — 누운 사람 (깔개와 붙어 가로·깊이가 부풂)
            #     3.88㎡ 2.59x1.45x1.89m — 웅크린 사람 (낡은 마스크로 주변이 붙음)
            #   인정된 4명 합계가 2.16㎡였으니, 버려진 쪽이 5배 크다.
            #   응급 현장에서 사람을 놓치는 비용이 훨씬 크므로, 판정은 그대로 두되
            #   파일과 목록으로 남겨 사람이 확인할 수 있게 한다.
            if a>=0.15:
                rv+=1
                sub.paint_uniform_color([.95,.75,.20])      # 주황 — 확인 필요
                o3d.io.write_triangle_mesh(f"{S}/review_blob_{rv:02d}.ply", sub)
                bad=[]
                if not (0.15<d[0]<2.0): bad.append(f"가로{d[0]:.2f}")
                if not (0.30<d[1]<2.2): bad.append(f"높이{d[1]:.2f}")
                if not (0.15<d[2]<2.0): bad.append(f"깊이{d[2]:.2f}")
                review.append({"file":f"review_blob_{rv:02d}.ply","index":rv,
                               "surface_m2":round(float(a),3),
                               "size_m":[round(float(x),3) for x in d],
                               "center_xyz":[round(float(x),3) for x in c],
                               "vertices":len(pts),
                               "reason":"크기 범위 밖 (" + ",".join(bad) + ")"})
            if a>0.3: rejected.append({"surface_m2":round(float(a),2),
                                       "size_m":[round(float(x),2) for x in d],
                                       "reason":"크기 범위 밖"})
            continue
        if a<0.15: continue
        _emit_person(sub,pts)
# ── 마스크 일관성 신뢰도 사이드카 ───────────────────────────────────
# 정점마다 (마스크 안에 든 프레임 수) / (실제로 보이는 프레임 수) 를 기록한다.
#
# ⚠️ 이 값으로 정점을 **삭제하지 않는다**. 9차 측정에서 임계 0.55로 자르면
#    삭제분의 47%가 유지 정점 5cm 이내였고 투영 덮음이 50.1% -> 44.3%로 떨어졌다.
#    즉 배경이 아니라 팔·가장자리를 함께 깎았다. 그래서 표시용 정보로만 남긴다.
#
# 파일이 없거나 헤더가 맞지 않으면 뷰어는 조용히 기존 표시로 돌아간다.
def _fnv1a64(b: bytes) -> int:
    h = 0xcbf29ce484222325
    for x in b:
        h = ((h ^ x) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h

def _vhash(V: np.ndarray) -> int:
    """앞뒤 1000정점의 float32 비트로 만든 해시.
    전체를 해싱하지 않는 이유는 브라우저에서 같은 계산을 해야 하기 때문이다."""
    f = np.ascontiguousarray(V, dtype="<f4")
    k = min(1000, len(f))
    return _fnv1a64(f[:k].tobytes() + f[-k:].tobytes())

if person_verts:
    _progress("신뢰도 사이드카", 0, 1)
    tc0 = time.time()
    Vall = np.vstack([v for _, v in person_verts])
    off = np.cumsum([0] + [len(v) for _, v in person_verts])
    Vocc = np.asarray(mob.vertices)          # 가림 판정용 (객체 볼륨 전체)
    seen = np.zeros(len(Vall), np.int32)
    inm = np.zeros(len(Vall), np.int32)
    nseen = 0
    for r in rows:
        p = poses.get(r["timestamp"])
        if p is None or p["tracking_state"] != "2": continue
        msk = mask_for(r)
        if msk is None: continue
        R = R_(*[float(p[k]) for k in ("qx","qy","qz","qw")])
        t = np.array([float(p[k]) for k in ("tx","ty","tz")])
        Rc = np.diag([1.,-1.,-1.]) @ R.T; tc = -Rc @ t
        fx, fy = float(p["fx"])*sx, float(p["fy"])*sy
        cx, cy = float(p["cx"])*sx, float(p["cy"])*sy
        def _proj(X):
            q = X @ Rc.T + tc; f = q[:,2] > 0.2
            u = fx*q[f,0]/q[f,2] + cx; v = fy*q[f,1]/q[f,2] + cy
            ok2 = (u>=0)&(u<W)&(v>=0)&(v<H)
            return np.nonzero(f)[0][ok2], u[ok2].astype(np.int32), v[ok2].astype(np.int32), q[f,2][ok2]
        _, ua, va, za = _proj(Vocc)
        if len(ua) == 0: continue
        zb = np.full((H,W), np.inf, np.float32)
        np.minimum.at(zb, (va, ua), za)
        idx, u, v, zz = _proj(Vall)
        if len(idx) == 0: continue
        vis = zz <= zb[v,u] + 0.02      # 2cm 여유 — 자기 자신이 최전면이면 보인다
        idx = idx[vis]; u = u[vis]; v = v[vis]
        np.add.at(seen, idx, 1)
        np.add.at(inm, idx, msk[v,u].astype(np.int32))
        nseen += 1
    MINF = 5                            # 5프레임 미만은 근거가 부족하다 -> 1.0 (감점 없음)
    ratio = np.where(seen >= MINF, inm/np.maximum(seen,1), 1.0).astype("<f4")
    for i, (name, V) in enumerate(person_verts):
        seg = ratio[off[i]:off[i+1]]
        hdr = b"LCF1" + np.uint32(len(V)).tobytes() + np.uint64(_vhash(V)).tobytes()
        with open(f"{S}/{name}_confidence.bin", "wb") as fh:
            fh.write(hdr); fh.write(np.ascontiguousarray(seg, dtype="<f4").tobytes())
    low = (ratio[seen>=MINF] < 0.55).mean()*100 if (seen>=MINF).any() else 0.0
    mark(f"신뢰도 사이드카 {len(person_verts)}개 ({nseen}프레임, {time.time()-tc0:.1f}s) "
         f"— 근거있는 정점 {int((seen>=MINF).sum()):,}, 0.55 미만 {low:.1f}%")

_json.dump({"session_id":_os.path.basename(S.rstrip("/")),"count":len(persons),
            "persons":persons,
            # 크기 범위 밖이라 사람으로 세지 않았지만 **버리지도 않은** 덩어리.
            # 실제로 사람인 경우가 확인됐으므로 반드시 눈으로 확인할 것.
            "review":review if "review" in dir() else [],
            "rejected":rejected if "rejected" in dir() else [],
            "note":"객체 볼륨을 연결 성분으로 나눈 뒤 사람 크기인 것만 남겼다. "
                   "프레임 간 추적은 하지 않으므로 같은 사람이 크게 끊기면 둘로 셀 수 있다."},
           open(f"{S}/persons.json","w",encoding="utf-8"), ensure_ascii=False, indent=2)
mark(f"융합 {t_fuse:.1f}초 (배경 {nb}프레임 / 객체 {no}프레임)")
print(f"  배경({BGV*100:.0f}cm): {len(mbg.vertices):>9,}정점  {mbg.get_surface_area():7.1f} m²")
print(f"  객체({OBV*100:.0f}cm): {len(mob.vertices):>9,}정점  {mob.get_surface_area():7.1f} m²")
print(f"  합계      : {len(mbg.vertices)+len(mob.vertices):>9,}정점   융합시간 {t_fuse:.1f}초")
print(f"\n  사람 분리 : {len(persons)}명")
for p_ in persons:
    c=p_["center_xyz"]; d=p_["size_m"]
    print(f"    {p_['file']}  {p_['surface_m2']:5.2f}㎡  "
          f"{d[0]:.2f}x{d[1]:.2f}x{d[2]:.2f}m  중심({c[0]:+.2f},{c[1]:+.2f},{c[2]:+.2f})")
try:
    if review:
        print(f"\n  ⚠️ 확인 필요 {len(review)}개 (사람일 수 있음 — 버리지 않고 남겼다):")
        for r_ in review:
            d=r_["size_m"]
            print(f"    {r_['file']}  {r_['surface_m2']:5.2f}㎡  "
                  f"{d[0]:.2f}x{d[1]:.2f}x{d[2]:.2f}m — {r_['reason']}")
except NameError: pass
try:
    if rejected:
        print(f"  제외된 큰 조각 {len(rejected)}개 (조용히 버리지 않고 알림):")
        for r_ in rejected[:5]:
            d=r_["size_m"]; print(f"    {r_['surface_m2']:5.2f}㎡  {d[0]:.2f}x{d[1]:.2f}x{d[2]:.2f}m — {r_['reason']}")
except NameError: pass
