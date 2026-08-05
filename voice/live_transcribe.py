"""마이크를 계속 녹음하면서 N초마다 누적 버퍼 전체를 재변환하는 라이브 오케스트레이터.

Whisper는 진짜 스트리밍 STT가 아니라 완결된 오디오 전체를 한 번에 처리하는
배치 API다(faster_whisper.WhisperModel.transcribe()). 그래서 "라이브"는 이
스크립트에서 다음을 의미한다: 마이크를 백그라운드에서 계속 녹음하면서,
stt_interval_sec초마다 그 시점까지 누적된 오디오 전체를 다시 whisper에
통째로 넣어 재변환(re-transcribe)하고, 새로 나타난 세그먼트만 출력한다.

사용 예:
    python live_transcribe.py --session live_test1 --model base --stt-interval 5
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from faster_whisper import WhisperModel

from audio_preprocess import preprocess_for_stt
from filtering import MedicalRelevanceFilter
from mic_recorder import MicRecorder
from transcribe import build_and_emit_call_summary, format_timestamp

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_VOICE_DIR = BASE_DIR / "data" / "voice_data"
LIVE_AUDIO_DIR = DATA_VOICE_DIR / "live_audio"
LIVE_TEXT_DIR = DATA_VOICE_DIR / "live_text"


def live_transcribe(
    session: str,
    model_size: str = "base",
    language: str = "ko",
    device: str = "auto",
    compute_type: str = "auto",
    stt_interval_sec: int = 5,
    sbar_interval_sec: int = 20,
    llm_model: str = "qwen3:14b",
) -> None:
    print(f"모델 로딩 중... ({model_size}, device={device}, compute_type={compute_type})")
    load_start = time.perf_counter()
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except RuntimeError as e:
        print(f"Whisper 모델 로딩 실패: {e}", file=sys.stderr)
        print("GPU 메모리를 확인하세요.", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"모델 다운로드 실패: {e}", file=sys.stderr)
        print("네트워크와 디스크 공간을 확인하세요.", file=sys.stderr)
        sys.exit(1)
    load_elapsed = time.perf_counter() - load_start
    print(f"모델 로딩 완료 ({load_elapsed:.2f}초)")

    recorder = MicRecorder()
    try:
        recorder.start()
    except RuntimeError as e:
        print(f"{e}", file=sys.stderr)
        sys.exit(1)

    # 임베딩 모델 로딩 비용이 크므로 루프 진입 전 1회만 생성한다.
    relevance_filter = MedicalRelevanceFilter()

    # 마지막으로 출력한 세그먼트의 끝 시각. 재변환할 때마다 이 값보다 뒤에
    # 끝나는 세그먼트만 새 것으로 취급해 중복 출력을 막는다.
    printed_until = 0.0
    all_turn_texts: list[str] = []
    all_turn_offsets: list[float] = []
    out_path = LIVE_TEXT_DIR / f"{session}.txt"
    audio_out_path = LIVE_AUDIO_DIR / f"{session}.wav"

    print(f"\n🎤 라이브 재변환 시작 (주기: {stt_interval_sec}초)")
    print("말하세요... Ctrl+C로 중지")

    buffer_elapsed = 0.0
    try:
        iteration = 0
        while True:
            time.sleep(stt_interval_sec)
            iteration += 1

            buffer = recorder.snapshot()
            if buffer.shape[0] == 0:
                continue

            buffer_elapsed = buffer.shape[0] / recorder.sample_rate
            print(f"\n[{iteration}차] 재변환 중... 누적 {buffer_elapsed:.1f}초")

            transcribe_start = time.perf_counter()
            clean_audio = preprocess_for_stt(buffer.flatten(), recorder.sample_rate)
            segments, info = model.transcribe(
                clean_audio,
                language=language,
                vad_filter=True,
            )
            transcribe_elapsed = time.perf_counter() - transcribe_start

            new_count = 0
            for seg in segments:
                if seg.end <= printed_until:
                    continue
                ts = format_timestamp(seg.start)
                text = seg.text.strip()
                print(f"[{ts}] {text}")
                all_turn_texts.append(text)
                all_turn_offsets.append(seg.start)
                printed_until = seg.end
                new_count += 1

            if new_count == 0:
                print("(새 세그먼트 없음)")
            else:
                # 턴 개수가 적어 매 사이클 전체 재분류해도 비용이 낮다
                # (STT 재변환과 달리 증분 처리를 따로 구현할 필요가 없음).
                classified = relevance_filter.classify_turns(all_turn_texts)
                for result in classified[-new_count:]:
                    verdict = "유지" if result.is_relevant else "제외"
                    print(f"  [{result.score:.3f}] {verdict}  {result.text}")

            if all_turn_texts:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(" ".join(all_turn_texts), encoding="utf-8")

            print(f"(재변환: {transcribe_elapsed:.2f}초, 누적 텍스트: {out_path})")

            # SBAR 구조화는 LLM 호출 비용이 크므로 STT/필터링보다 긴 주기로만 실행한다.
            elapsed_since_start = iteration * stt_interval_sec
            if all_turn_texts and elapsed_since_start % sbar_interval_sec == 0:
                print(f"\n[SBAR 생성 중... ({elapsed_since_start}초 경과)]")
                build_and_emit_call_summary(
                    full_text=" ".join(all_turn_texts),
                    turn_texts=all_turn_texts,
                    turn_offsets=all_turn_offsets,
                    duration_sec=buffer_elapsed,
                    language=info.language or language,
                    model_size=model_size,
                    llm_model=llm_model,
                    audio_path=audio_out_path,
                )

    except KeyboardInterrupt:
        print("\n\n🛑 녹음 중지 (Ctrl+C)")

    finally:
        # 루프는 stt_interval_sec마다만 재변환하므로, 마지막 재변환 이후
        # ~ 종료 시점 사이에 한 말은 아직 한 번도 STT를 거치지 않은 상태다.
        # 종료 직전 마지막 스냅샷을 한 번 더 재변환해 그 구간이 누락되지
        # 않게 한다 (없으면 오디오 파일에는 남지만 텍스트/JSON에는 빠짐).
        final_buffer = recorder.snapshot()
        final_elapsed = final_buffer.shape[0] / recorder.sample_rate if final_buffer.shape[0] else 0.0
        if final_elapsed > buffer_elapsed:
            print(f"\n[종료 전 마지막 구간 재변환 중... 누적 {final_elapsed:.1f}초]")
            clean_audio = preprocess_for_stt(final_buffer.flatten(), recorder.sample_rate)
            segments, info = model.transcribe(clean_audio, language=language, vad_filter=True)
            for seg in segments:
                if seg.end <= printed_until:
                    continue
                ts = format_timestamp(seg.start)
                text = seg.text.strip()
                print(f"[{ts}] {text}")
                all_turn_texts.append(text)
                all_turn_offsets.append(seg.start)
                printed_until = seg.end
            buffer_elapsed = final_elapsed

        # 인터벌마다 잘라 재변환했을 뿐, 실제로는 처음부터 계속 하나의
        # 버퍼에 누적 녹음해왔으므로 그 전체를 그대로 WAV 하나로 저장하면
        # 된다 — 인터벌 조각들을 따로 이어붙이는 과정이 필요 없다.
        audio_out_path.parent.mkdir(parents=True, exist_ok=True)
        recorder.save_wav(audio_out_path)
        recorder.stop()
        print(f"\n🎧 전체 녹음 오디오 저장: {audio_out_path}")

        if all_turn_texts:
            print("\n📊 세션 요약:")
            print(f"  총 시간: {buffer_elapsed:.1f}초")
            print(f"  총 턴: {len(all_turn_texts)}")
            print(f"  텍스트 파일: {out_path}")
            print(f"  내용: {out_path.read_text()[:100]}...")

            print("\n=== 최종 통화 요약 (세션 종료) ===")
            build_and_emit_call_summary(
                full_text=" ".join(all_turn_texts),
                turn_texts=all_turn_texts,
                turn_offsets=all_turn_offsets,
                duration_sec=buffer_elapsed,
                language=language,
                model_size=model_size,
                llm_model=llm_model,
                audio_path=audio_out_path,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="마이크를 계속 녹음하면서 N초마다 재변환합니다.")
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="세션 이름 (예: live_test1). 지정하지 않으면 실행 시각으로 자동 생성 (예: 2026_0801_2312)",
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
    parser.add_argument(
        "--stt-interval",
        type=int,
        default=5,
        help="STT 재변환 주기 (초, 기본: 5)",
    )
    parser.add_argument(
        "--sbar-interval",
        type=int,
        default=20,
        help="SBAR JSON 생성 주기 (초, 기본: 20 - stt-interval의 배수로 지정)",
    )
    parser.add_argument("--llm-model", default="qwen3:14b", help="구조화에 사용할 Ollama 모델 (기본: qwen3:14b)")
    args = parser.parse_args()

    session = args.session or datetime.now().strftime("%Y_%m%d_%H%M")
    if args.session is None:
        print(f"--session이 지정되지 않아 자동 생성된 세션 이름을 사용합니다: {session}")

    live_transcribe(
        session=session,
        model_size=args.model,
        language=args.language,
        device=args.device,
        compute_type=args.compute_type,
        stt_interval_sec=args.stt_interval,
        sbar_interval_sec=args.sbar_interval,
        llm_model=args.llm_model,
    )


if __name__ == "__main__":
    main()
