"""Ollama 구현 — 실제 추론.

왜 Ollama인가
-------------
- 팀이 이미 그 스택이다. CLAUDE.md의 voice 출력 예시가 `"llm": "qwen3:14b"`인데
  이건 Ollama 모델 태그 표기다. 여기서 다른 런타임을 쓰면 모델 관리가 둘로 갈라진다
- **구조화 출력**을 지원한다. `format`에 JSON Schema를 주면 문법 제약 디코딩이
  걸려 형식이 깨진 출력 자체가 생성되지 않는다. 파싱 실패를 재시도로 때우는 것과는
  다른 층위의 보장이다
- 전부 로컬이다. 환자·병원 데이터가 외부로 나가지 않는다 (On-Premise 원칙)
- 서버 프로세스가 분리돼 있어 OCR(torch)과 같은 파이썬 프로세스에 모델을 올리지
  않는다. 한쪽이 죽어도 다른 쪽은 살아 있다

의존성을 늘리지 않으려고 `requests` 대신 표준 라이브러리 `urllib`을 쓴다.
이 패키지는 pydantic 하나로 도는 것이 장점인데, HTTP 호출 한 종류 때문에 패키지를
더할 이유가 없다.

동시 상주
---------
`keep_alive=-1`이면 Ollama가 모델을 VRAM에 무기한 붙잡아 둔다. OCR 모델(약 2.1GB)과
LLM(qwen3:14b Q4 약 10.5GB)이 RTX 5080의 16GB 안에 함께 올라간 채로 문서를 연달아
처리한다. 문서마다 모델을 내렸다 올리는 비용이 사라지는 대신 여유 VRAM이 줄어든다.
여유가 부족하면 `keep_alive=0`으로 바꾸면 순차 모드가 된다 (`config.py` 참고).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..config import LlmConfig
from .base import LlmError


class OllamaClient:
    """Ollama 서버에 붙어 구조화된 JSON을 받아온다."""

    def __init__(self, config: LlmConfig) -> None:
        self._cfg = config
        # 모델이 `think`를 모르면 한 번 실패한 뒤 이 값을 내려 재시도한다.
        # 매 호출마다 같은 실패를 반복하지 않도록 인스턴스에 기억해 둔다
        self._send_think = True

    # --- 공개 메서드 --------------------------------------------------------

    def describe(self) -> str:
        return self._cfg.model

    def preload(self) -> None:
        """모델을 VRAM에 미리 올린다.

        Ollama는 프롬프트 없이 `/api/generate`를 부르면 로드만 하고 끝낸다.
        """
        self._request(
            "/api/generate", {"model": self._cfg.model, "keep_alive": self._cfg.keep_alive}
        )

    def loaded_models(self) -> list[dict]:
        """지금 메모리에 올라와 있는 모델 목록.

        동시 상주가 실제로 되고 있는지 눈으로 확인하는 용도다. 각 항목의
        `size_vram`이 VRAM 점유 바이트다.
        """
        try:
            return self._request("/api/ps", None, method="GET").get("models", [])
        except LlmError:
            return []

    def complete_json(self, *, system: str, prompt: str, json_schema: dict) -> dict:
        """스키마를 만족하는 JSON 객체를 받아온다.

        `format`으로 문법 제약이 걸려 있어 형식 오류는 원칙적으로 나지 않는다.
        그래도 재시도를 두는 이유는 통신 실패와, 모델이 제약 안에서 빈 응답을
        내놓는 드문 경우 때문이다.
        """
        payload = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "format": json_schema,
            "stream": False,
            "keep_alive": self._cfg.keep_alive,
            "options": {
                # 추출 작업이라 창의성이 필요 없다. 같은 입력에 같은 출력이 나와야
                # 프롬프트를 고쳤을 때 그 효과를 판단할 수 있다
                "temperature": 0,
                "seed": 0,
                "num_ctx": self._cfg.num_ctx,
                "num_predict": self._cfg.num_predict,
            },
        }

        last_error: Exception | None = None
        for attempt in range(self._cfg.max_retries + 1):
            body = dict(payload)
            if self._send_think:
                body["think"] = self._cfg.think

            content = ""
            try:
                response = self._request("/api/chat", body)
                content = (response.get("message") or {}).get("content", "")
                if not content.strip():
                    raise LlmError("응답이 비어 있다")
                return json.loads(content)
            except LlmError as error:
                # `think`를 모르는 모델이면 서버가 거부한다. 한 번은 빼고 다시 해본다
                if self._send_think and "think" in str(error).lower():
                    self._send_think = False
                    continue
                last_error = error
            except json.JSONDecodeError as error:
                # format 제약이 걸려 있어 여기 오는 건 이례적이다. 그냥 두면 원인을
                # 못 찾으므로 응답 앞부분을 붙여 남긴다
                last_error = LlmError(
                    f"JSON으로 못 읽었다: {error} / 응답 앞부분: {content[:200]!r}"
                )

        raise LlmError(f"{self._cfg.max_retries + 1}번 시도했지만 실패했다: {last_error}")

    # --- 내부 ---------------------------------------------------------------

    def _request(self, path: str, body: dict | None, method: str = "POST") -> dict:
        url = f"{self._cfg.host.rstrip('/')}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._cfg.timeout_sec) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:300]
            if error.code == 404:
                raise LlmError(
                    f"모델을 찾을 수 없다: {self._cfg.model}\n"
                    f"  먼저 받아야 한다:  ollama pull {self._cfg.model}\n"
                    f"  서버 응답: {detail}"
                ) from None
            raise LlmError(f"Ollama가 {error.code}로 거부했다: {detail}") from None
        except urllib.error.URLError as error:
            raise LlmError(
                f"Ollama에 접속하지 못했다 ({self._cfg.host}): {error.reason}\n"
                f"  서버가 떠 있는지 확인:  ollama serve\n"
                f"  다른 장비의 GPU를 쓴다면 GOLDENLINK_OLLAMA_HOST 를 설정할 것"
            ) from None
        except TimeoutError:
            raise LlmError(
                f"{self._cfg.timeout_sec}초 안에 응답이 없다. "
                f"모델이 크거나 VRAM이 부족해 CPU로 밀려났을 수 있다"
            ) from None
