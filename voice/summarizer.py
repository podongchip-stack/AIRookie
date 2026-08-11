"""교정된 통화 텍스트를 LLM으로 요약한다 (AI 처리, sLLM).

두 가지를 만든다.
    structure_call_summary()   - SBAR 구조화 JSON. hub의 매칭 스코어링 입력이다.
    summarize_patient_state()  - 환자 상태 1~2문장. 사람이 한눈에 읽는 용도.

모델/API 호출부를 여기에 모아두고 transcribe.py는 이 함수들만 호출한다. 나중에
Ollama 대신 다른 LLM 백엔드로 바꾸더라도 이 파일만 교체하면 된다.
simulation3의 시뮬레이터도 자기 사본을 두지 않고 이 모듈을 그대로 쓴다 - 프롬프트가
갈리면 시연 화면과 실제 결과가 달라지기 때문이다.
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
당신은 응급이송 현장에서 구급대원의 의료 판단을 지원하는 의료 정보 전문가입니다.

아래 구급대원의 통화 내용에서 환자 정보를 정확히 추출하여,
반드시 다음 JSON 형식으로만 응답하세요.
설명이나 다른 텍스트는 절대 추가하지 마세요.

=== 필드별 상세 가이드 ===

1. "patient" (환자 인적사항 요약)
   형식: "N대 성별" (예: "50대 남성", "30대 여성")
   정보 부족 시: 빈 문자열 ""

2. "mechanism" (사고/발병 기전)
   형식: "원인 · 부위/증상"
   예시:
     - "교통사고 · 흉부 충격"
     - "낙상 · 좌측 팔"
     - "심장질환 · 가슴 통증"
   정보 부족 시: 빈 문자열 ""

3. "symptoms" (주요 증상 목록 - 배열, 중증도순)
   최우선: 의식 저하/호흡 곤란/심박 이상
   예시: ["의식 저하", "호흡 곤란", "혈압 상승"]
   정보 부족 시: 빈 배열 []

4. "treatment" (현장 처치 목록 - 배열)
   주의: 이미 시행한 처치만 포함 (계획은 제외)
   예시: ["산소 공급", "지혈 완료", "심폐소생술"]
   정보 부족 시: 빈 배열 []

5. "severity_tag" (중증도 - 필수, 하나만 선택)
   "high" (생명 위험):
     - 의식 저하, 반응 없음
     - 호흡 부전, 심정지
     - 심한 출혈
     - 다중 외상

   "medium" (중상):
     - 강한 통증
     - 중상 (골절, 화상 2도 이상)
     - 만성질환 악화

   "low" (경상):
     - 가벼운 타박상, 찰과상
     - 약한 통증

   판정 기준: 생명 위험 신호 여부, 보수적으로 판정

6. "required_department" (증상에 비추어 필요한 진료과 - 선택. 그러나 형식은 반드시 지킬 것)
   예시: "흉부외과", "신경외과", "정형외과", "응급의학"
   판단 근거 부족 시: null (빈칸이 아닌 null)

=== 특수 상황 ===

[다중 외상]
  입력: "흉부 타박, 좌팔 골절, 화상"
  → severity_tag: "high" (복합 손상)

[의식 상태 불명확]
  입력: "의식이 있는 것 같은데..."
  → 보수적으로 "high" 판정

[만성질환 악화]
  입력: "당뇨 환자, 혈당 떨어져서"
  → severity_tag: "medium"

=== 출력 JSON 형식 (필수. 배열은 여러 항목 입력 가능.) ===

{
  "patient": "환자 정보",
  "mechanism": "사고 기전",
  "symptoms": ["증상1", "증상2"],
  "treatment": ["처치1", "처치2"],
  "severity_tag": "high|medium|low",
  "required_department": "진료과 또는 null"
}
"""


BRIEF_SYSTEM_PROMPT = """\
당신은 응급이송 통화를 듣고 병원 응급실이 환자를 한눈에 파악하도록 돕는 의료 정보 전문가입니다.

아래 구급대원의 통화 내용을 읽고, 환자 상태를 1~2문장으로 요약하세요.

규칙:
- 요약 문장만 출력합니다. 제목·머리기호·JSON·부연 설명을 붙이지 마세요.
- 통화에 나온 내용만 씁니다. 나이·성별·질환을 추측해서 채우지 마세요.
- "[STT 후처리 참고 정보]" 아래는 통화 내용이 아니라 후처리 메모입니다. 요약에 넣지 마세요.
- 담는 순서: 환자 인적사항 -> 발병/사고 기전 -> 활력징후·의식 -> 시행한 처치.

예시:
60대 남성, 자택에서 갑자기 발생한 흉통으로 심근경색 의심. 혈압 100/68, 맥박 104회 빈맥이며 \
산소요법과 정맥로 확보 후 이송 중.
"""


class StructuringError(RuntimeError):
    pass


def _ollama_generate(prompt: str, system: str, llm_model: str, timeout: int) -> str:
    """Ollama /api/generate를 한 번 호출하고 응답 문자열을 돌려준다.

    오디오 파일만 있으면 끝까지 처리되도록, Ollama 설치/서버 실행/모델 pull이 안
    되어 있으면 ensure_ollama_ready()가 전부 자동으로 준비한다.

    format:"json"(문법 강제 디코딩)은 쓰지 않는다. qwen3 같은 추론형 모델과 충돌해
    빈 응답({})만 뱉는 문제가 있었다 - thinking 과정을 거치지 못하고 바로
    포기해버린다. 대신 프롬프트로만 JSON을 요청하고 응답 텍스트에서 관대하게
    추출한다 (_extract_json).
    """
    try:
        ensure_ollama_ready(llm_model)
    except OllamaBootstrapError as e:
        raise StructuringError(str(e)) from e

    payload = json.dumps(
        {"model": llm_model, "system": system, "prompt": prompt, "stream": False}
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as e:
        raise StructuringError(f"Ollama 호출 실패: {e}") from e

    return result.get("response", "")


def structure_call_summary(
    filtered_text: str, llm_model: str, timeout: int = 300, system_prompt: str | None = None
) -> dict:
    """filtered_text -> {patient, mechanism, symptoms, treatment, severity_tag, required_department}

    system_prompt를 주면 그것으로 대체한다 (simulation3 GUI가 프롬프트를 고쳐가며
    실험하는 용도). 실운영은 항상 기본값 STRUCTURE_SYSTEM_PROMPT를 쓴다.
    """
    raw = _ollama_generate(
        filtered_text, system_prompt or STRUCTURE_SYSTEM_PROMPT, llm_model, timeout
    )
    return _normalize(_extract_json(raw))


def summarize_patient_state(
    text: str, llm_model: str, timeout: int = 300, system_prompt: str | None = None
) -> str:
    """통화 텍스트 -> 환자 상태 1~2문장 요약 (SBAR 구조화와는 별개 호출).

    SBAR는 hub가 스코어링에 쓰는 기계용 구조이고, 이쪽은 사람이 한눈에 읽는
    문장이다. 한 번의 호출로 둘 다 만들게 하면 JSON 안에 산문을 끼워넣어야 해서
    파싱이 불안정해지므로 호출을 나눴다.
    """
    raw = _ollama_generate(text, system_prompt or BRIEF_SYSTEM_PROMPT, llm_model, timeout)
    brief = _THINK_TAG_RE.sub("", raw).strip()
    return " ".join(brief.split())  # 줄바꿈 제거 - 한두 줄로 붙여서 표시


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
