"""파인튜닝한 Qwen3-ASR(베이스 + LoRA 어댑터)로 통화 음성을 텍스트로 바꾼다.

C:\\Dev\\HMM\\use\\transcribe_ko.py의 인식 로직을 가져왔다. 어댑터는 AI Hub 119 신고 음성
20시간으로 학습했고, 학습 데이터가 평균 2초짜리 발화라 긴 통화를 통째로 넣지 않고 조용한 지점에서
5초 안팎으로 잘라 구간별로 인식한다(20초 단위는 문장이 통째로 빠졌고 8초 단위도 일부 누락).

가중치는 저장소에 없다. 베이스 모델은 첫 실행 때 Hugging Face 캐시(HF_HOME)로 내려받고,
어댑터(약 79MB)는 ASR_ADAPTER_DIR 폴더에 있어야 한다.
"""

from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np
import soundfile as sf
import torch
from peft import PeftModel
from scipy.signal import resample_poly
from transformers import AutoProcessor, Qwen3ASRForConditionalGeneration

BASE_MODEL_ID = "Qwen/Qwen3-ASR-1.7B-hf"
ASR_ADAPTER_DIR = Path(os.environ.get("ASR_ADAPTER_DIR", r"C:\Dev\HMM\use\adapter"))

#: model_used.stt에 싣는 이름
MODEL_NAME = "qwen3-asr-1.7b-lora"

SAMPLE_RATE = 16000
DEFAULT_CHUNK_SEC = 5.0
MAX_NEW_TOKENS = 256


@dataclass
class Segment:
    start: float
    end: float
    text: str


def pick_device(name: str) -> str:
    if name != "auto":
        return name
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def pick_dtype(device: str) -> torch.dtype:
    # 학습·검증은 CUDA + bf16으로 했다. MPS·CPU 값은 검증하지 못한 보수적 선택이다.
    return {"cuda": torch.bfloat16, "mps": torch.float16, "cpu": torch.float32}[device]


def _to_16k(audio: np.ndarray, rate: int) -> np.ndarray:
    if rate == SAMPLE_RATE:
        return audio
    g = math.gcd(rate, SAMPLE_RATE)
    return resample_poly(audio, SAMPLE_RATE // g, rate // g).astype(np.float32)


def load_audio(path: Path) -> np.ndarray:
    """오디오 파일 -> 16kHz 모노 float32.

    마이크 녹음(wav)은 soundfile로 읽는다. m4a처럼 soundfile이 못 읽는 형식은 PyAV(FFmpeg)로 푼다.
    """
    try:
        audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
        return _to_16k(audio.mean(axis=1), rate)
    except sf.LibsndfileError:
        pass

    resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
    pieces = []
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            pieces.extend(out.to_ndarray()[0] for out in resampler.resample(frame))
    pieces.extend(out.to_ndarray()[0] for out in resampler.resample(None))
    return np.concatenate(pieces).astype(np.float32)


def split_chunks(audio: np.ndarray, chunk_sec: float) -> list[tuple[int, int]]:
    """chunk_sec를 넘는 오디오는 목표 길이 근처의 가장 조용한 지점에서 자른다."""
    total = len(audio)
    max_len = int(chunk_sec * SAMPLE_RATE)
    if total <= max_len:
        return [(0, total)]

    frame = SAMPLE_RATE // 10
    search = 3 * SAMPLE_RATE
    bounds, start = [], 0
    while total - start > max_len:
        target = start + max_len
        lo, hi = max(start + frame, target - search), target
        energies = [
            (float(np.sqrt(np.mean(audio[p:p + frame] ** 2))), p)
            for p in range(lo, hi, frame)
        ]
        cut = min(energies)[1]
        bounds.append((start, cut))
        start = cut
    bounds.append((start, total))
    return bounds


class AsrModel:
    """베이스 + 어댑터를 한 번 올려두고 한 건씩 인식한다.

    GPU 하나에 모델 하나라 동시에 돌릴 이유가 없다 — 앞 통화의 마무리 인식과 다음 통화의 발화 인식이
    겹칠 수 있어 락으로 한 번에 하나만 돌린다.
    """

    def __init__(self, device: str = "auto", adapter_dir: Path = ASR_ADAPTER_DIR) -> None:
        if not adapter_dir.is_dir():
            raise FileNotFoundError(f"ASR 어댑터 폴더가 없습니다: {adapter_dir} (ASR_ADAPTER_DIR 환경변수로 지정)")
        self.device = pick_device(device)
        self.dtype = pick_dtype(self.device)
        self.processor = AutoProcessor.from_pretrained(BASE_MODEL_ID)
        model = Qwen3ASRForConditionalGeneration.from_pretrained(BASE_MODEL_ID, dtype=self.dtype)
        self.model = PeftModel.from_pretrained(model, str(adapter_dir)).to(self.device).eval()
        self._lock = threading.Lock()

    @torch.no_grad()
    def _transcribe_chunk(self, audio: np.ndarray) -> str:
        # 학습 때와 같은 형식: assistant 턴을 "language Korean<asr_text>"로 미리 채워두고 이어서 생성
        conv = [
            {"role": "user", "content": [{"type": "audio", "audio": audio}]},
            {"role": "assistant", "content": [{"type": "text", "text": "language Korean<asr_text>"}]},
        ]
        inputs = self.processor.apply_chat_template(
            [conv], tokenize=True, return_dict=True, continue_final_message=True,
        ).to(self.device, self.dtype)
        ids = self.model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS)
        return self.processor.decode(ids[:, inputs["input_ids"].shape[1]:], return_format="transcription_only")[0].strip()

    def transcribe_audio(self, audio: np.ndarray, chunk_sec: float = DEFAULT_CHUNK_SEC) -> list[Segment]:
        """16kHz 모노 배열 -> 구간 목록(시각은 배열 시작 기준 초). 빈 구간은 버린다."""
        segments = []
        with self._lock:
            for start, end in split_chunks(audio, chunk_sec):
                text = self._transcribe_chunk(audio[start:end])
                if text:
                    segments.append(Segment(start / SAMPLE_RATE, end / SAMPLE_RATE, text))
        return segments

    def transcribe_file(self, path: Path) -> tuple[list[Segment], float, float]:
        """녹음된 파일 통째로 -> (구간 목록, 오디오 길이 초, 인식 소요 초)."""
        audio = load_audio(path)
        started = time.perf_counter()
        segments = self.transcribe_audio(audio)
        return segments, len(audio) / SAMPLE_RATE, time.perf_counter() - started
