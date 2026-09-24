"""통화 음성 -> STT(Qwen3-ASR) -> 구조화(HMM) -> feature/hub 전달용 JSON. 파이프라인 본체이자 배치 CLI.

    ASR   Qwen3-ASR-1.7B + LoRA (asr.py)          음성 -> 발화 구간 텍스트   (AI 처리)
    HMM   KLUE RoBERTa-large 다중과제 (hmm/)       텍스트 -> 필드별 점수      (AI 처리)
          + 규칙 조립기 (hmm/assemble.py)          -> summary 6필드            (규칙 기반)

app.py·call_capture.py는 통화 중에 발화 단위로 미리 인식해(live_transcriber.py) 구간 목록을 넘기고,
이 파일의 CLI는 이미 녹음된 파일을 통째로 인식한다. 이후 과정(emit_call_summary)은 같다.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import asr
import hmm
from asr import AsrModel, Segment
from hmm import HmmExtractor
from schema import CallSummaryMessage, ModelUsed, Summary, Transcript, TranscriptTurn

# feature/hub의 voice 요약 수신 엔드포인트. dashboard로는 직접 보내지 않고
# 이 브랜치를 거쳐 전달된다 (CLAUDE.md "데이터 포맷 및 흐름" 참고).
HUB_VOICE_SUMMARY_URL = os.environ.get("HUB_VOICE_SUMMARY_URL", "http://127.0.0.1:5001/voice/summary")

# 화자 분리(diarization)는 아직 구현되어 있지 않다. 실제 화자 분리가 붙기 전까지는
# 모든 발화 턴에 동일한 placeholder를 채운다 (README "알려진 제약사항" 참고).
UNDIARIZED_SPEAKER_LABEL = "미분리"

# ASR 어댑터는 한국어 프롬프트("language Korean")로 학습·추론한다
LANGUAGE = "ko"

# 원본 음성/STT 원문/구조화 결과를 용도별 폴더로 분리한다. 전부 .gitignore의
# data/ 규칙에 걸려 저장소에는 올라가지 않는다 (README "폴더 구조" 참고).
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_VOICE_DIR = BASE_DIR / "data" / "voice_data"
ORIGIN_DATA_DIR = DATA_VOICE_DIR / "origin_data"
ORIGIN_TEXT_DIR = DATA_VOICE_DIR / "origin_text"
SUMMARY_TEXT_DIR = DATA_VOICE_DIR / "summary_text"


def load_models(device: str) -> tuple[AsrModel, HmmExtractor]:
    """두 모델을 한 번 올린다(합쳐서 약 20초). 통화마다 올리면 그만큼 늦어지므로 프로세스 시작 시 1회만 부른다."""
    print(f"모델 로딩 중... (ASR {asr.MODEL_NAME} + 구조화 {hmm.MODEL_NAME}, device={device})")
    started = time.perf_counter()
    asr_model = AsrModel(device)
    extractor = HmmExtractor(device)
    print(f"모델 로딩 완료 ({time.perf_counter() - started:.1f}초, ASR device={asr_model.device})")
    return asr_model, extractor


def send_to_hub(message: CallSummaryMessage) -> None:
    """통화 요약을 feature/hub로 전송한다. hub는 summary/source만 사용하므로
    transcript 등 나머지 필드가 섞여 있어도 그대로 보낸다 (schema.py 참고).
    hub가 아직 안 떠 있어도 배치 파이프라인 자체는 계속 진행되어야 하므로,
    실패해도 예외를 올리지 않고 콘솔에만 알린다.
    """
    try:
        response = requests.post(
            HUB_VOICE_SUMMARY_URL,
            json=message.model_dump(exclude_none=True),
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"\n[통신] feature/hub 전송 실패 ({HUB_VOICE_SUMMARY_URL}): {e}", file=sys.stderr)
        return
    print(f"\n[통신] feature/hub 전송 완료 ({HUB_VOICE_SUMMARY_URL}) — 매칭 결과 {len(response.json().get('hospitals', []))}건 수신")


def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def emit_call_summary(
    segments: list[Segment],
    duration_sec: float,
    name: str,
    extractor: HmmExtractor,
    case_id: str | None = None,
    do_summarize: bool = True,
) -> None:
    """발화 구간 -> STT 원문 저장 -> HMM 구조화 -> JSON 조립·저장 -> hub 전송.

    발화는 줄바꿈으로 이어 붙인다. HMM은 "줄바꿈 = 화자 전환"인 통화 텍스트로 학습했는데, 여기 줄바꿈은
    발화(무음) 경계라 완전히 같은 형태는 아니다 — 화자 분리가 붙으면 그 경계로 바꿀 자리다.

    오인식 교정 단계는 없다. filtered_text(=구조화에 실제로 들어간 입력)는 raw_text와 같다 — 필드는
    hub·dashboard와의 계약이라 남긴다. 원본 보존 원칙대로 raw_text/turns에 인식 결과 전체가 남는다.

    실제 통화 시작 시각 메타데이터가 없으므로, 처리 시점에서 오디오 길이만큼 거슬러
    올라간 시각을 통화 시작 시각으로 근사한다.
    """
    full_text = "\n".join(segment.text for segment in segments)
    ORIGIN_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    text_path = ORIGIN_TEXT_DIR / f"{name}.txt"
    text_path.write_text(full_text, encoding="utf-8")
    print(f"\n텍스트 파일 저장: {text_path}")

    if not do_summarize:
        return
    if not full_text:
        print("\n인식된 발화가 없어 구조화·전송을 건너뜁니다.", file=sys.stderr)
        return

    summary, extract_elapsed = extractor.extract(full_text)
    print(f"구조화 완료 ({extract_elapsed:.2f}초)")

    call_start = datetime.now(timezone.utc) - timedelta(seconds=duration_sec)
    # voice/app.py(실제 파이프라인)는 hub가 중계한 caseId를 그대로 넘긴다.
    # CLI 단독 실행에는 caseId 개념이 없어 None이 들어오는데,
    # hub의 스키마는 caseId를 필수로 요구하므로 파일명 기반으로 만들어 채운다.
    resolved_case_id = case_id or f"case-{name}"

    message = CallSummaryMessage(
        caseId=resolved_case_id,
        transcript=Transcript(
            raw_text=full_text,
            filtered_text=full_text,
            language=LANGUAGE,
            timestamp=call_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            duration_sec=round(duration_sec, 1),
            turns=[
                TranscriptTurn(
                    speaker=UNDIARIZED_SPEAKER_LABEL,
                    timestamp=(call_start + timedelta(seconds=segment.start)).strftime("%H:%M:%S"),
                    text=segment.text,
                )
                for segment in segments
            ],
        ),
        summary=Summary(**summary),
        model_used=ModelUsed(stt=asr.MODEL_NAME, llm=hmm.MODEL_NAME),
    )

    output_json = message.model_dump_json(exclude_none=True, indent=2)
    SUMMARY_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = SUMMARY_TEXT_DIR / f"{name}_call_summary.json"
    summary_path.write_text(output_json, encoding="utf-8")

    print("\n=== feature/hub로 전송될 JSON ===")
    print(output_json)
    print(f"\nJSON 파일 저장: {summary_path}")

    send_to_hub(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="녹음된 통화 파일을 인식하고, 선택적으로 구조화해 hub로 보냅니다.")
    parser.add_argument("audio", type=Path, help="변환할 오디오 파일 경로 (wav·m4a 등)")
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cuda", "mps", "cpu"],
        help="연산 장치 (기본: auto - GPU가 있으면 자동으로 사용, 없으면 CPU)",
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="구조화까지 수행해 feature/hub 전달용 JSON을 생성·전송",
    )
    parser.add_argument(
        "--case-id",
        type=str,
        default=None,
        help="hub에 보낼 caseId. 지정하지 않으면 오디오 파일명 기반으로 자동 생성",
    )
    args = parser.parse_args()

    if not args.audio.exists():
        print(f"파일을 찾을 수 없습니다: {args.audio}", file=sys.stderr)
        sys.exit(1)

    asr_model, extractor = load_models(args.device)
    print(f"변환 중: {args.audio.name}")
    segments, duration_sec, elapsed = asr_model.transcribe_file(args.audio)
    for segment in segments:
        print(f"[{format_timestamp(segment.start)} -> {format_timestamp(segment.end)}] {segment.text}")
    print(f"변환 소요 시간: {elapsed:.1f}초 (오디오 {duration_sec:.1f}초, 모델 로딩 제외)")

    emit_call_summary(segments, duration_sec, args.audio.stem, extractor, args.case_id, args.summarize)


if __name__ == "__main__":
    main()
