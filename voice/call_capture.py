"""통화 시작~종료를 마이크 녹음으로 흉내내고, 종료 즉시 배치 파이프라인을 돌리는 진입점.

실제 취지: "전화가 시작되고 끝나면, 그 통화 전체가 하나의 음성 파일이 되고,
그 파일이 STT 파이프라인에 들어간다." live_transcribe.py처럼 통화 중 N초마다
끊어 재변환하지 않는다 — 통화 중에는 그냥 녹음만 하고, Ctrl+C(통화 종료)를
누른 시점에만 전체 오디오를 한 번 transcribe.py의 배치 파이프라인(STT -> 필터링
-> SBAR 구조화)에 통과시킨다. STT/필터링/구조화 로직은 새로 만들지 않고
transcribe.py의 transcribe()를 그대로 재사용한다.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from mic_recorder import MicRecorder
from transcribe import DEFAULT_BEAM_SIZE, ORIGIN_DATA_DIR, transcribe


def capture_call(
    session: str,
    model_size: str,
    language: str,
    device: str,
    compute_type: str,
    llm_model: str,
    beam_size: int = DEFAULT_BEAM_SIZE,
    case_id: str | None = None,
) -> None:
    audio_path = ORIGIN_DATA_DIR / f"{session}.wav"

    recorder = MicRecorder()
    try:
        recorder.start()
    except RuntimeError as e:
        print(f"{e}", file=sys.stderr)
        sys.exit(1)

    print("통화 시작. 마이크에 대고 말하세요.")
    print("통화가 끝나면 Ctrl+C를 누르세요 (통화 종료 신호).")

    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n통화 종료 (Ctrl+C)")
    finally:
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        recorder.save_wav(audio_path)
        recorder.stop()
        print(f"녹음 저장: {audio_path}")

    print("\n=== 파이프라인 시작: STT -> SBAR 구조화 ===")
    transcribe(
        audio_path=audio_path,
        model_size=model_size,
        language=language,
        device=device,
        compute_type=compute_type,
        do_summarize=True,
        llm_model=llm_model,
        beam_size=beam_size,
        case_id=case_id,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="마이크로 통화를 녹음하고(Ctrl+C=통화 종료), 종료 즉시 STT+구조화 파이프라인을 자동 실행합니다."
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="세션(파일) 이름. 지정하지 않으면 실행 시각으로 자동 생성 (예: 2026_0805_1600)",
    )
    parser.add_argument("--model", default="medium", help="Whisper 모델 크기 (기본: medium)")
    parser.add_argument("--language", default="ko", help="언어 코드 (기본: ko)")
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cuda", "cpu"],
        help="연산 장치 (기본: auto)",
    )
    parser.add_argument("--compute-type", default="auto", help="연산 정밀도 (기본: auto)")
    parser.add_argument("--llm-model", default="qwen3:14b", help="구조화에 사용할 Ollama 모델 (기본: qwen3:14b)")
    parser.add_argument(
        "--beam-size",
        type=int,
        default=DEFAULT_BEAM_SIZE,
        help=f"Whisper 빔 서치 크기 (기본: {DEFAULT_BEAM_SIZE}. 클수록 정확도↑ 속도↓)",
    )
    parser.add_argument(
        "--case-id",
        type=str,
        default=None,
        help="hub에 보낼 caseId. 지정하지 않으면 세션 이름 기반으로 자동 생성",
    )
    args = parser.parse_args()

    session = args.session or datetime.now().strftime("%Y_%m%d_%H%M")
    if args.session is None:
        print(f"--session이 지정되지 않아 자동 생성된 세션 이름을 사용합니다: {session}")

    capture_call(
        session=session,
        model_size=args.model,
        language=args.language,
        device=args.device,
        compute_type=args.compute_type,
        llm_model=args.llm_model,
        beam_size=args.beam_size,
        case_id=args.case_id,
    )


if __name__ == "__main__":
    main()
