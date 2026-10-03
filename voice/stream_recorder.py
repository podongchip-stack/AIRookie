"""네트워크로 들어오는 통화 음성을 쌓는 녹음기(2026-10-03, 중앙 voice 모드).

구급차 대시보드(휴대폰·태블릿 브라우저)가 마이크 음성을 16kHz 모노 16비트 PCM으로 바꿔 hub로 보내고, hub가
사건(caseId)별로 이 voice에 넘긴다. MicRecorder와 같은 모양(snapshot·samples_since·save_wav·stop·sample_rate)이라
LiveTranscriber가 마이크 대신 이걸 그대로 따라가며 발화 단위로 인식한다.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from mic_recorder import SAMPLE_RATE


class StreamRecorder:
    """append()로 받은 PCM 조각을 float32 버퍼로 누적한다. 녹음 장치가 없으니 start·stop은 할 일이 없다."""

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self._accumulated = np.array([], dtype=np.float32)
        self._lock = threading.Lock()
        #: 마지막으로 음성이 들어온 시각(monotonic) — 끊긴 통화를 자동으로 끝내는 데 쓴다
        self.last_audio_at = time.monotonic()

    def append(self, pcm16: bytes) -> int:
        """16비트 리틀엔디언 모노 PCM을 덧붙인다. 홀수 바이트(잘린 샘플)는 버린다. 받은 샘플 수를 돌려준다."""
        usable = len(pcm16) - (len(pcm16) % 2)
        if usable <= 0:
            return 0
        samples = np.frombuffer(pcm16[:usable], dtype="<i2").astype(np.float32) / 32768.0
        with self._lock:
            self._accumulated = np.concatenate([self._accumulated, samples])
            self.last_audio_at = time.monotonic()
        return len(samples)

    def start(self) -> None:  # MicRecorder와 같은 모양을 맞추려고 둔다
        return None

    def snapshot(self) -> np.ndarray:
        with self._lock:
            return self._accumulated.copy()

    def samples_since(self, start: int) -> np.ndarray:
        with self._lock:
            return self._accumulated[start:].copy()

    def save_wav(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), self.snapshot(), samplerate=self.sample_rate)

    def stop(self) -> None:
        return None
