"""골든링크 문서 OCR — 레이아웃 인지 파이프라인.

가중치는 저장소에 포함하지 않는다. 최초 1회 scripts/download_models.py 를 실행한다.
"""

from .config import Config, load_config
from .layout import LayoutDetector
from .pipeline import DocumentOCR
from .recognizer import Recognizer
from .router import plan_regions
from .validator import review_reasons

__all__ = [
    "Config",
    "DocumentOCR",
    "LayoutDetector",
    "Recognizer",
    "load_config",
    "plan_regions",
    "review_reasons",
]
