#!/usr/bin/env python3
"""YOLO 검출 결과를 영상 플레이어용 오버레이 JSON으로 내보낸다.

왜 필요한가:
  person_masks.npz는 numpy 형식이라 브라우저가 못 읽는다. 마스크를 프레임마다 PNG로
  굽는 방법도 있지만 파일이 수백 개가 되어 서버 화이트리스트와 캐시가 지저분해진다.
  대신 **윤곽선 좌표**로 뽑으면 파일 하나로 끝나고, 해상도와 무관하게 확대·축소된다.

좌표계:
  마스크는 뎁스 해상도(256x192), 영상은 1920x1440이다. 배율이 가로세로 모두 7.5로
  같아서 단순 스케일로 맞는다. 출력 좌표는 **0~1 정규화**라 플레이어가 어떤 크기로
  띄우든 그대로 쓸 수 있다.

생성: <세션>/detection_overlay.json
"""
import argparse, json, csv
from pathlib import Path

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path)
    ap.add_argument("--min-area", type=int, default=30,
                    help="이보다 작은 덩어리는 잡음으로 보고 버린다 (마스크 화소 기준)")
    ap.add_argument("--epsilon", type=float, default=1.5,
                    help="윤곽선 단순화 강도. 클수록 점이 줄어 파일이 작아진다")
    args = ap.parse_args()

    sess = args.session
    npz = sess / "person_masks.npz"
    if not npz.exists():
        raise SystemExit(f"❌ {npz} 없음 — 적응형 융합(1단계)을 먼저 실행하세요")

    meta = json.loads((sess / "metadata.json").read_text(encoding="utf-8"))
    VW, VH = meta["video_frame_width"], meta["video_frame_height"]

    # 프레임 -> 시각. 플레이어가 currentTime으로 프레임을 찾으려면 이게 필요하다.
    fps, times = None, {}
    fcsv = sess / "video_frames.csv"
    if fcsv.exists():
        rows = list(csv.DictReader(open(fcsv)))
        if len(rows) > 1:
            t0 = float(rows[0]["timestamp"])
            for r in rows:
                times[int(r["frame_index"])] = round(float(r["timestamp"]) - t0, 4)
            span = float(rows[-1]["timestamp"]) - t0
            fps = round((len(rows) - 1) / span, 3) if span > 0 else None

    z = np.load(npz)
    frames = {}
    total_blobs = 0
    for key in z.files:
        m = z[key]
        mh, mw = m.shape
        cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        polys = []
        for c in cnts:
            if cv2.contourArea(c) < args.min_area:
                continue
            c = cv2.approxPolyDP(c, args.epsilon, True)
            # 0~1 정규화 — 플레이어가 어떤 크기로 띄워도 그대로 쓴다
            polys.append([[round(float(p[0][0]) / mw, 4), round(float(p[0][1]) / mh, 4)]
                          for p in c])
        if polys:
            # ⚠️ 덩어리**마다** 경계상자를 따로 낸다.
            #   예전에는 모든 덩어리를 합친 bbox 하나만 저장했다. 그러면 사람이 둘일 때
            #   화면에 박스가 하나로 그려져 "YOLO가 두 사람을 합쳤다"는 오해를 준다
            #   (실측: 229프레임 중 90프레임(39%)이 덩어리 2개 이상).
            #   검출과 마스크는 정상이고 시각화만 틀렸던 것이다.
            boxes = []
            for poly in polys:
                xs = [q[0] for q in poly]; ys = [q[1] for q in poly]
                boxes.append([min(xs), min(ys), max(xs), max(ys)])
            # bbox(합집합)는 이전 형식 호환을 위해 남겨 둔다 — 새 코드는 boxes를 쓸 것
            x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
            x1 = max(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
            frames[key] = {"polys": polys, "boxes": boxes,
                           "bbox": [x0, y0, x1, y1], "n": len(polys)}
            total_blobs += len(polys)

    out = {
        "session_id": sess.name,
        "video": {"width": VW, "height": VH, "fps": fps},
        "source": "person_masks.npz (YOLO-seg 픽셀 마스크)",
        "frames_with_person": len(frames),
        "frames_checked": len(z.files),
        "total_blobs": total_blobs,
        "frame_times": times,
        "frames": frames,
        "note": "좌표는 0~1 정규화. 마스크 해상도와 영상 해상도가 달라도 그대로 쓸 수 있다.",
    }
    dst = sess / "detection_overlay.json"
    dst.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"검사 {len(z.files)}프레임 중 사람 {len(frames)}프레임, 덩어리 {total_blobs}개")
    print(f"✅ {dst}  ({dst.stat().st_size/1024:.0f}KB)")


if __name__ == "__main__":
    main()
