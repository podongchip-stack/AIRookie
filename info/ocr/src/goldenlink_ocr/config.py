"""설정 로딩 — configs/models.yaml 을 읽어 각 단계에 넘긴다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "configs" / "models.yaml"
MODELS_DIR = PROJECT_ROOT / "models"

def apply_hf_environment() -> None:
    """모델 캐시 관련 환경을 정리한다. 모델을 받거나 로드하기 전에 한 번 호출한다.

    캐시 위치는 각자 `HF_HOME` 환경변수로 지정한다. 지정하지 않으면 HuggingFace 기본
    위치(사용자 홈)를 쓴다. 인식 모델이 1.8GB라 C드라이브 용량이 빠듯하면
    용량이 있는 드라이브를 가리키게 설정하는 편이 좋다.
    """
    # Windows에서 개발자 모드가 꺼져 있으면 심링크 생성이 실패한다 → 복사 모드로 받는다
    if os.name == "nt":
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")


@dataclass(frozen=True)
class LayoutConfig:
    repo_id: str
    revision: str
    onnx_file: str
    license: str
    imgsz: int
    conf_threshold: float

    @property
    def onnx_path(self) -> Path:
        return MODELS_DIR / self.onnx_file


@dataclass(frozen=True)
class RecognizerConfig:
    repo_id: str
    revision: str
    license: str
    dtype: str
    max_new_tokens: int


@dataclass(frozen=True)
class RouterConfig:
    task_by_class: dict[str, str]
    default_task: str
    iou_threshold: float
    min_side: int


@dataclass(frozen=True)
class Config:
    layout: LayoutConfig
    recognizer: RecognizerConfig
    router: RouterConfig


def load_config(path: Path | str = CONFIG_PATH) -> Config:
    """models.yaml 을 읽어 설정 객체로 만든다."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Config(
        layout=LayoutConfig(
            repo_id=raw["layout"]["repo_id"],
            revision=raw["layout"]["revision"],
            onnx_file=raw["layout"]["onnx_file"],
            license=raw["layout"]["license"],
            imgsz=raw["layout"]["imgsz"],
            conf_threshold=raw["layout"]["conf_threshold"],
        ),
        recognizer=RecognizerConfig(
            repo_id=raw["recognizer"]["repo_id"],
            revision=raw["recognizer"]["revision"],
            license=raw["recognizer"]["license"],
            dtype=raw["recognizer"]["dtype"],
            max_new_tokens=raw["recognizer"]["max_new_tokens"],
        ),
        router=RouterConfig(
            task_by_class=raw["router"]["task_by_class"],
            default_task=raw["router"]["default_task"],
            iou_threshold=raw["router"]["iou_threshold"],
            min_side=raw["router"]["min_side"],
        ),
    )
