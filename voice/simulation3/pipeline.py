# -*- coding: utf-8 -*-
"""음성 파일 -> STT -> (오인식 사전 교정) -> SBAR 요약 시뮬레이션 파이프라인.

feature/voice의 배치 파이프라인(transcribe.py -> summarizer.py)을 로컬 시뮬레이션용으로
재구성한 것이다. 차이점:
    - STT가 뱉은 텍스트를 text_postprocess에 넘겨 corrections.json의 "오인식 -> 정답"
      쌍과 대조하는 교정 단계가 추가돼 있다 (팀 파이프라인에는 아직 없는 단계).
      whisper 쪽에는 아무것도 붙이지 않는다.
    - 실시간 음성 필터링(문장 분류, sentence-transformers)은 시뮬레이션에서 생략한다.
    - feature/hub 전송 등 통신 없음. 결과는 화면 표시/JSON 저장까지만.
    - Ollama 자동 설치(ollama_bootstrap)는 생략 — Ollama 앱이 켜져 있어야 한다.

STT 옵션(beam_size, vad_filter, initial_prompt)과 SBAR 구조화의 시스템 프롬프트/JSON
추출/정규화 로직은 voice/transcribe.py · voice/summarizer.py와 동일하게 유지한다
(버전이 갈리면 그쪽 기준으로 맞출 것).

CLI 사용 (GUI 없이 확인용):
    python pipeline.py <오디오파일> [--model small] [--no-summary]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

SCRIPT_DIR = Path(__file__).resolve().parent
# 교정 필터·사전과 CUDA DLL 등록은 voice/로 옮겨 실운영 파이프라인(transcribe.py)과
# 공유한다. 여기에 사본을 두면 GUI로 실험하며 늘린 사전 항목이 실운영에 반영되지
# 않고 갈라지고, DLL 등록 로직도 한쪽만 고치는 사고가 난다.
sys.path.insert(0, str(SCRIPT_DIR.parent))

import cuda_setup  # noqa: E402, F401  — faster_whisper보다 먼저 import돼야 한다
from text_postprocess import (  # noqa: E402
    CORRECTIONS_PATH,
    DEFAULT_MAX_NGRAM,
    TextPostprocessResult,
    postprocess_text,
)

OLLAMA_URL = "http://localhost:11434/api/generate"

# voice/transcribe.py의 STT_INITIAL_PROMPT와 동일 (도메인 어휘 사전 확률 힌트).
# 이건 STT 모델에 주는 힌트라 텍스트 교정과는 별개 단계이므로 팀 설정 그대로 둔다.
STT_INITIAL_PROMPT = (
    "환자는 의식이 저하되어 있습니다. 호흡 곤란을 호소하고 있습니다. "
    "혈압과 맥박, 산소포화도를 측정했습니다. 심정지 상태로 심폐소생술을 시행 중입니다. "
    "출혈이 지속되고 있어 압박 지혈 중입니다. 교통사고로 흉부에 충격을 입었습니다. "
    "낙상으로 인한 골절이 의심됩니다. 구급대원입니다. 흉부외과, 신경외과, 정형외과, "
    "응급의학과로 이송하겠습니다."
)
DEFAULT_BEAM_SIZE = 5

# 화자 분리 미구현 — voice/transcribe.py와 동일한 placeholder
UNDIARIZED_SPEAKER_LABEL = "미분리"

# ---------------------------------------------------------------------------
# SBAR 구조화 (voice/summarizer.py와 동일한 프롬프트/파싱 — 통신부만 단순화)
# ---------------------------------------------------------------------------

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

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


# 환자 상태 한두 줄 요약용 (팀 파이프라인에는 없는 시뮬레이터 전용 프롬프트).
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
    """Ollama /api/generate를 한 번 호출하고 응답 문자열을 돌려준다."""
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
        raise StructuringError(
            f"Ollama 호출 실패: {e}\nOllama 앱이 켜져 있는지 확인하세요."
        ) from e
    return result.get("response", "")


def summarize_patient_state(
    text: str, llm_model: str, timeout: int = 300, system_prompt: str | None = None
) -> str:
    """통화 텍스트 -> 환자 상태 1~2문장 요약 (SBAR 구조화와는 별개 호출)."""
    raw = _ollama_generate(text, system_prompt or BRIEF_SYSTEM_PROMPT, llm_model, timeout)
    brief = _THINK_TAG_RE.sub("", raw).strip()
    return " ".join(brief.split())  # 줄바꿈 제거 — 한두 줄로 붙여서 표시


def structure_call_summary(
    text: str, llm_model: str, timeout: int = 300, system_prompt: str | None = None
) -> dict:
    """통화 텍스트 -> {patient, mechanism, symptoms, treatment, severity_tag, required_department}

    system_prompt를 주면 그것으로 대체한다 (GUI에서 프롬프트를 고쳐 실험하는 용도).
    기본값은 voice/summarizer.py와 동일한 STRUCTURE_SYSTEM_PROMPT.
    """
    raw = _ollama_generate(
        text, system_prompt or STRUCTURE_SYSTEM_PROMPT, llm_model, timeout
    )
    return _normalize(_extract_json(raw))


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


# ---------------------------------------------------------------------------
# STT
# ---------------------------------------------------------------------------

_MODEL_CACHE: dict[tuple[str, str], object] = {}


def _load_model(model_size: str, device: str, progress: Callable[[str], None]):
    """WhisperModel 하나를 로드한다 (프로세스 내 캐시 재사용)."""
    from faster_whisper import WhisperModel

    key = (model_size, device)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    progress(f"Whisper 모델 로딩 중... ({model_size}, device={device})")
    started = time.perf_counter()
    model = WhisperModel(model_size, device=device, compute_type="auto")
    progress(f"모델 로딩 완료 ({time.perf_counter() - started:.1f}초, device={device})")
    _MODEL_CACHE[key] = model
    return model


def transcribe_audio(
    audio_path: Path, model_size: str, device: str, progress: Callable[[str], None]
):
    """음성을 변환한다. device="auto"는 cuda로 시도 후 실패하면 cpu로 재시도한다.

    word_timestamps는 켜지 않는다 — 교정에 확신도를 쓰지 않으므로 단어별 정렬
    연산이 불필요하다.

    CUDA 실패는 모델 로드가 아니라 실제 인코딩 시점(DLL 로드)에 나는 경우가
    있어서, 변환 단계까지 폴백 범위에 포함한다. (RTX 5080 Blackwell + ctranslate2
    조합의 커널/DLL 문제 대응)
    """
    tried = ["cuda", "cpu"] if device == "auto" else [device]
    last_error: Exception | None = None
    for dev in tried:
        try:
            model = _load_model(model_size, dev, progress)
            progress(
                f"변환 중: {audio_path.name} (device={dev}, beam_size={DEFAULT_BEAM_SIZE})"
            )
            segments_iter, info = model.transcribe(
                str(audio_path),
                language="ko",
                vad_filter=True,
                beam_size=DEFAULT_BEAM_SIZE,
                initial_prompt=STT_INITIAL_PROMPT,
            )
            segments = list(segments_iter)  # 제너레이터 소진 (여기서 실제 연산 발생)
            return segments, info, dev
        except Exception as e:  # ctranslate2가 다양한 예외 타입을 던짐
            last_error = e
            _MODEL_CACHE.pop((model_size, dev), None)
            progress(f"device={dev} 실패: {e}")
            if dev != tried[-1]:
                progress("다음 장치로 재시도합니다...")
    raise RuntimeError(f"음성 변환에 실패했습니다: {last_error}")


# ---------------------------------------------------------------------------
# 전체 파이프라인
# ---------------------------------------------------------------------------


def run_pipeline(
    audio_path: str | Path,
    stt_model: str = "medium",
    device: str = "auto",
    llm_model: str = "qwen3:14b",
    system_prompt: str | None = None,
    use_correction: bool = True,
    max_ngram: int = DEFAULT_MAX_NGRAM,
    do_summarize: bool = True,
    progress: Callable[[str], None] = print,
) -> dict:
    """음성 파일 하나를 끝까지 처리해 결과 dict를 반환한다.

    system_prompt를 주면 SBAR 구조화에 그 프롬프트를 쓴다 (없으면 기본 프롬프트).

    반환 구조:
        {
          "call_summary_message": voice/schema.py CallSummaryMessage와 같은 모양
                                  (hub 전송은 하지 않음),
          "patient_brief": 환자 상태 1~2문장 요약 (팀 스키마에 없는 필드라
                           call_summary_message 밖에 둔다),
          "text_postprocess": 교정 내역 (corrections/llm_notice/설정값),
          "segments": STT 세그먼트 [{start, end, text}],
          "timings": 단계별 소요 시간(초),
        }
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"오디오 파일이 없습니다: {audio_path}")

    timings: dict[str, float] = {}

    started = time.perf_counter()
    segments, info, used_device = transcribe_audio(audio_path, stt_model, device, progress)
    timings["stt"] = round(time.perf_counter() - started, 2)
    progress(f"변환 완료 ({timings['stt']}초, 세그먼트 {len(segments)}개)")

    segment_rows = [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in segments
    ]
    raw_text = " ".join(row["text"] for row in segment_rows)

    post: TextPostprocessResult | None = None
    if use_correction:
        progress(f"오인식 교정 중... ({CORRECTIONS_PATH.name}, max_ngram={max_ngram})")
        started = time.perf_counter()
        post = postprocess_text(raw_text, CORRECTIONS_PATH, max_ngram=max_ngram)
        timings["correction"] = round(time.perf_counter() - started, 2)
        progress(f"교정 완료 ({timings['correction']}초) — 교정 {len(post.corrections)}건")
        text_for_llm = post.corrected_text
        if post.llm_notice:
            text_for_llm = f"{post.corrected_text}\n\n{post.llm_notice}"
    else:
        text_for_llm = raw_text

    summary: dict | None = None
    brief: str | None = None
    if do_summarize:
        progress(f"SBAR 구조화 중... ({llm_model})")
        started = time.perf_counter()
        summary = structure_call_summary(text_for_llm, llm_model, system_prompt=system_prompt)
        timings["summarize"] = round(time.perf_counter() - started, 2)
        progress(f"구조화 완료 ({timings['summarize']}초)")

        progress(f"환자 상태 요약 중... ({llm_model})")
        started = time.perf_counter()
        brief = summarize_patient_state(text_for_llm, llm_model)
        timings["brief"] = round(time.perf_counter() - started, 2)
        progress(f"요약 완료 ({timings['brief']}초) — {brief}")

    # voice/transcribe.py와 동일한 방식으로 통화 시작 시각을 근사
    call_start = datetime.now(timezone.utc) - timedelta(seconds=info.duration)
    turns = [
        {
            "speaker": UNDIARIZED_SPEAKER_LABEL,
            "timestamp": (call_start + timedelta(seconds=row["start"])).strftime("%H:%M:%S"),
            "text": row["text"],
        }
        for row in segment_rows
    ]

    message = {
        "transcript": {
            "raw_text": raw_text,
            "filtered_text": post.corrected_text if post else raw_text,
            "language": info.language or "ko",
            "timestamp": call_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_sec": round(info.duration, 1),
            "turns": turns,
        },
        "summary": summary,
        "source": "ai",
        "model_used": {
            "stt": f"faster-whisper-{stt_model}({used_device})",
            "llm": llm_model if do_summarize else None,
        },
    }

    return {
        "call_summary_message": message,
        "patient_brief": brief,
        "text_postprocess": (
            {
                "corrections": [asdict(c) for c in post.corrections],
                "llm_notice": post.llm_notice,
                "max_ngram": max_ngram,
            }
            if post
            else None
        ),
        "segments": segment_rows,
        "timings": timings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="음성 파일 STT + 텍스트 기반 교정 + SBAR 요약 (CLI)"
    )
    parser.add_argument("audio", type=Path)
    parser.add_argument("--model", default="medium", help="Whisper 모델 크기 (기본 medium)")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--llm", default="qwen3:14b", help="Ollama 모델 (기본 qwen3:14b)")
    parser.add_argument("--no-correction", action="store_true", help="오인식 교정 생략")
    parser.add_argument("--no-summary", action="store_true", help="LLM 요약 생략 (STT/교정만)")
    parser.add_argument(
        "--max-ngram", type=int, default=DEFAULT_MAX_NGRAM,
        help=f"한 구간으로 묶을 최대 어절 수 (기본 {DEFAULT_MAX_NGRAM})",
    )
    parser.add_argument("--out", type=Path, default=None, help="결과 JSON 저장 경로")
    args = parser.parse_args()

    result = run_pipeline(
        args.audio,
        stt_model=args.model,
        device=args.device,
        llm_model=args.llm,
        use_correction=not args.no_correction,
        max_ngram=args.max_ngram,
        do_summarize=not args.no_summary,
    )

    if result["patient_brief"]:
        print("\n=== 환자 상태 요약 ===")
        print(result["patient_brief"])

    print("\n=== 결과 ===")
    print(json.dumps(result["call_summary_message"], ensure_ascii=False, indent=2))
    if result["text_postprocess"] and result["text_postprocess"]["llm_notice"]:
        print("\n" + result["text_postprocess"]["llm_notice"])

    if args.out:
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
