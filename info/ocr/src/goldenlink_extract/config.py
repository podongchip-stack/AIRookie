"""설정 — 모델 이름·주소를 코드에 박지 않는다.

CLAUDE.md의 "모델/API 호출부와 비즈니스 로직은 분리해서 구현한다 — 나중에 모델을
교체해도 로직에 영향 없게" 규칙 때문이다. 개발 장비와 실행 장비의 GPU가 달라
쓰는 모델 크기도 다르므로, 코드를 고치지 않고 바꿀 수 있어야 한다.

    맥에서 개발     GOLDENLINK_LLM_MODEL=qwen3:8b
    5080에서 실행   GOLDENLINK_LLM_MODEL=qwen3:14b   (기본값)

`goldenlink_ocr`은 `configs/models.yaml`로 설정을 읽지만 여기서는 dataclass +
환경변수를 쓴다. 이 패키지는 pydantic 하나로 도는 것이 장점인데(torch도 PyYAML도
필요 없다) 설정 파일 하나 때문에 의존성을 늘릴 이유가 없다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import timedelta, timezone

#: 이 저장소는 시각을 전부 KST로 기록한다
KST = timezone(timedelta(hours=9))

#: LLM이 "서류에서 찾지 못했다"를 나타내는 정수 값.
#: E-Gen이 미입력을 -1로 주는 것과 같은 규약을 일부러 재사용한다 — 저장소 안에
#: 결측 표현이 두 가지가 되면 매번 어느 쪽인지 확인해야 한다
MISSING_SENTINEL = -1

#: 미상을 나타내는 문자열 값
UNKNOWN_TEXT = "UNKNOWN"


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"환경변수 {name}은 정수여야 한다: {raw!r}") from None


@dataclass(frozen=True)
class LlmConfig:
    """LLM 런타임 설정. Ollama 구현만 이 값을 읽는다."""

    #: Ollama 서버 주소. 다른 장비의 GPU를 쓰려면 여기를 바꾼다
    host: str = "http://127.0.0.1:11434"
    #: 모델 태그. `ollama pull <이름>`으로 미리 받아둬야 한다
    model: str = "qwen3:14b"
    #: 컨텍스트 길이. 서류 1장은 보통 1~3K 토큰이고 필드 그룹별로 쪼개 부르므로
    #: 4K면 충분하다. 늘리면 KV 캐시가 그만큼 VRAM을 더 먹는다
    num_ctx: int = 4096
    #: 응답 최대 토큰. 진료과 목록이 길어질 수 있어 넉넉히 잡되 폭주는 막는다.
    #: 1024로 뒀을 때 실측 324회 중 8회가 여기 걸려 죽었다 — 구조화 출력은 문법
    #: 제약이 걸려 있어 형식이 깨질 수 없는데, 한도에 걸려 생성이 잘리면 문자열이
    #: 열린 채 끝나 파싱이 실패한다. 그 경우 temperature=0이라 재시도해도 같은
    #: 지점에서 같은 실패가 반복된다. 근거를 길게 복사하는 '시술·장비' 그룹에 몰렸다
    num_predict: int = 2048
    #: 모델을 VRAM에 얼마나 붙잡아둘지.
    #: -1  = 무기한 상주 (동시 상주 모드 — OCR 모델과 함께 올라간 채로 유지)
    #:  0  = 호출이 끝나면 즉시 내림 (순차 모드 — VRAM 여유가 없을 때)
    keep_alive: int = -1
    #: qwen3 계열의 사고(thinking) 모드. 필드 추출에는 득이 없고 시간과 토큰만
    #: 쓰므로 끈다. 모델이 이 옵션을 모르면 자동으로 빼고 재시도한다
    think: bool = False
    #: 요청 타임아웃(초). 14b 콜드 스타트 시간까지 고려한 값
    timeout_sec: int = 180
    #: 통신 실패·빈 응답 시 재시도 횟수
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> LlmConfig:
        return cls(
            host=_env_str("GOLDENLINK_OLLAMA_HOST", cls.host),
            model=_env_str("GOLDENLINK_LLM_MODEL", cls.model),
            num_ctx=_env_int("GOLDENLINK_LLM_NUM_CTX", cls.num_ctx),
            keep_alive=_env_int("GOLDENLINK_LLM_KEEP_ALIVE", cls.keep_alive),
        )

    def with_model(self, model: str) -> LlmConfig:
        return replace(self, model=model)


@dataclass(frozen=True)
class ExtractConfig:
    """추출 동작 설정. LLM이 무엇인지는 모른다."""

    llm: LlmConfig

    #: 근거 대조에 실패한 값을 결과에서 뺄 것인가.
    #: True(기본)면 환각으로 보고 값을 버리되, 무엇을 왜 버렸는지는 `evidence`에
    #: `grounded: false`로 남긴다. 의료 정보라 "못 읽음"보다 "지어냄"이 훨씬
    #: 위험하다는 판단이다
    drop_ungrounded: bool = True

    #: 근거 문자열이 이 길이보다 짧으면 대조 결과를 믿지 않는다.
    #: "3" 한 글자는 원문 어디에나 있어 근거 역할을 못 한다
    min_evidence_chars: int = 4

    @classmethod
    def from_env(cls) -> ExtractConfig:
        return cls(llm=LlmConfig.from_env())

    def with_llm(self, llm: LlmConfig) -> ExtractConfig:
        return replace(self, llm=llm)
