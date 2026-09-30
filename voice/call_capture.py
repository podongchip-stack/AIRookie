"""통화 시작~종료를 마이크 녹음으로 흉내내는 CLI. app.py의 흐름을 HTTP 대신 Ctrl+C로 트리거한다.

통화 중에는 live_transcriber.py가 말이 끊길 때마다 그 발화를 바로 인식해 화면에 찍고,
Ctrl+C(통화 종료)를 누르면 남은 발화만 인식한 뒤 구조화 -> hub 전송까지 이어서 실행한다.
인식·구조화 로직은 새로 만들지 않고 app.py와 같은 모듈을 그대로 쓴다.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from live_transcriber import LiveTranscriber
from mic_recorder import MicRecorder
from transcribe import ORIGIN_DATA_DIR, emit_call_summary, load_models


def capture_call(session: str, device: str, case_id: str | None = None) -> None:
    asr_model, extractor = load_models(device)

    recorder = MicRecorder()
    try:
        recorder.start()
    except RuntimeError as e:
        print(f"{e}", file=sys.stderr)
        sys.exit(1)
    live = LiveTranscriber(recorder, asr_model)
    live.start()

    print("\n통화 시작. 마이크에 대고 말하세요 — 말이 끊길 때마다 인식 결과가 찍힙니다.")
    print("통화가 끝나면 Ctrl+C를 누르세요 (통화 종료 신호).")

    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n통화 종료 (Ctrl+C)")
    finally:
        audio_path = ORIGIN_DATA_DIR / f"{session}.wav"
        recorder.save_wav(audio_path)
        recorder.stop()
        print(f"녹음 저장: {audio_path}")

    duration_sec = len(recorder.snapshot()) / recorder.sample_rate
    print("\n=== 남은 발화 인식 -> 구조화 ===")
    segments = live.finish()
    emit_call_summary(segments, duration_sec, session, extractor, case_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="마이크로 통화를 녹음하며 발화 단위로 인식하고, Ctrl+C(통화 종료) 시 구조화해 hub로 보냅니다."
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="세션(파일) 이름. 지정하지 않으면 실행 시각으로 자동 생성 (예: 2026_0805_1600)",
    )
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cuda", "mps", "cpu"],
        help="연산 장치 (기본: auto)",
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

    capture_call(session=session, device=args.device, case_id=args.case_id)


if __name__ == "__main__":
    main()
