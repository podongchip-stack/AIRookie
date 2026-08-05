"""레이아웃 검출 — 페이지에서 영역의 위치와 종류를 찾는다. [AI 처리]

DocLayout-YOLO(Apache-2.0) 가중치를 ONNX로 변환한 것을 onnxruntime(MIT)으로 실행한다.
원본 .pt 를 돌리는 doclayout_yolo 패키지는 AGPL-3.0이라 배포물에서 제외했다.
변환본은 configs/models.yaml 의 layout.repo_id 저장소에 있고, 변환 이력은 그 모델 카드 참고.

YOLOv10 계열이라 NMS가 모델 안에 없다(NMS-free). 출력이 이미
[1, 300, 6] = (x1, y1, x2, y2, confidence, class_id) 형태여서
후처리는 좌표 역변환과 임계값 필터뿐이다.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image

PAD_VALUE = 114  # ultralytics letterbox 기본 패딩값

# 원본 모델의 클래스 순서 (변경하면 라우팅이 어긋난다)
CLASS_NAMES = (
    "title", "plain text", "abandon", "figure", "figure_caption",
    "table", "table_caption", "table_footnote", "isolate_formula", "formula_caption",
)


def letterbox(image: Image.Image, size: int) -> tuple[np.ndarray, float, float, float]:
    """종횡비를 유지한 채 size×size 로 맞추고 남는 곳을 패딩한다.

    ultralytics LetterBox와 동일하게 cv2 INTER_LINEAR를 쓴다. PIL BILINEAR은 축소 시
    안티에일리어싱이 걸려 검출 결과가 미세하게 달라진다.

    반환: (NCHW float32 배열, 확대율, 좌측 패딩, 상단 패딩)
    """
    src = np.asarray(image)  # RGB, HWC
    h, w = src.shape[:2]
    scale = min(size / w, size / h)
    nw, nh = int(round(w * scale)), int(round(h * scale))

    resized = cv2.resize(src, (nw, nh), interpolation=cv2.INTER_LINEAR) if (nw, nh) != (w, h) else src

    dw, dh = (size - nw) / 2, (size - nh) / 2
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    padded = cv2.copyMakeBorder(resized, top, bottom, left, right,
                                cv2.BORDER_CONSTANT, value=(PAD_VALUE,) * 3)

    return padded.astype(np.float32).transpose(2, 0, 1)[None] / 255.0, scale, dw, dh


class LayoutDetector:
    """페이지 이미지에서 영역 목록을 검출한다.

    CPU 실행이 기본이다. 레이아웃은 장당 0.7초 수준이라 CPU로 충분하고,
    GPU를 인식 모델(VLM)이 독점하게 두는 편이 전체 처리량에 유리하다.
    """

    def __init__(self, model_path: str | Path, imgsz: int = 1024,
                 providers: list[str] | None = None):
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"레이아웃 ONNX 모델이 없다: {model_path}\n"
                "scripts/download_models.py 를 먼저 실행한다.")
        self.session = ort.InferenceSession(
            str(model_path), providers=providers or ["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.imgsz = imgsz

    @property
    def providers(self) -> list[str]:
        return self.session.get_providers()

    def detect(self, image: Image.Image, conf_threshold: float = 0.2) -> list[dict]:
        """영역 목록을 반환한다. 각 항목은 {cls, conf, xyxy}.

        좌표는 입력 이미지 기준 픽셀값이다.
        """
        blob, scale, dw, dh = letterbox(image, self.imgsz)
        raw = self.session.run(None, {self.input_name: blob})[0][0]  # (300, 6)

        w, h = image.size
        regions = []
        for x1, y1, x2, y2, score, cls_id in raw:
            if score < conf_threshold:
                continue
            # 패딩을 빼고 원본 좌표계로 되돌린 뒤 이미지 경계로 자른다
            box = ((x1 - dw) / scale, (y1 - dh) / scale, (x2 - dw) / scale, (y2 - dh) / scale)
            clipped = (
                max(0.0, min(box[0], w)), max(0.0, min(box[1], h)),
                max(0.0, min(box[2], w)), max(0.0, min(box[3], h)),
            )
            regions.append({
                "cls": CLASS_NAMES[int(cls_id)],
                "conf": round(float(score), 3),
                "xyxy": tuple(round(v) for v in clipped),
            })
        return regions
