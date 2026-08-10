import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from faster_whisper import WhisperModel

from filtering import MedicalRelevanceFilter
from schema import CallSummaryMessage, ModelUsed, Summary, Transcript, TranscriptTurn
from summarizer import StructuringError, structure_call_summary

# feature/hub의 voice 요약 수신 엔드포인트. dashboard로는 직접 보내지 않고
# 이 브랜치를 거쳐 전달된다 (CLAUDE.md "데이터 포맷 및 흐름" 참고).
HUB_VOICE_SUMMARY_URL = os.environ.get("HUB_VOICE_SUMMARY_URL", "http://127.0.0.1:5001/voice/summary")

# 화자 분리(diarization)는 아직 구현되어 있지 않다. 실제 화자 분리가 붙기 전까지는
# 모든 발화 턴에 동일한 placeholder를 채운다 (README "알려진 제약사항" 참고).
UNDIARIZED_SPEAKER_LABEL = "미분리"

# Whisper가 응급이송 통화에서 자주 놓치거나 오인식하는 의료 용어를 initial_prompt로
# 미리 흘려준다. Whisper의 initial_prompt는 문맥 힌트로만 작용해 강제 디코딩은
# 아니지만, 등장 어휘의 사전 확률을 해당 도메인 쪽으로 기울여준다 (예: "심정지가
# 왔었습니다" -> "심정도 너무 왔었습니다" 같은 오인식이 실제로 관찰됨, README
# "알려진 한계" 참고). 문장 형태로 주면 실제 통화체 억양/어순 학습에도 더 잘
# 맞는다는 whisper 커뮤니티 권장을 따라 단어 나열이 아닌 짧은 문장들로 구성했다.
STT_INITIAL_PROMPT = (
    "환자는 의식이 저하되어 있습니다. 호흡 곤란을 호소하고 있습니다. "
    "혈압과 맥박, 산소포화도를 측정했습니다. 심정지 상태로 심폐소생술을 시행 중입니다. "
    "출혈이 지속되고 있어 압박 지혈 중입니다. 교통사고로 흉부에 충격을 입었습니다. "
    "낙상으로 인한 골절이 의심됩니다. 구급대원입니다. 흉부외과, 신경외과, 정형외과, "
    "응급의학과로 이송하겠습니다."
)

# beam_size가 클수록 후보 시퀀스를 더 넓게 탐색해 저확률(도메인 특화) 토큰을
# 놓칠 확률이 줄어들지만, 그만큼 느려진다 (macOS는 CPU 전용이라 체감 영향이 큼).
# faster-whisper 기본값(5)을 그대로 명시적 상수로 빼서, 나중에 실제 통화 녹음으로
# 정확도/속도를 비교해가며 튜닝할 지점을 코드에서 바로 보이게 했다.
DEFAULT_BEAM_SIZE = 5

# 원본 음성/노이즈 합성 음성/STT 원문/구조화 결과를 용도별 폴더로 분리한다. 전부
# .gitignore의 data/ 규칙에 걸려 저장소에는 올라가지 않는다 (README "폴더 구조" 참고).
# origin_data·origin_noise_data 둘 다 입력 소스일 뿐이라, 어느 쪽 파일을 넣어도
# 결과는 항상 origin_text/summary_text로 모인다 (아래 --audio 인자는 경로만 받음).
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_VOICE_DIR = BASE_DIR / "data" / "voice_data"
ORIGIN_DATA_DIR = DATA_VOICE_DIR / "origin_data"
ORIGIN_NOISE_DATA_DIR = DATA_VOICE_DIR / "origin_noise_data"
ORIGIN_TEXT_DIR = DATA_VOICE_DIR / "origin_text"
SUMMARY_TEXT_DIR = DATA_VOICE_DIR / "summary_text"


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


def transcribe(
    audio_path: Path,
    model_size: str,
    language: str,
    device: str,
    compute_type: str,
    do_summarize: bool,
    llm_model: str,
    beam_size: int = DEFAULT_BEAM_SIZE,
) -> None:
    print(f"모델 로딩 중... ({model_size}, device={device}, compute_type={compute_type})")
    load_start = time.perf_counter()
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    load_elapsed = time.perf_counter() - load_start
    print(f"모델 로딩 완료 ({load_elapsed:.2f}초)")

    print(f"변환 중: {audio_path.name} (beam_size={beam_size})")
    transcribe_start = time.perf_counter()
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        beam_size=beam_size,
        initial_prompt=STT_INITIAL_PROMPT,
    )

    turn_texts: list[str] = []
    turn_offsets: list[float] = []
    for segment in segments:
        ts = f"[{format_timestamp(segment.start)} -> {format_timestamp(segment.end)}]"
        text = segment.text.strip()
        print(f"{ts} {text}")
        turn_texts.append(text)
        turn_offsets.append(segment.start)
    transcribe_elapsed = time.perf_counter() - transcribe_start

    full_text = " ".join(turn_texts)
    ORIGIN_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ORIGIN_TEXT_DIR / (audio_path.stem + ".txt")
    out_path.write_text(full_text, encoding="utf-8")
    print(f"\n텍스트 파일 저장: {out_path}")
    print(f"변환 소요 시간: {transcribe_elapsed:.2f}초 (모델 로딩 제외)")

    if not do_summarize:
        return

    build_and_emit_call_summary(
        full_text=full_text,
        turn_texts=turn_texts,
        turn_offsets=turn_offsets,
        duration_sec=info.duration,
        language=info.language or language,
        model_size=model_size,
        llm_model=llm_model,
        audio_path=audio_path,
    )


def build_and_emit_call_summary(
    full_text: str,
    turn_texts: list[str],
    turn_offsets: list[float],
    duration_sec: float,
    language: str,
    model_size: str,
    llm_model: str,
    audio_path: Path,
) -> None:
    """실시간 음성 필터링(의료 관련 문장 분류) -> SBAR 구조화 -> JSON 조립까지 수행한다.

    실제 통화 시작 시각 메타데이터가 없으므로(사전 녹음 파일 처리), 처리 시작
    시점에서 오디오 길이만큼 거슬러 올라간 시각을 통화 시작 시각으로 근사한다.
    실시간 스트림 연동 시에는 실제 통화 시작 시각으로 교체하면 된다.
    """
    call_start = datetime.now(timezone.utc) - timedelta(seconds=duration_sec)

    print("\n실시간 음성 필터링: 의료 관련 문장 분류 중...")
    filter_start = time.perf_counter()
    relevance_filter = MedicalRelevanceFilter()
    classified = relevance_filter.classify_turns(turn_texts)
    filter_elapsed = time.perf_counter() - filter_start
    print(f"분류 완료 ({filter_elapsed:.2f}초, threshold={relevance_filter.threshold})")

    turns: list[TranscriptTurn] = []
    filtered_parts: list[str] = []
    for text, offset, result in zip(turn_texts, turn_offsets, classified):
        turn_time = (call_start + timedelta(seconds=offset)).strftime("%H:%M:%S")
        print(f"  [{result.score:.3f}] {'유지' if result.is_relevant else '제외'}  {text}")
        turns.append(
            TranscriptTurn(
                speaker=UNDIARIZED_SPEAKER_LABEL,
                timestamp=turn_time,
                text=text,
                excludedFromSummary=None if result.is_relevant else True,
            )
        )
        if result.is_relevant:
            filtered_parts.append(text)

    filtered_text = " ".join(filtered_parts)

    if not filtered_text.strip():
        print(
            "\n경고: 의료 관련으로 분류된 문장이 없습니다. 전체 텍스트를 대상으로 구조화를 시도합니다.",
            file=sys.stderr,
        )
        filtered_text = full_text

    print(f"\nSBAR 구조화 중... ({llm_model})")
    structure_start = time.perf_counter()
    try:
        structured = structure_call_summary(filtered_text, llm_model)
    except StructuringError as e:
        print(f"\n구조화 실패: {e}", file=sys.stderr)
        return
    structure_elapsed = time.perf_counter() - structure_start
    print(f"구조화 완료 ({structure_elapsed:.2f}초)")

    message = CallSummaryMessage(
        transcript=Transcript(
            raw_text=full_text,
            filtered_text=filtered_text,
            language=language,
            timestamp=call_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            duration_sec=round(duration_sec, 1),
            turns=turns,
        ),
        summary=Summary(**structured),
        model_used=ModelUsed(stt=f"faster-whisper-{model_size}", llm=llm_model),
    )

    output_json = message.model_dump_json(exclude_none=True, indent=2)

    SUMMARY_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = SUMMARY_TEXT_DIR / (audio_path.stem + "_call_summary.json")
    summary_path.write_text(output_json, encoding="utf-8")

    print("\n=== feature/hub로 전송될 JSON ===")
    print(output_json)
    print(f"\nJSON 파일 저장: {summary_path}")

    send_to_hub(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="로컬 음성 파일을 텍스트로 변환하고, 선택적으로 요약합니다.")
    parser.add_argument("audio", type=Path, help="변환할 오디오 파일 경로")
    parser.add_argument("--model", default="medium", help="Whisper 모델 크기 (기본: medium)")
    parser.add_argument("--language", default="ko", help="언어 코드 (기본: ko)")
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cuda", "cpu"],
        help="연산 장치 (기본: auto - GPU가 있으면 자동으로 사용, 없으면 CPU. Mac에서는 항상 cpu로 동작)",
    )
    parser.add_argument(
        "--compute-type",
        default="auto",
        help="연산 정밀도 (기본: auto - 장치에 맞는 값을 자동 선택. 예: float16, int8, float32)",
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="실시간 음성 필터링 + SBAR 구조화를 수행해 feature/dashboard 전달용 JSON을 생성",
    )
    parser.add_argument("--llm-model", default="qwen3:14b", help="구조화에 사용할 Ollama 모델 (기본: qwen3:14b)")
    parser.add_argument(
        "--beam-size",
        type=int,
        default=DEFAULT_BEAM_SIZE,
        help=f"Whisper 빔 서치 크기 (기본: {DEFAULT_BEAM_SIZE}. 클수록 정확도↑ 속도↓)",
    )
    args = parser.parse_args()

    if not args.audio.exists():
        print(f"파일을 찾을 수 없습니다: {args.audio}", file=sys.stderr)
        sys.exit(1)

    transcribe(
        args.audio,
        args.model,
        args.language,
        args.device,
        args.compute_type,
        args.summarize,
        args.llm_model,
        args.beam_size,
    )


if __name__ == "__main__":
    main()
