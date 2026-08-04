"""실행 설정 — 무엇을 어디에 남길 것인가.

왜 파일에 저장하는가
--------------------
이 창을 쓰는 사람이 두 종류다.

- **학습 데이터를 모으는 사람** — OCR 텍스트와 LLM 원시 응답이 쌓여야 한다
- **성능만 확인하는 사람** — 결과만 보면 되고, 폴더가 지저분해지면 곤란하다

기본값을 하나로 정하면 한쪽이 매번 손대야 하고, 손대는 걸 잊으면 조용히 틀린
상태로 돌아간다. 그래서 각자 장비에 한 번 정해두고 기억시킨다.

**학습 데이터 수집은 기본이 꺼짐이다.** 처음 받아 실행한 사람에게 쌓이지 않는
쪽이 안전하다 — 실제 병원 서류의 원문이 쌓이는 일이라, 켜는 것은 의식적인
선택이어야 한다.

경로
----
상대 경로는 저장소 루트 기준으로 푼다. 절대 경로를 넣으면 그대로 쓴다.
설정 파일(`settings.json`)은 장비마다 다르므로 커밋하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"


@dataclass(frozen=True)
class Settings:
    """한 번의 실행이 어떻게 돌지. 전부 이 창 안에서만 쓰는 값이다."""

    #: Ollama로 실제 추출할 것인가. False면 Stub(LLM 없이 로직만)
    use_llm: bool = True
    #: PDF를 이미지로 만들 해상도
    dpi: int = 200

    #: 추출 결과(DocumentFields)를 파일로 남길 것인가.
    #: 끄면 화면에서만 본다 — 성능만 확인하는 사람에게는 이쪽이 깔끔하다
    save_result: bool = True
    result_dir: str = "ocr/output"

    #: OCR 텍스트와 LLM 원시 응답을 남길 것인가 (필드 추출 모델 학습용).
    #: 기본이 꺼짐인 이유는 위 모듈 설명 참고
    collect_training_data: bool = False
    training_dir: str = "LLMdata"

    # --- 경로 ---------------------------------------------------------------

    def result_path(self) -> Path:
        return _resolve(self.result_dir)

    def ocr_text_path(self) -> Path:
        """OCR 텍스트가 쌓이는 곳 — 학습 입력."""
        return _resolve(self.training_dir) / "raw"

    def llm_raw_path(self) -> Path:
        """LLM 가공 전 응답이 쌓이는 곳 — 학습 타깃."""
        return _resolve(self.training_dir) / "llm_raw"

    def summary(self) -> str:
        """머리말에 한 줄로 보여줄 요약. 지금 무엇이 켜져 있는지 헷갈리지 않게."""
        parts = [
            "Ollama (실제 추출)" if self.use_llm else "Stub (LLM 없이 로직만)",
            f"{self.dpi}dpi",
            f"결과 저장 → {self.result_dir}" if self.save_result else "결과 저장 끔",
        ]
        parts.append(
            f"학습 데이터 수집 → {self.training_dir}" if self.collect_training_data
            else "학습 데이터 수집 끔"
        )
        return "  ·  ".join(parts)


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def load() -> Settings:
    """저장된 설정을 읽는다. 없거나 깨졌으면 기본값으로 돌아간다.

    설정 파일이 망가졌다고 창이 안 뜨면 안 된다 — 고칠 수단이 그 창뿐이다.
    모르는 키는 버린다(예전 버전이 남긴 것). 기본값에 있는 키만 받는다.
    """
    try:
        stored = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()
    if not isinstance(stored, dict):
        return Settings()
    known = {field: stored[field] for field in asdict(Settings()) if field in stored}
    try:
        return Settings(**known)
    except TypeError:
        return Settings()


def save(settings: Settings) -> None:
    """설정을 저장한다. 실패해도 예외를 던지지 않는다.

    저장이 안 되는 것보다 창이 죽는 게 나쁘다. 다음 실행에 기본값으로 돌아갈 뿐이다.
    """
    try:
        SETTINGS_PATH.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
