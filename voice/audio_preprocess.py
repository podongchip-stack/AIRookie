"""Whisper STT 입력 전 오디오 신호를 정리하는 전처리 유틸리티.

의료 용어(산소포화도, 호흡곤란 등)가 작은 목소리나 배경 소음에 묻혀 STT가
뭉개는 문제를 완화하기 위해, STT 호출 직전에 신호 자체를 다듬는다. 모델
교체나 파인튜닝 없이 적용 가능한 가장 저렴한 개선이며, 근본 해결(파인튜닝)
전 단계의 보조 수단이다.

각 함수는 float32 numpy 배열(모노, 임의 샘플레이트)을 받아 같은 형태로
반환한다 - transcribe.py/live_transcribe.py의 model.transcribe() 호출부
바로 앞에 끼워 넣는 방식으로 쓴다.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt, stft, istft


def normalize_audio(audio: np.ndarray, target_peak: float = 0.95) -> np.ndarray:
    """최대 진폭을 target_peak으로 맞춘다 (너무 작거나 큰 목소리 표준화)."""
    max_val = np.max(np.abs(audio))
    if max_val < 1e-8:
        return audio
    return (audio * (target_peak / max_val)).astype(np.float32)


def boost_high_freq(audio: np.ndarray, sample_rate: int, cutoff_hz: float = 2000.0, gain: float = 1.4) -> np.ndarray:
    """cutoff_hz 이상 고주파 대역을 gain배 증폭한다 (자음/의료 용어 명료도 개선)."""
    sos = butter(4, cutoff_hz, btype="highpass", fs=sample_rate, output="sos")
    high_band = sosfilt(sos, audio)
    boosted = audio + high_band * (gain - 1.0)
    # 증폭으로 인한 클리핑 방지
    peak = np.max(np.abs(boosted))
    if peak > 1.0:
        boosted = boosted / peak
    return boosted.astype(np.float32)


def reduce_noise(audio: np.ndarray, sample_rate: int, noise_floor_db: float = 10.0) -> np.ndarray:
    """스펙트럼 게이팅으로 배경 소음(에어컨, 차 소음 등)을 억제한다.

    전체 신호의 평균 에너지보다 noise_floor_db만큼 낮은 주파수 성분을
    소음으로 간주해 감쇠시킨다. 조용한 배경 소음 제거가 목적이며, 실제 발화
    구간은 평균보다 에너지가 높아 거의 영향받지 않는다.
    """
    if len(audio) < 256:
        return audio

    _, _, Zxx = stft(audio, fs=sample_rate, nperseg=256)
    magnitude = np.abs(Zxx)
    magnitude_db = 20 * np.log10(magnitude + 1e-8)

    threshold_db = magnitude_db.mean() - noise_floor_db
    mask = magnitude_db > threshold_db

    Zxx_clean = Zxx * mask
    _, audio_clean = istft(Zxx_clean, fs=sample_rate, nperseg=256)

    # istft가 원본과 길이가 살짝 다를 수 있으므로 맞춰준다
    if len(audio_clean) < len(audio):
        audio_clean = np.pad(audio_clean, (0, len(audio) - len(audio_clean)))
    else:
        audio_clean = audio_clean[: len(audio)]

    return audio_clean.astype(np.float32)


def preprocess_for_stt(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """STT 직전 표준 전처리 파이프라인: 소음 제거 -> 정규화 -> 고주파 강조."""
    audio = reduce_noise(audio, sample_rate)
    audio = normalize_audio(audio)
    audio = boost_high_freq(audio, sample_rate)
    return audio
