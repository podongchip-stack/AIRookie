"""
1단계 — YOLO 2D 검출만 (open3d를 import하지 않는다)

왜 2단계인가:
  torch(YOLO)와 open3d를 **한 프로세스에서 import하면 이 환경에서 멈춘다**
  (CPU 0%로 무한 대기, 실측 확인). 기존 detect_objects_3d.py가 176~177행에서
  둘을 함께 import해 바로 이 문제로 완료되지 않았다.
  stage1/stage2(적응형 융합)와 같은 방식으로 분리한다.

부수 효과: 검출 결과가 파일로 남아 3D 매핑을 여러 번 다시 돌려도 YOLO는 한 번만 돈다.

사용법:
  python3 scripts/detect_stage1.py <세션경로> [--stride 5] [--conf 0.35]

생성: <세션>/detections_2d.json
"""
import argparse, json, sys, time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("session", type=Path)
ap.add_argument("--stride", type=int, default=5, help="영상 N프레임마다 1장 처리")
ap.add_argument("--conf", type=float, default=0.35)
ap.add_argument("--model", default=None)
a = ap.parse_args()

import cv2
from ultralytics import YOLO

t0 = time.time()
sess = a.session.resolve()
video = sess / "video.mov"
if not video.exists():
    sys.exit(f"[실패] video.mov가 없습니다: {sess}")

model_path = a.model
if model_path is None:
    for c in ["yolov8n.pt", "../CAM/models/yolov8n.pt", "CAM/models/yolov8n.pt"]:
        p = (Path.cwd() / c).resolve()
        if p.exists():
            model_path = str(p); break
model = YOLO(model_path or "yolov8n.pt")
print(f"[{time.time()-t0:5.1f}s] 모델 로드: {Path(model_path or 'yolov8n.pt').name}", flush=True)

cap = cv2.VideoCapture(str(video))
if not cap.isOpened():
    sys.exit(f"[실패] video.mov를 열 수 없습니다 (손상 또는 코덱 문제)")

frames = {}
idx = -1; n = 0
while True:
    ok, frame = cap.read()
    if not ok:
        break
    idx += 1
    if idx % max(a.stride, 1):
        continue
    res = model.predict(frame, conf=a.conf, verbose=False)[0]
    dets = [{"class": model.names[int(b.cls)], "conf": round(float(b.conf), 4),
             "bbox": [round(float(v), 1) for v in b.xyxy[0]]} for b in res.boxes]
    if dets:
        frames[str(idx)] = dets
    n += 1
    if n % 25 == 0:
        print(f"[{time.time()-t0:5.1f}s] {n}프레임 처리", flush=True)
cap.release()

if n == 0:
    sys.exit("[실패] 처리한 프레임이 0개입니다 (영상이 비었을 수 있습니다)")

out = {"model": Path(model_path or "yolov8n.pt").name, "stride": a.stride,
       "conf": a.conf, "frames_processed": n, "frames": frames}
(sess / "detections_2d.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
total = sum(len(v) for v in frames.values())
print(f"[{time.time()-t0:5.1f}s] 완료: {n}프레임 처리, 검출 {total}개 "
      f"({len(frames)}프레임에서) -> detections_2d.json", flush=True)
