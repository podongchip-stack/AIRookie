"""live4d 공통 마커판(ChArUco) 정의와 인쇄용 파일 생성.

여러 세션(두 폰의 4D 녹화, 배경용 3D 스캔)을 같은 좌표계에 놓는 기준이다. 모든 세션이 녹화 중에
이 판을 한 번 이상 또렷하게 비추면, Mac이 영상에서 판을 찾아 각 세션의 ARKit 좌표를 **판 좌표계**로
옮긴다(align_sessions.py). 앱 수정이 필요 없고 기기 종류와도 무관하다(안드로이드 포함).

판 규격을 바꾸면 이 파일의 상수만 고치면 된다 — 인식 쪽도 여기 값을 그대로 쓴다.
인쇄는 **실제 크기(100%, 배율 맞춤 끄기)**로 하고, 인쇄 후 칸 하나를 자로 재서 SQUARE_MM과 다르면
align_sessions.py에 --square-mm 으로 실측값을 넘긴다(크기가 틀리면 미터 스케일이 그만큼 틀어진다).

사용법: python3 live4d/scripts/board.py   → live4d/markers/charuco_5x7_35mm.png / .pdf
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

COLS, ROWS = 5, 7            # 칸 수 (가로 × 세로) — A4 세로에 맞춘다
SQUARE_MM = 35.0             # 칸 한 변
MARKER_MM = 26.0             # 칸 안 ArUco 무늬 한 변
DICTIONARY = cv2.aruco.DICT_5X5_100
DPI = 300
A4_MM = (210.0, 297.0)

MARKERS_DIR = Path(__file__).resolve().parents[1] / "markers"


def make_board(square_mm: float = SQUARE_MM) -> "cv2.aruco.CharucoBoard":
    """판 좌표계: 원점은 판의 한 모서리, 판 평면이 z=0, 단위는 **미터**."""
    dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARY)
    scale = square_mm / SQUARE_MM
    return cv2.aruco.CharucoBoard((COLS, ROWS), square_mm / 1000.0, MARKER_MM * scale / 1000.0, dictionary)


def main() -> None:
    board = make_board()
    px_per_mm = DPI / 25.4
    bw, bh = int(round(COLS * SQUARE_MM * px_per_mm)), int(round(ROWS * SQUARE_MM * px_per_mm))
    img = board.generateImage((bw, bh), marginSize=0, borderBits=1)

    page = np.full((int(round(A4_MM[1] * px_per_mm)), int(round(A4_MM[0] * px_per_mm))), 255, np.uint8)
    y0, x0 = (page.shape[0] - bh) // 2, (page.shape[1] - bw) // 2
    page[y0:y0 + bh, x0:x0 + bw] = img
    label = (f"live4d ChArUco {COLS}x{ROWS}  square {SQUARE_MM:.0f}mm  marker {MARKER_MM:.0f}mm  "
             f"DICT_5X5_100 - print at 100% (no fit-to-page)")
    cv2.putText(page, label, (x0, y0 + bh + 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, 2)

    MARKERS_DIR.mkdir(parents=True, exist_ok=True)
    stem = MARKERS_DIR / f"charuco_{COLS}x{ROWS}_{SQUARE_MM:.0f}mm"
    cv2.imwrite(str(stem.with_suffix(".png")), page)
    from PIL import Image  # PDF는 DPI를 담아야 인쇄 크기가 정확해진다
    Image.fromarray(page).save(stem.with_suffix(".pdf"), resolution=DPI)
    print(f"✅ {stem}.png / .pdf  (판 {COLS * SQUARE_MM:.0f}×{ROWS * SQUARE_MM:.0f}mm, A4 {DPI}dpi)")


if __name__ == "__main__":
    main()
