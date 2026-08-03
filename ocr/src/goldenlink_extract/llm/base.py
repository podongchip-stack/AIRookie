"""LLM 호출부의 공통 모양.

쓰는 쪽(`extractor.py`)은 뒤에 무엇이 있는지 몰라도 되고, 모델을 바꿔도 비즈니스
로직은 손대지 않는다 — CLAUDE.md의 "모델/API 호출부와 비즈니스 로직은 분리해서
구현한다" 규칙이 요구하는 바다.

    client = StubLlmClient()      # LLM 없이 (맥에서 개발, 테스트, CI)
    client = OllamaClient(cfg)    # 실제 추론 (GPU 장비)
"""

from __future__ import annotations

from typing import Protocol


class LlmError(RuntimeError):
    """LLM 호출이 끝내 실패했을 때. 추출기는 이걸 잡아 해당 그룹만 포기한다."""


class LlmClient(Protocol):
    """구조화된 JSON 하나를 받아오는 통로."""

    def complete_json(self, *, system: str, prompt: str, json_schema: dict) -> dict:
        """스키마를 만족하는 JSON 객체를 돌려준다.

        구현이 형식 보장까지 책임진다. 즉 이 함수가 정상 반환했다면 반환값은
        `json_schema`를 만족한다. 만족시키지 못하면 `LlmError`를 던진다.
        내용이 맞는지(환각 여부)는 여기서 판단하지 않는다 — `grounding.py`의 몫이다.
        """
        ...

    def describe(self) -> str:
        """모델 식별자. 결과 JSON의 `modelUsed.llm`에 그대로 기록된다."""
        ...

    def preload(self) -> None:
        """모델을 미리 메모리에 올린다.

        동시 상주 모드에서 필요하다. 첫 호출 때 로드하면 그 순간에 OCR 모델과
        VRAM을 동시에 요구하게 되는데, 그때는 이미 OCR이 이미지를 처리 중일 수
        있다. 미리 올려두면 점유가 예측 가능해지고, 첫 문서의 처리 시간에 모델
        로드 시간이 섞이지 않아 성능 측정도 정확해진다.
        """
        ...
