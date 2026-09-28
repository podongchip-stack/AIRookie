#!/usr/bin/env python3
"""뎁스 프레임마다 시간상 최근접 영상 프레임에 YOLO를 돌려 마스크를 만든다.

기존 person_masks.npz는 영상 3프레임마다(≈200ms 간격) 만들어져,
그 사이 뎁스 프레임은 직전 마스크를 재사용한다(시간차 중앙 100ms).
영상은 796프레임 전부 있으므로 최근접을 쓰면 시간차가 33ms로 줄어든다.

저장 (진단용, 파이프라인 파일과 이름을 겹치지 않게 한다):
  diag_masks_nearest.npz   — 병합 마스크 (모드 D 융합용)
  diag_inst_nearest.npz    — 인스턴스별 마스크 (B, C 검증용)

torch 전용 프로세스. open3d를 import하지 않는다.
"""
import sys, csv, json, time
from pathlib import Path
import numpy as np, cv2
from ultralytics import YOLO

S = Path(sys.argv[1])
meta = json.loads((S/"metadata.json").read_text(encoding="utf-8"))
W, H = meta["depth_width"], meta["depth_height"]

vf = {int(r["frame_index"]): float(r["timestamp"])
      for r in csv.DictReader(open(S/"video_frames.csv"))}
vt = np.array([vf[k] for k in sorted(vf)]); vk = np.array(sorted(vf))
poses = {r["timestamp"]: r for r in csv.DictReader(open(S/"arkit_pose.csv"))}
rows = list(csv.DictReader(open(S/"depth"/"index.csv")))

# 뎁스 행 -> 최근접 영상 프레임
need = {}
for i, r in enumerate(rows):
    p = poses.get(r["timestamp"])
    if p is None or p["tracking_state"] != "2": continue
    j = int(np.argmin(np.abs(vt - float(r["timestamp"]))))
    need[i] = int(vk[j])
uniq = sorted(set(need.values()))
print(f"뎁스 {len(need)}행 → 고유 영상 프레임 {len(uniq)}개에 YOLO 실행")

mp = next((c for c in ["models/yolov8l-seg.pt","models/yolov8m-seg.pt"]
           if Path(c).exists()), "yolov8l-seg.pt")
model = YOLO(mp)
cap = cv2.VideoCapture(str(S/"video.mov"))
merged, inst = {}, {}
t0 = time.time(); done = 0
for fi in uniq:
    cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ok, img = cap.read()
    if not ok: continue
    r = model.predict(img, conf=0.15, imgsz=640, verbose=False)[0]
    m_all = np.zeros((H, W), bool); k2 = 0
    if r.masks is not None:
        md = r.masks.data.cpu().numpy()
        for k, b in enumerate(r.boxes):
            if model.names[int(b.cls)] != "person" or k >= len(md): continue
            mm = cv2.resize((md[k] > 0.5).astype(np.uint8), (W, H),
                            interpolation=cv2.INTER_NEAREST).astype(bool)
            if mm.sum() < 20: continue
            inst[f"{fi}_{k2}"] = mm
            # 신뢰도도 남긴다 — 저신뢰 중복 검출을 가려내려면 필요하다
            inst[f"{fi}_{k2}_conf"] = np.array([float(b.conf)])
            k2 += 1
            m_all |= mm
    merged[str(fi)] = m_all
    inst[f"{fi}_n"] = np.array([k2])
    done += 1
    if done % 60 == 0:
        print(f"  [{time.time()-t0:5.1f}s] {done}/{len(uniq)}", flush=True)
cap.release()
np.savez_compressed(S/"diag_masks_nearest.npz", **merged)
np.savez_compressed(S/"diag_inst_nearest.npz", **inst)
json.dump({str(k): v for k, v in need.items()},
          open(S/"diag_nearest_map.json", "w"))
el = time.time() - t0
print(f"✅ 완료 — YOLO {done}프레임 {el:.0f}초 ({el/max(done,1)*1000:.0f}ms/프레임)")
print(f"   diag_masks_nearest.npz / diag_inst_nearest.npz / diag_nearest_map.json")
