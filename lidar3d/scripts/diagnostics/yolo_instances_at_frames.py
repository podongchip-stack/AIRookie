#!/usr/bin/env python3
"""지정 프레임에서 YOLO 인스턴스 마스크를 그대로 뽑는다 (합치지 않는다).

stage1_masks.py는 인스턴스를 논리합으로 합쳐 저장하므로 "몇 명인지"가 사라진다.
여기서는 합치기 **전** 결과를 보존해 별도 npz로 남긴다.

torch 전용 프로세스다 — open3d를 import하지 않는다 (같이 쓰면 이 환경에서 멈춘다).
"""
import sys, json
from pathlib import Path
import numpy as np, cv2
from ultralytics import YOLO

S = Path(sys.argv[1]); frames = [int(x) for x in sys.argv[2].split(",")]
out = Path(sys.argv[3])
meta = json.loads((S/"metadata.json").read_text(encoding="utf-8"))
W, H = meta["depth_width"], meta["depth_height"]

mp = next((c for c in ["models/yolov8l-seg.pt","models/yolov8m-seg.pt","yolov8l-seg.pt"]
           if Path(c).exists()), "yolov8l-seg.pt")
model = YOLO(mp)
cap = cv2.VideoCapture(str(S/"video.mov"))
store = {}
for fi in frames:
    cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ok, img = cap.read()
    if not ok:
        print(f"  프레임 {fi}: 읽기 실패"); continue
    r = model.predict(img, conf=0.15, imgsz=640, verbose=False)[0]
    inst = []
    if r.masks is not None:
        md = r.masks.data.cpu().numpy()
        for k, b in enumerate(r.boxes):
            if model.names[int(b.cls)] != "person" or k >= len(md): continue
            m = cv2.resize((md[k] > 0.5).astype(np.uint8), (W, H),
                           interpolation=cv2.INTER_NEAREST).astype(bool)
            if m.sum() < 20: continue
            inst.append((m, float(b.conf)))
    print(f"  프레임 {fi}: person 인스턴스 {len(inst)}개 "
          f"(conf {', '.join(f'{c:.2f}' for _, c in inst)})")
    for i, (m, c) in enumerate(inst):
        store[f"{fi}_{i}"] = m
    store[f"{fi}_n"] = np.array([len(inst)])
cap.release()
np.savez_compressed(out, **store)
print(f"✅ {out}")
