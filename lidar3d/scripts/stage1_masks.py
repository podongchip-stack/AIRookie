"""
1단계 — 사람 마스크 추출 (YOLO 전용 프로세스)

왜 2단계로 나누는가:
  torch(YOLO)와 open3d(TSDF 융합)를 **한 프로세스에서 import하면 이 환경에서 멈춘다**
  (CPU 0%로 대기 상태에 빠짐, 실측 확인). 그래서 검출과 융합을 별도 프로세스로 분리했다.
  부수 효과로 마스크가 파일로 남아 **재사용**된다 — 융합 파라미터를 바꿔가며 여러 번
  실험할 때 YOLO를 다시 돌릴 필요가 없다.

사용법:
  python3 scripts/stage1_masks.py <세션경로> [클래스] [--model ...] [--imgsz N] [--conf F] [--stride N]
  예) python3 scripts/stage1_masks.py server/sessions/session_XXX person --imgsz 1280

생성: <세션>/person_masks.npz, <세션>/person_instances.npz

검출률이 3D 완성도를 직접 좌우한다:
  YOLO가 못 잡은 프레임은 융합에 기여하지 못한다. 그래서 사람이 일부 각도에서만
  잡히면 3D도 그 각도만 만들어진다. 놓침을 줄이는 것이 곧 3D 완성도다.

기본값은 추측이 아니라 실측으로 정했다 (session_20260919v6, 표본 40프레임):

  설정                        사람 검출 프레임   총 인원   소요
  n-seg @640 conf.35 (예전)        12/40        16      4s
  m-seg @640 conf.15               18/40        32      8s
  m-seg @640 conf.08               19/40        47     10s   ← 오검출로 인원만 늘어남
  l-seg @640 conf.15 (현재)        22/40        34     16s

  n-seg @1280                      14/40        16     11s
  m-seg @1280                      14/40        20     38s   ← 해상도를 올리면 오히려 나빠진다

⚠️ imgsz를 640보다 올리지 말 것.
  일반적으로는 해상도를 올리면 작은 물체 검출이 좋아지지만, 이 영상은 사람이 0.87m
  거리에서 1725x1328px로 **이미 화면을 가득 채운다**. 1280으로 넣으면 YOLO가 학습한
  크기 분포를 벗어나 오히려 놓친다. 위 표가 실측 결과다.

--stride 는 1을 유지할 것. 건너뛴 프레임은 그 시점을 융합에 기여시키지 못해
3D가 부분적으로만 만들어진다 (예전 코드는 idx%3으로 2/3을 버리고 있었다).
"""
import argparse, os, sys, time, csv, json, numpy as np, cv2
from ultralytics import YOLO

_ap = argparse.ArgumentParser()
_ap.add_argument("session")
_ap.add_argument("classes", nargs="?", default="person")
_ap.add_argument("--model", default=None, help="가중치 경로/이름 (미지정 시 자동 선택)")
_ap.add_argument("--imgsz", type=int, default=640, help="올리지 말 것 — 위 주석의 실측 참고")
_ap.add_argument("--conf", type=float, default=0.15)
_ap.add_argument("--stride", type=int, default=1, help="대상 프레임 N개마다 1장 (1=전부)")
_a = _ap.parse_args()

S=_a.session; t0=time.time()
TARGETS={c.strip() for c in _a.classes.split(",") if c.strip()}
m=json.load(open(f"{S}/metadata.json",encoding="utf-8"))
W,H=m["depth_width"],m["depth_height"]; vw,vh=m["video_frame_width"],m["video_frame_height"]
sx,sy=W/vw,H/vh
rows=list(csv.DictReader(open(f"{S}/depth/index.csv")))

# ── 마스크를 만들 영상 프레임을 고르는 기준 ──────────────────────────────
#
# 예전: depth/index.csv의 video_frame_index 를 그대로 썼다.
#   그런데 이 값은 **영상과 뎁스의 저장 주기가 달라 절반이 -1**이다
#   (실측 v3: 531행 중 265행). 그 행들은 2단계에서 **직전 마스크를 재사용**했고,
#   그 사이 카메라가 움직여 마스크가 엉뚱한 표면에 적용됐다.
#   실측 어긋남: 위치 중앙 3.00cm / 회전 2.50° / 시간차 100ms.
#
# 지금: 뎁스 프레임마다 **타임스탬프가 가장 가까운 영상 프레임**을 찾는다.
#   영상은 796프레임 전부 있으므로 훨씬 가까운 것을 고를 수 있다.
#   실측 개선: 위치 1.01cm / 회전 0.90° / 시간차 33ms (각각 3배, 2.8배, 3배)
#   결과: 웅크린 사람이 2.59m → 1.86m로 줄어 크기 필터를 통과했다.
#
# 대가: YOLO를 돌릴 프레임이 늘어난다 (실측 266 → 531, 시간 2배).
_vpath=f"{S}/video_frames.csv"
_use_nearest=_os_path_exists=__import__("os").path.exists(_vpath)
if _use_nearest:
    _vf={int(r["frame_index"]):float(r["timestamp"])
         for r in csv.DictReader(open(_vpath))}
    _vt=np.array([_vf[k] for k in sorted(_vf)]); _vk=np.array(sorted(_vf))
    # 뎁스 행(depth_index) -> 최근접 영상 프레임
    nearest={}
    for r in rows:
        j=int(np.argmin(np.abs(_vt-float(r["timestamp"]))))
        nearest[int(r["depth_index"])]=int(_vk[j])
    wanted=sorted(set(nearest.values()))
else:
    # video_frames.csv가 없는 예전 세션 — 기존 방식으로 폴백
    nearest=None
    wanted=sorted({int(r["video_frame_index"]) for r in rows if int(r["video_frame_index"])>=0})
    print("⚠ video_frames.csv 없음 — 예전 방식(video_frame_index)으로 폴백합니다", flush=True)
# ⚠️ 세그멘테이션 모델을 쓴다 (bbox 아님).
#
#   bbox 마스크를 쓰면 사각형 안의 **사람 뒤 벽과 바닥까지 통째로** 객체로 잡힌다.
#   실측: "사람만" 메시가 4.6 x 1.3 x 2.4 m 띠 모양으로 나왔고 수직면이 49.4%였다
#   (사람이면 0.6 x 1.7 x 0.4 정도, 큰 덩어리 1~2개여야 한다).
#   세그멘테이션은 픽셀 단위라 사람 윤곽만 정확히 딴다.
import os as _os
if _a.model:
    _seg = _a.model
else:
    # 큰 모델을 우선 찾는다. 없으면 ultralytics가 이름만으로 내려받는다.
    _cands = []
    for _n in ["yolov8l-seg.pt", "yolov8m-seg.pt", "yolov8s-seg.pt", "yolov8n-seg.pt"]:
        _cands += [_n, f"models/{_n}", f"../CAM/models/{_n}", f"CAM/models/{_n}"]
    _seg = next((c for c in _cands if _os.path.exists(c)), "yolov8l-seg.pt")
model=YOLO(_seg)
print(f"[{time.time()-t0:5.1f}s] 모델 {_os.path.basename(str(_seg))} 로드 "
      f"(imgsz={_a.imgsz}, conf={_a.conf}, stride={_a.stride}), "
      f"대상 프레임 {len(wanted)}개, 클래스 {sorted(TARGETS)}", flush=True)
# ⚠️ 영상이 없거나 열리지 않으면 **여기서 실패해야 한다.**
#    cv2.VideoCapture는 없는 파일에도 객체를 돌려주고 read()만 False를 낸다.
#    그대로 두면 빈 마스크를 저장하고 "성공"으로 끝나, 2단계가 객체 없이 융합해버린다
#    (실측으로 확인한 조용한 실패). 원인을 명확히 알리고 비정상 종료한다.
if not os.path.exists(f"{S}/video.mov"):
    sys.exit(f"[실패] video.mov가 없습니다: {S}\n"
             f"       객체 검출에는 영상이 필요합니다. 업로드가 완료됐는지 확인하세요.")
# 건너뛴 프레임은 그 시점의 사람을 융합에 기여시키지 못한다.
# 예전에는 idx%3 이 코드에 박혀 있어 대상 프레임의 2/3을 버리고 있었다.
selected=set(wanted[::max(_a.stride,1)])
print(f"[{time.time()-t0:5.1f}s] 처리 대상 {len(selected)}/{len(wanted)} 프레임", flush=True)
cap=cv2.VideoCapture(f"{S}/video.mov")
if not cap.isOpened():
    sys.exit(f"[실패] video.mov를 열 수 없습니다 (손상 또는 코덱 문제): {S}")
masks={}; idx=-1; done=0
# 진행 상황을 파일로 남긴다. 뷰어가 이걸 읽어 "몇 %인지"를 보여준다.
# ⚠️ 실패해도 본 작업을 멈추지 않는다 (디스크/권한 문제로 스캔을 망치면 안 된다).
def _progress(stage, name, done_, total_, extra=""):
    try:
        import json as _pj, os as _po, tempfile
        d = {"stage": stage, "name": name, "done": int(done_), "total": int(total_),
             "pct": round(done_/max(total_,1)*100, 1), "extra": extra,
             "t": time.time()}
        fd, tmp = tempfile.mkstemp(dir=S, suffix=".tmp")
        with _po.fdopen(fd, "w") as fh: _pj.dump(d, fh, ensure_ascii=False)
        _po.replace(tmp, f"{S}/_progress.json")        # 원자적 교체 — 반쯤 쓰인 파일을 읽지 않게
    except Exception: pass
_progress(1, "YOLO 사람 검출", 0, len(selected))
# 인스턴스별 마스크와 신뢰도도 남긴다.
# 2단계가 "한 프레임에 사람이 동시에 몇 명 잡혔는가"를 보고 덩어리를 나누려면
# 병합 마스크만으로는 부족하다 (4차 진단에서 인스턴스 정보가 여기서 소실됐다).
inst={}
while True:
    ok,fr=cap.read()
    if not ok: break
    idx+=1
    if idx not in selected: continue
    r=model.predict(fr,conf=_a.conf,imgsz=_a.imgsz,verbose=False)[0]
    msk=np.zeros((H,W),dtype=bool)
    if r.masks is not None:
        # 세그멘테이션 마스크는 모델 입력 해상도 기준이라 뎁스 해상도로 리샘플한다.
        md = r.masks.data.cpu().numpy()                      # (n, mh, mw) 0~1
        k2 = 0
        for k, b in enumerate(r.boxes):
            if model.names[int(b.cls)] not in TARGETS: continue
            if k >= len(md): continue
            mk = (md[k] > 0.5).astype(np.uint8)
            mk = cv2.resize(mk, (W, H), interpolation=cv2.INTER_NEAREST)
            msk |= mk.astype(bool)
            if mk.sum() >= 20:
                inst[f"{idx}_{k2}"] = mk.astype(bool)
                inst[f"{idx}_{k2}_conf"] = np.array([float(b.conf)], dtype=np.float32)
                k2 += 1
        inst[f"{idx}_n"] = np.array([k2], dtype=np.int32)
    else:
        # 세그 모델이 아니면 bbox로 폴백 (정확도는 떨어진다 — 위 주석 참고)
        for b in r.boxes:
            if model.names[int(b.cls)] not in TARGETS: continue
            x1,y1,x2,y2=[float(v) for v in b.xyxy[0]]
            msk[max(0,int(y1*sy)):min(H,int(y2*sy)+1), max(0,int(x1*sx)):min(W,int(x2*sx)+1)]=True
    masks[idx]=msk; done+=1
    if done%10==0:
        print(f"[{time.time()-t0:5.1f}s] {done}프레임 처리", flush=True)
        _progress(1, "YOLO 사람 검출", done, len(selected),
                  f"{(time.time()-t0)/max(done,1)*1000:.0f}ms/프레임")
cap.release()
if not masks:
    sys.exit(f"[실패] 검사한 프레임이 0개입니다. video.mov가 비었거나 "
             f"depth/index.csv의 video_frame_index가 전부 -1일 수 있습니다.")
np.savez_compressed(f"{S}/person_masks.npz", **{str(k):v for k,v in masks.items()})
# 인스턴스별 마스크 — 2단계의 동시 검출 판정용.
# 없으면 2단계는 예전처럼 동작한다 (선택적 입력).
if inst: np.savez_compressed(f"{S}/person_instances.npz", **inst)
# 2단계가 "이 뎁스 행에 어느 마스크를 쓸지"를 알아야 한다.
# 매핑을 남기지 않으면 2단계가 video_frame_index로 되돌아가 개선이 무효가 된다.
if nearest is not None:
    import json as _json
    _json.dump({str(k):v for k,v in nearest.items()},
               open(f"{S}/person_masks_map.json","w"), ensure_ascii=False)
n=sum(1 for v in masks.values() if v.any())
_el=time.time()-t0
print(f"[{_el:5.1f}s] 완료: {len(masks)}프레임 검사, 사람 {n}프레임 -> person_masks.npz", flush=True)
# 계측을 남긴다 — 예전에는 처리 시간을 기록하지 않아 매번 손으로 재야 했다.
print(f"         YOLO {done}프레임 {_el:.0f}초 ({_el/max(done,1)*1000:.0f}ms/프레임), "
      f"매칭={'최근접 타임스탬프' if nearest is not None else 'video_frame_index(폴백)'}", flush=True)
