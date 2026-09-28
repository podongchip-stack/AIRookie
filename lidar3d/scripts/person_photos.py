"""
사람별 **참조 사진**을 뽑는다 (3D와 나란히 비교하기 위한 것).

왜 필요한가:
  "3DGS로 얼마나 좋아질 수 있나"의 **상한은 원본 영상**이다. 어떤 재구성 기법도
  찍히지 않은 디테일을 만들어낼 수는 없다 (만들어낸다면 그건 지어낸 것이고,
  의료 판단에서 가장 위험한 실패다 — documents/warning/0917v1_2148 3번).

  실측: 이 세션에서 사람이 최대 1905x1438px(화면의 98.5%)로 찍혔다.
        1픽셀 ≈ 0.1cm 이므로, 현재 메시의 1cm 복셀보다 **10배 세밀한 정보**가 원본에 있다.
        즉 3DGS를 시도할 가치가 있다는 근거가 된다.

  그리고 사진 자체가 현장 판단에 직접 쓸모가 있다 — 의사는 3D만이 아니라 실제 사진도 본다.

선택 기준:
  ① 그 사람의 3D 중심이 검출 박스 안에 들어오는 프레임만 (다른 사람 사진을 붙이지 않는다)
  ② 박스가 클수록 = 가까이서 찍힘
  ③ 라플라시안 분산이 클수록 = 초점이 맞음 (모션블러 배제)

사용법:
  python3 scripts/person_photos.py <세션경로> [--per-person 3]

생성: <세션>/person_NN_photo_K.jpg , photos.json
"""
import argparse, csv, json, sys
from pathlib import Path

import numpy as np
import cv2

ap = argparse.ArgumentParser()
ap.add_argument("session", type=Path)
ap.add_argument("--per-person", type=int, default=3)
a = ap.parse_args()

sess = a.session.resolve()
pj = sess / "persons.json"
dj = sess / "detections_2d.json"
for f in (pj, dj, sess / "metadata.json", sess / "arkit_pose.csv"):
    if not f.exists():
        sys.exit(f"[실패] {f.name}이 없습니다. 적응형 융합과 물체 검출을 먼저 실행하세요.")

persons = json.loads(pj.read_text(encoding="utf-8")).get("persons", [])
if not persons:
    sys.exit("[실패] 분리된 사람이 없습니다.")
det = json.loads(dj.read_text(encoding="utf-8"))
meta = json.loads((sess / "metadata.json").read_text(encoding="utf-8"))
VW, VH = meta["video_frame_width"], meta["video_frame_height"]

poses = {}
for r in csv.DictReader(open(sess / "arkit_pose.csv")):
    fi = int(r["frame_index"])
    if fi >= 0 and r["tracking_state"] == "2":
        poses[fi] = r

def quat_to_R(x, y, z, w):
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

# 각 사람의 3D 중심을 프레임마다 투영해, 그 사람을 담은 검출 박스를 찾는다
cand = {p["index"]: [] for p in persons}
for fi_s, dets in det["frames"].items():
    fi = int(fi_s)
    p = poses.get(fi)
    if p is None:
        continue
    R = quat_to_R(*[float(p[k]) for k in ("qx", "qy", "qz", "qw")])
    t = np.array([float(p[k]) for k in ("tx", "ty", "tz")])
    fx, fy, cx, cy = [float(p[k]) for k in ("fx", "fy", "cx", "cy")]
    for per in persons:
        c = np.array(per["center_xyz"])
        cam = (c - t) @ R
        if cam[2] >= -1e-6:
            continue                                  # 카메라 뒤
        dep = -cam[2]
        u = cx + fx * cam[0] / dep
        v = cy - fy * cam[1] / dep
        for o in dets:
            if o["class"] != "person":
                continue
            x1, y1, x2, y2 = o["bbox"]
            if x1 <= u <= x2 and y1 <= v <= y2:
                cand[per["index"]].append((fi, (x2-x1)*(y2-y1), o["bbox"], float(dep)))
                break

cap = cv2.VideoCapture(str(sess / "video.mov"))
if not cap.isOpened():
    sys.exit("[실패] video.mov를 열 수 없습니다.")

# 필요한 프레임만 모아 한 번의 순회로 읽는다 (영상 seek는 느리고 부정확하다)
need = {}
for idx, lst in cand.items():
    for fi, area, bbox, dep in sorted(lst, key=lambda x: -x[1])[:a.per_person * 4]:
        need.setdefault(fi, []).append((idx, area, bbox, dep))

frames = {}
fi = -1
while True:
    ok, fr = cap.read()
    if not ok:
        break
    fi += 1
    if fi in need:
        frames[fi] = fr
cap.release()

out = {}
for per in persons:
    idx = per["index"]
    scored = []
    for fi, area, bbox, dep in sorted(cand[idx], key=lambda x: -x[1])[:a.per_person * 4]:
        fr = frames.get(fi)
        if fr is None:
            continue
        x1, y1, x2, y2 = [int(max(0, v)) for v in bbox]
        x2, y2 = min(VW, x2), min(VH, y2)
        if x2 - x1 < 60 or y2 - y1 < 60:
            continue
        crop = fr[y1:y2, x1:x2]
        # 초점 선명도: 라플라시안 분산이 낮으면 모션블러
        sharp = float(cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
        scored.append((sharp, area, fi, crop, dep))
    scored.sort(key=lambda s: -(s[0] * (s[1] ** 0.5)))     # 선명도 x sqrt(크기)
    saved = []
    for k, (sharp, area, f_, crop, dep) in enumerate(scored[:a.per_person], 1):
        name = f"person_{idx:02d}_photo_{k}.jpg"
        cv2.imwrite(str(sess / name), crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
        saved.append({"file": name, "frame": f_, "size_px": [crop.shape[1], crop.shape[0]],
                      "sharpness": round(sharp, 1), "distance_m": round(dep, 2)})
    out[str(idx)] = saved
    print(f"  사람 {idx}: 사진 {len(saved)}장 "
          + (f"(최대 {saved[0]['size_px'][0]}x{saved[0]['size_px'][1]}px, "
             f"거리 {saved[0]['distance_m']}m)" if saved else "— 후보 없음"))

(sess / "photos.json").write_text(json.dumps({"persons": out}, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
print(f"  -> {sess/'photos.json'}")
