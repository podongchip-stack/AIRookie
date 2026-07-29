"""오디오 파일에 화이트 노이즈를 지정한 SNR(dB)로 섞어서 새 wav 파일로 저장한다.

STT/실시간 음성 필터링 파이프라인이 소음 환경에서도 잘 동작하는지 확인하기 위한
테스트 데이터 생성 도구다. 새 오디오 라이브러리 없이 이미 설치된 av(PyAV) +
numpy만으로 동작한다.

사용 예:
    python add_noise.py data/origin_data/원본.mp3 data/origin_data/원본_noisy10db.wav 10
"""

import argparse
from pathlib import Path

import av
import numpy as np


def load_audio_mono(path: str, target_rate: int = 16000) -> tuple[np.ndarray, int]:
    container = av.open(path)
    stream = container.streams.audio[0]
    resampler = av.AudioResampler(format="s16", layout="mono", rate=target_rate)
    samples = []
    for frame in container.decode(stream):
        for resampled in resampler.resample(frame):
            samples.append(resampled.to_ndarray())
    container.close()
    audio = np.concatenate(samples, axis=1).flatten().astype(np.float32)
    return audio, target_rate


def add_white_noise(signal: np.ndarray, snr_db: float, seed: int = 42) -> np.ndarray:
    signal_power = np.mean(signal.astype(np.float64) ** 2)
    noise = np.random.default_rng(seed).normal(0, 1, size=signal.shape)
    noise_power = np.mean(noise**2)
    target_noise_power = signal_power / (10 ** (snr_db / 10))
    noise = noise * np.sqrt(target_noise_power / noise_power)
    mixed = signal + noise
    # int16 범위 클리핑 방지
    peak = np.max(np.abs(mixed))
    if peak > 32767:
        mixed = mixed * (32767 / peak)
    return mixed.astype(np.int16)


def save_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(path), mode="w")
    stream = container.add_stream("pcm_s16le", rate=rate)
    stream.layout = "mono"
    frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
    frame.sample_rate = rate
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="오디오 파일에 화이트 노이즈를 섞어 강건성 테스트용 파일을 만든다.")
    parser.add_argument("input", type=Path, help="원본 오디오 파일 경로")
    parser.add_argument("output", type=Path, help="저장할 wav 파일 경로 (예: data/origin_data/파일명_noisy10db.wav)")
    parser.add_argument("snr_db", type=float, help="목표 SNR(dB). 낮을수록 소음이 심함 (예: 10=중간, 0=심함)")
    args = parser.parse_args()

    signal, rate = load_audio_mono(str(args.input))
    noisy = add_white_noise(signal, args.snr_db)
    save_wav(args.output, noisy, rate)
    print(f"저장 완료: {args.output} (SNR={args.snr_db}dB, {len(signal) / rate:.1f}초)")


if __name__ == "__main__":
    main()
