"""통화 중에 마이크 버퍼를 지켜보다가 말이 끊길 때마다 그 발화만 잘라 바로 인식한다.

C:\\Dev\\HMM\\simulation\\app.py의 무음 감지 방식을 가져왔다. 통화가 끝난 뒤 전체를 한 번에 인식하면
통화 길이의 절반가량을 기다려야 하지만(108초 통화 -> 약 61초), 통화 중에 발화 단위로 미리 인식해
두면 종료 후에는 마지막 발화 하나만 남는다. 전체 연산량은 같고, 그 연산을 통화 시간 동안 나눠 할 뿐이다.

    0.5초마다 버퍼 확인 -> 0.1초 프레임 RMS로 무음 판정 -> 말이 끊기면 그 발화만 잘라 ASR
                                                        -> 인식 결과를 구간 목록에 쌓음

무음 판정은 소리 크기만 본다. 사람 목소리와 소음을 구분하지 못하므로, 시끄러운 곳에서 발화가 안 끊기면
VOICE_SILENCE_RMS를 올리고, 말하는 중에 자꾸 끊기면 VOICE_UTTERANCE_HOLD_SEC를 늘린다.
"""

from __future__ import annotations

import os
import sys
import threading

import numpy as np

from asr import SAMPLE_RATE, AsrModel, Segment
from mic_recorder import MicRecorder

FRAME = SAMPLE_RATE // 10  # 0.1초 — 무음 판정 단위
MIN_SPEECH_SEC = 0.6  # 이보다 짧은 소리는 발화로 보지 않는다(기침·잡음)
MAX_UTTERANCE_SEC = 12.0  # 쉬지 않고 말하면 여기서 가장 조용한 지점을 찾아 끊는다
KEEP_SILENCE_SEC = 0.5  # 말이 없을 때 버퍼에 남겨 두는 길이
POLL_SEC = 0.5

#: 이보다 작은 소리(RMS)는 말이 아닌 것으로 본다
SILENCE_RMS = float(os.environ.get("VOICE_SILENCE_RMS", 0.01))
#: 이만큼 조용하면 한 발화가 끝난 것으로 보고 바로 인식한다
UTTERANCE_HOLD_SEC = float(os.environ.get("VOICE_UTTERANCE_HOLD_SEC", 0.4))


def frame_rms(audio: np.ndarray) -> np.ndarray:
    count = len(audio) // FRAME
    if count == 0:
        return np.zeros(0, dtype=np.float32)
    frames = audio[: count * FRAME].reshape(count, FRAME)
    return np.sqrt((frames**2).mean(axis=1))


def find_utterance_end(rms: np.ndarray, threshold: float, hold_frames: int) -> int | None:
    """버퍼에서 발화가 끝난 지점(샘플 위치). 끊을 곳이 없으면 None.

    말이 시작된 뒤 hold_frames 이상 조용해지면 그 발화가 끝난 것으로 본다. 쉬지 않고 말해서 버퍼가
    MAX_UTTERANCE_SEC를 넘으면 마지막 2초 중 가장 조용한 지점에서 끊는다.
    """
    speech = rms >= threshold
    if not speech.any():
        return None
    first = int(np.argmax(speech))
    last = len(speech) - 1 - int(np.argmax(speech[::-1]))
    if (last - first + 1) * FRAME < MIN_SPEECH_SEC * SAMPLE_RATE:
        return None
    trailing = len(speech) - 1 - last
    if trailing >= hold_frames:
        return min(last + 1 + hold_frames // 2, len(rms)) * FRAME
    if len(rms) * FRAME >= MAX_UTTERANCE_SEC * SAMPLE_RATE:
        tail = rms[-20:]
        return (len(rms) - len(tail) + int(np.argmin(tail)) + 1) * FRAME
    return None


class LiveTranscriber:
    """녹음기 하나를 따라가며 발화 단위로 인식한다. start()로 시작, finish()로 남은 소리까지 인식해 결과를 받는다."""

    def __init__(
        self,
        recorder: MicRecorder,
        asr_model: AsrModel,
        threshold: float = SILENCE_RMS,
        hold_sec: float = UTTERANCE_HOLD_SEC,
    ) -> None:
        self._recorder = recorder
        self._asr = asr_model
        self._threshold = threshold
        self._hold_frames = max(1, round(hold_sec * SAMPLE_RATE / FRAME))
        self._consumed = 0  # 녹음 버퍼에서 이미 인식했거나 무음으로 버린 곳까지의 샘플 위치
        self._segments: list[Segment] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def finish(self) -> list[Segment]:
        """감시를 멈추고 아직 인식하지 않은 소리까지 처리해 전체 구간 목록을 돌려준다."""
        self._stop.set()
        self._thread.join()
        self._process(final=True)
        return self._segments

    def _run(self) -> None:
        # 여기서 예외로 스레드가 죽어도 통화를 잃지 않는다 — _consumed가 멈춘 자리부터 finish()가 다시 인식한다
        try:
            while not self._stop.wait(POLL_SEC):
                self._process(final=False)
        except Exception as e:  # ASR·CUDA 쪽 예외 타입이 다양하다
            print(f"[발화 인식] 통화 중 인식 실패 — 종료 시 남은 소리를 한꺼번에 인식합니다: {e}", file=sys.stderr)

    def _process(self, final: bool) -> None:
        pending = self._recorder.samples_since(self._consumed)
        while (cut := find_utterance_end(frame_rms(pending), self._threshold, self._hold_frames)) is not None:
            self._recognize(pending[:cut])
            pending = pending[cut:]

        rms = frame_rms(pending)
        if final:
            if len(rms) and (rms >= self._threshold).any():
                self._recognize(pending)
            return

        # 말이 하나도 없는 버퍼는 끝부분만 남긴다(가만히 있는 동안 버퍼가 계속 커지지 않게)
        keep = int(KEEP_SILENCE_SEC * SAMPLE_RATE)
        if len(rms) and not (rms >= self._threshold).any() and len(pending) > keep:
            self._consumed += len(pending) - keep

    def _recognize(self, audio: np.ndarray) -> None:
        offset = self._consumed / SAMPLE_RATE
        for segment in self._asr.transcribe_audio(audio):
            self._segments.append(Segment(offset + segment.start, offset + segment.end, segment.text))
            print(f"[발화 인식] {offset + segment.start:6.1f}s  {segment.text}")
        self._consumed += len(audio)
