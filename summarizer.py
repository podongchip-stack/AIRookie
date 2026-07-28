"""필터링된 통화 텍스트를 SBAR 형태의 구조화된 요약으로 변환한다 (AI 처리, sLLM).

모델/API 호출부를 여기에 모아두고, transcribe.py는 이 함수만 호출한다.
나중에 Ollama 대신 다른 LLM 백엔드로 바꾸더라도 이 파일만 교체하면 된다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ollama_bootstrap import OllamaBootstrapError, ensure_ollama_ready

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

    payload = json.dumps(
        {
            "model": llm_model,
            "system": STRUCTURE_SYSTEM_PROMPT,
            "prompt": filtered_text,
            "format": "json",
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

    try:
        structured = json.loads(result["response"])
    except (KeyError, json.JSONDecodeError) as e:
        raise StructuringError(f"LLM 응답을 JSON으로 파싱하지 못했습니다: {e}") from e

    return _normalize(structured)


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
