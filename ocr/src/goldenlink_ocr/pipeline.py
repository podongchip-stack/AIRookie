"""문서 OCR 파이프라인 진입점.

    레이아웃 검출(AI) → 영역 정리·라우팅(규칙) → 영역별 인식(AI) → 검증(규칙)

페이지를 통째로 넣는 대신 영역별로 나눠 알맞은 태스크로 읽는다. 실측 기준으로
전체 페이지 방식보다 재현율이 68% → 88%로 올랐고 VRAM 피크는 8.3GB → 2.1GB로 줄었다.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from .config import Config, apply_hf_environment, load_config
from .layout import LayoutDetector
from .recognizer import Recognizer
from .router import plan_regions
from .validator import review_reasons


class DocumentOCR:
    """레이아웃 인지 문서 OCR.

    사용 예:
        ocr = DocumentOCR()
        result = ocr.read("진단서.png")
        print(result["text"])
    """

    def __init__(self, config: Config | None = None, device: str = "cuda"):
        apply_hf_environment()
        self.config = config or load_config()
        self.detector = LayoutDetector(
            self.config.layout.onnx_path, imgsz=self.config.layout.imgsz)
        self.recognizer = Recognizer(self.config.recognizer, device=device)

    def read(self, image_or_path: Image.Image | str | Path) -> dict:
        """문서 1장을 읽는다.

        반환:
            text          결합된 전체 텍스트 (읽기 순서)
            regions       영역별 결과 [{cls, conf, xyxy, task, text, needs_review, review_reasons}]
            needs_review  하나라도 검토가 필요하면 True
        """
        image = self._load_image(image_or_path)
        regions = self.detector.detect(image, self.config.layout.conf_threshold)
        planned = plan_regions(regions, self.config.router)

        results, texts = [], []
        for region in planned:
            crop = self._prepare_crop(image, region["xyxy"])
            if crop is None:
                continue
            recognized = self.recognizer.recognize(crop, region["task"])
            reasons = review_reasons(recognized)
            results.append({
                **region,
                "text": recognized["text"],
                "generated_tokens": recognized["generated_tokens"],
                "needs_review": bool(reasons),
                "review_reasons": reasons,
            })
            if recognized["text"]:
                texts.append(recognized["text"])

        return {
            "text": "\n".join(texts),
            "regions": results,
            "needs_review": any(r["needs_review"] for r in results),
            # 이 결과가 AI 처리물임을 명시한다 (CLAUDE.md 핵심 AI 활용 원칙)
            "source": "ai",
            "model_used": {
                "layout": self.config.layout.repo_id,
                "recognizer": self.config.recognizer.repo_id,
            },
        }

    def _load_image(self, image_or_path: Image.Image | str | Path) -> Image.Image:
        if isinstance(image_or_path, Image.Image):
            return image_or_path.convert("RGB")
        # 실물 촬영본은 EXIF 회전 정보가 있어 반영하지 않으면 옆으로 누운 채 처리된다
        return ImageOps.exif_transpose(Image.open(image_or_path)).convert("RGB")

    def _prepare_crop(self, image: Image.Image, xyxy: tuple[int, ...]) -> Image.Image | None:
        """영역을 잘라내고, 너무 작으면 업스케일한다. 유효하지 않으면 None."""
        crop = image.crop(xyxy)
        if min(crop.size) < 10:
            return None
        min_side = self.config.router.min_side
        if min(crop.size) < min_side:
            scale = min_side / min(crop.size)
            crop = crop.resize((int(crop.width * scale), int(crop.height * scale)), Image.LANCZOS)
        return crop
