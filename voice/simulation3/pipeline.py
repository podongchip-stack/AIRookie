# -*- coding: utf-8 -*-
"""음성 파일 -> STT -> 오인식 교정 -> LLM 요약. 시연/실험용 파이프라인.

**처리 내용은 실운영(voice/transcribe.py)과 같아야 한다.** 그래서 STT 프롬프트,
SBAR·환자상태 프롬프트, LLM 호출, JSON 파싱, 교정 필터, 사전, CUDA DLL 등록을
전부 voice/에서 import해서 쓴다 - 사본을 두면 시연 화면과 실제 결과가 갈린다.

이 파일이 따로 존재하는 이유는 처리가 달라서가 아니라 **주변 장치**가 달라서다.
    - 진행 상황을 progress 콜백으로 흘려보낸다 (GUI 단계 표시등용)
    - 단계별 소요 시간과 STT 세그먼트 원본을 함께 돌려준다 (화면 표시용)
    - hub 전송·파일 저장·pydantic 검증이 없다 (결과를 dict로 반환만)
    - Whisper 모델을 프로세스 내에 캐시한다 (같은 파일을 반복 실행하는 용도)
    - SBAR 시스템 프롬프트를 실행마다 바꿔 실험할 수 있다
    - 환자 상태 1~2문장 요약(patient_brief)을 추가로 만든다 - 정해진 전송
      포맷에 없는 값이라 call_summary_message 밖에 담는다

CLI 사용 (GUI 없이 확인용):
    python pipeline.py <오디오파일> [--model small] [--no-summary]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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

# STT 도메인 프롬프트·SBAR 프롬프트·LLM 호출·JSON 파싱은 전부 voice/의 실운영
# 모듈을 그대로 import해서 쓴다. 사본을 두면 시연 화면과 실제 파이프라인 결과가
# 갈린다 - 실제로 STT_INITIAL_PROMPT가 팀에서 롤백된 구버전으로 남아 있던 적이 있다.
from summarizer import (  # noqa: E402
    STRUCTURE_SYSTEM_PROMPT,  # noqa: F401  — stt_summary_gui가 pipeline에서 가져다 쓴다
    structure_call_summary,
    summarize_patient_state,
)
from transcribe import (  # noqa: E402
    DEFAULT_BEAM_SIZE,
    STT_INITIAL_PROMPT,
    UNDIARIZED_SPEAKER_LABEL,
)

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
    """음성을 변환한다. 폴백 순서는 transcribe.run_stt()와 같게 맞춘다.

    ["cuda","cpu"]가 아니라 ["auto","cpu"]인 이유: GPU가 없는 환경(맥 등)에서
    cuda를 명시하면 매번 실패 시도를 한 번씩 낭비한다. "auto"는 ctranslate2가
    알아서 고른다.

    word_timestamps는 켜지 않는다 — 교정에 확신도를 쓰지 않으므로 단어별 정렬
    연산이 불필요하다.

    CUDA 실패는 모델 로드가 아니라 실제 인코딩 시점(DLL 로드)에 나는 경우가
    있어서, 변환 단계까지 폴백 범위에 포함한다. (RTX 5080 Blackwell + ctranslate2
    조합의 커널/DLL 문제 대응)
    """
    tried = ["auto", "cpu"] if device == "auto" else [device]
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
          "text_postprocess": 교정 내역 (corrections/correction_notice/설정값),
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
    # 실제로 쓴 장치는 여기(진행 로그)에만 남긴다 — model_used.stt에 넣으면 화면의
    # 전송 포맷이 hub가 받는 문자열과 달라진다.
    progress(f"변환 완료 ({timings['stt']}초, 세그먼트 {len(segments)}개, device={used_device})")

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
        # 교정 안내문은 LLM에 넘기지 않는다 — transcribe.py와 같은 입력을 줘야
        # 시연에서 본 SBAR 결과가 실제와 같아진다. 안내문 자체는
        # STRUCTURE_SYSTEM_PROMPT에 "무시하라"는 규칙이 없어 요약에 섞일 위험도 있다.
        # 화면 표시용으로는 반환값(text_postprocess.correction_notice)에 그대로 남는다.
        text_for_llm = post.corrected_text
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

    # voice/schema.py의 CallSummaryMessage와 같은 모양으로 담는다. 이 포맷은
    # hub·dashboard와의 고정 계약이라 시뮬레이터가 임의로 필드를 늘리지 않는다 -
    # 화면에 보이는 JSON이 실제로 hub가 받는 것과 달라지면 시연이 거짓말이 된다.
    # patient_brief처럼 계약에 없는 값은 이 message 밖에 따로 담아 돌려준다.
    #
    # caseId는 원래 hub가 통화 시작 신호로 내려주는 값이라 시뮬레이터에는 없다.
    # 비워두면 화면에 뜨는 JSON이 실제 포맷과 달라 보이므로, transcribe.py가 CLI
    # 단독 실행에서 쓰는 것과 같은 규칙(파일명 기반)으로 채운다.
    message = {
        "caseId": f"case-{audio_path.stem}",
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
            # transcribe.py와 같은 문자열이어야 한다. 실제로 쓴 장치(used_device)를
            # 여기 덧붙이면 화면의 전송 포맷이 hub가 받는 것과 달라지므로, 장치는
            # 진행 로그에만 남긴다.
            "stt": f"faster-whisper-{stt_model}",
            "llm": llm_model if do_summarize else None,
        },
    }

    return {
        "call_summary_message": message,
        "patient_brief": brief,
        "text_postprocess": (
            {
                "corrections": [asdict(c) for c in post.corrections],
                "correction_notice": post.correction_notice,
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
    if result["text_postprocess"] and result["text_postprocess"]["correction_notice"]:
        print("\n" + result["text_postprocess"]["correction_notice"])

    if args.out:
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
