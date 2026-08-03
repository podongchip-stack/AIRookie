import argparse
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

# Whisper가 기대하는 샘플레이트로 고정한다. 다른 값으로 녹음하면 STT 단계에서
# 매번 리샘플링이 필요해지므로, 녹음 시점부터 16kHz로 맞춘다.
SAMPLE_RATE = 16000
# sounddevice 콜백 1회당 프레임 수. 16000Hz 기준 약 256ms 단위로 청크가 들어온다.
BLOCKSIZE = 4096

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_VOICE_DIR = BASE_DIR / "data" / "voice_data"
LIVE_AUDIO_DIR = DATA_VOICE_DIR / "live_audio"


class MicRecorder:
    """마이크 입력을 백그라운드 스레드에서 numpy 버퍼로 계속 누적하는 녹음기.

    STT/필터링과 무관하게 "녹음 자체"만 담당한다. snapshot()은 지금까지 누적된
    오디오의 복사본을 돌려주므로, 녹음이 진행 중인 동안에도 비파괴적으로 중간
    상태를 읽을 수 있다(Step 3의 라이브 재변환 루프에서 사용할 지점).
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE, blocksize: int = BLOCKSIZE) -> None:
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self._accumulated = np.array([], dtype=np.float32)
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None

    def _on_audio_block(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"⚠️ 마이크 입력 경고: {status}")
        # indata는 (frames, channels) 형태. 모노 채널만 사용한다.
        with self._lock:
            self._accumulated = np.concatenate([self._accumulated, indata[:, 0].copy()])

    def start(self) -> None:
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.blocksize,
            channels=1,
            dtype="float32",
            callback=self._on_audio_block,
        )
        self._stream.start()

    def snapshot(self) -> np.ndarray:
        """지금까지 누적된 오디오 버퍼의 복사본을 반환한다 (비파괴적)."""
        with self._lock:
            return self._accumulated.copy()

    def save_wav(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), self.snapshot(), samplerate=self.sample_rate)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


def record_fixed_seconds(duration_sec: float, out_path: Path) -> None:
    """Step 1 스모크 테스트 전용: 정확히 duration_sec초만 녹음하고 WAV로 저장한다."""
    print(f"녹음 시작 ({duration_sec:.1f}초)... 마이크에 대고 말하세요.")

    recorder = MicRecorder()
    recorder.start()
    try:
        time.sleep(duration_sec)
    finally:
        recorder.save_wav(out_path)
        recorder.stop()

    print(f"녹음 완료: {out_path} ({duration_sec:.1f}초)")


def main() -> None:
    parser = argparse.ArgumentParser(description="마이크로 지정한 시간만큼 녹음해 WAV로 저장합니다 (스모크 테스트용).")
    parser.add_argument("--seconds", type=float, default=5.0, help="녹음 시간(초) (기본: 5.0)")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="저장할 WAV 경로 (기본: data/live_audio/<실행 시각>.wav, 예: data/live_audio/2026_0801_2312.wav)",
    )
    args = parser.parse_args()

    out_path = args.out or LIVE_AUDIO_DIR / f"{datetime.now().strftime('%Y_%m%d_%H%M')}.wav"
    record_fixed_seconds(args.seconds, out_path)


if __name__ == "__main__":
    main()
