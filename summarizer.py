"""필터링된 통화 텍스트를 SBAR 형태의 구조화된 요약으로 변환한다 (AI 처리, sLLM).

모델/API 호출부를 여기에 모아두고, transcribe.py는 이 함수만 호출한다.
나중에 Ollama 대신 다른 LLM 백엔드로 바꾸더라도 이 파일만 교체하면 된다.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from ollama_bootstrap import OllamaBootstrapError, ensure_ollama_ready

# <think>...</think> 같은 추론 과정 태그를 제거하기 위한 패턴 (qwen3 등 추론형 모델 대응)
_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
# 텍스트 안에서 가장 바깥쪽 JSON 객체를 찾기 위한 패턴 (모델이 설명을 덧붙이는 경우 대응)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

OLLAMA_URL = "http://localhost:11434/api/generate"

STRUCTURE_SYSTEM_PROMPT = """\
너는 응급이송 통화 내용에서 환자 정보를 추출하는 도우미다.
아래 통화 내용(구급대원이 병원에 전달하는 발화)을 읽고, 반드시 다음 필드만 가진 JSON 객체 하나로만 답하라.
설명이나 다른 텍스트는 절대 추가하지 마라.

{
  "patient": "환자 인적사항 요약 (예: '50대 남성'). 정보가 없으면 빈 문자열",
  "mechanism": "사고 기전 요약 (예: '교통사고 · 흉부 충격'). 정보가 없으면 빈 문자열",
  "symptoms": ["증상 목록 (문자열 배열)"],
  "treatment": ["현장 처치 목록 (문자열 배열)"],
  "severity_tag": "high, medium, low 중 하나. 의식/호흡/순환 상태가 불안정하면 high",
  "required_department": "증상에 비추어 필요할 것으로 보이는 진료과. 판단 근거가 부족하면 null"
}
"""


class StructuringError(RuntimeError):
    pass


def structure_call_summary(filtered_text: str, llm_model: str, timeout: int = 300) -> dict:
    """filtered_text -> {patient, mechanism, symptoms, treatment, severity_tag, required_department}

    오디오 파일만 있으면 이 함수 호출만으로 끝까지 처리되도록, Ollama 설치/서버
    실행/모델 pull이 안 되어 있으면 ensure_ollama_ready()가 전부 자동으로 준비한다.
    """
    try:
        ensure_ollama_ready(llm_model)
    except OllamaBootstrapError as e:
        raise StructuringError(str(e)) from e

    # format:"json"(문법 강제 디코딩)은 qwen3 같은 추론형 모델과 충돌해서 빈 응답({})만
    # 뱉는 문제가 있었다 (thinking 과정을 거치지 못하고 바로 포기해버림). 대신 프롬프트로만
    # JSON을 요청하고, 응답 텍스트에서 JSON 부분만 관대하게 추출하는 방식으로 바꿨다.
    payload = json.dumps(
        {
            "model": llm_model,
            "system": STRUCTURE_SYSTEM_PROMPT,
            "prompt": filtered_text,
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as e:
        raise StructuringError(f"Ollama 호출 실패: {e}") from e

    structured = _extract_json(result.get("response", ""))
    return _normalize(structured)


def _extract_json(response_text: str) -> dict:
    text = _THINK_TAG_RE.sub("", response_text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = _JSON_OBJECT_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise StructuringError(f"LLM 응답을 JSON으로 파싱하지 못했습니다: {e}") from e

    raise StructuringError(f"LLM 응답에서 JSON을 찾지 못했습니다: {response_text[:200]!r}")


def _normalize(structured: dict) -> dict:
    severity = structured.get("severity_tag")
    if severity not in ("high", "medium", "low"):
        severity = "medium"

    return {
        "patient": str(structured.get("patient") or ""),
        "mechanism": str(structured.get("mechanism") or ""),
        "symptoms": [str(s) for s in (structured.get("symptoms") or [])],
        "treatment": [str(t) for t in (structured.get("treatment") or [])],
        "severity_tag": severity,
        "required_department": structured.get("required_department") or None,
    }
