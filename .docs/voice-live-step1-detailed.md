# Step 1 상세 가이드: 마이크 녹음 모듈 (`mic_recorder.py`)

## 📚 개념 설명

### 1. sounddevice 라이브러리

`sounddevice`는 **Python에서 오디오를 녹음하고 재생하기 위한 라이브러리**다.

```
macOS의 오디오 하드웨어 (마이크)
    ↓
PortAudio (C 라이브러리, 여러 OS에서 일관된 인터페이스 제공)
    ↓
sounddevice (Python 바인딩)
    ↓
우리의 Python 코드
```

**왜 sounddevice를 선택했나?**
- `pyaudio`보다 설치가 쉬움 (macOS에서 사전 컴파일된 휠 제공)
- 모던한 API (numpy 배열을 직접 다룸)
- PortAudio 기반으로 안정적

---

### 2. numpy 배열과 오디오 버퍼

**오디오는 숫자의 배열이다.**

마이크에서 나오는 소리:
```
음파 (아날로그 신호)
    ↓ (A/D 변환, 16kHz 샘플링)
    ↓
숫자 배열: [-0.001, 0.002, -0.003, 0.001, ...]
    ↓
numpy 배열로 저장: np.array([-0.001, 0.002, ...], dtype=float32)
```

**16kHz 샘플링 레이트란?**
```
시간 축 →
음량   ↑
      │  •
      │ • •
      │• • •••
      ├─────────→
      0 1 2 3 4 5 시간(ms)

각 • 는 1/16000초 (약 0.0625ms) 간격으로 음량을 측정한 것.

즉, 1초 동안 16,000개의 샘플(숫자)이 생긴다.
5초 녹음 → 16,000 × 5 = 80,000개 숫자
```

**Whisper(STT 모델)가 요구하는 포맷:**
- 샘플링 레이트: **16,000 Hz** (Whisper는 이 값으로 고정)
- 채널: **모노** (1채널, 왼쪽/오른쪽 합쳐서 1개 배열)
- 데이터형: **float32** (각 샘플이 -1.0 ~ 1.0 범위의 실수)

---

### 3. sounddevice.InputStream: "지속적인" 녹음

```python
import sounddevice as sd
import numpy as np

# InputStream을 시작하면 "백그라운드에서 계속 녹음"된다
stream = sd.InputStream(
    channels=1,           # 모노
    samplerate=16000,     # Whisper 맞춤
    dtype='float32',      # float32 형식
    blocksize=4096        # 한 번에 4096개 샘플씩 읽음
)
stream.start()

# 이제 마이크가 백그라운드에서 계속 음성을 수신하고 있다
# (stream이 종료될 때까지 계속)
```

**blocksize=4096의 의미:**
```
4096개 샘플 = 4096 / 16000초 = 약 0.256초 (256ms)

즉, 256ms마다 한 덩어리(블록)의 음성 데이터가 준비된다.
```

---

### 4. "버퍼에 누적"한다는 의미

우리는 N초 동안 계속 마이크 데이터를 받아서 **한 곳에 모아야** 한다.

```
시간 →
├─ 0~0.25초 ─┤  [블록 1: 4096개 샘플] 
├─ 0.25~0.5초 ┤  [블록 2: 4096개 샘플]
├─ 0.5~0.75초 ┤  [블록 3: 4096개 샘플]
├─ 0.75~1.0초 ┤  [블록 4: 4096개 샘플]
└─ 합치기 ────→  [누적: 16,384개 샘플 = 약 1초]

이 과정을 계속 반복:
현재 = 이전 누적 데이터 + 새로 도착한 블록
```

**Python에서의 구현:**
```python
import sounddevice as sd
import numpy as np

stream = sd.InputStream(channels=1, samplerate=16000, dtype='float32', blocksize=4096)
stream.start()

accumulated = np.array([])  # 빈 배열로 시작

while True:
    # read()는 blocksize개의 새 샘플과 상태를 반환
    data, overflowed = stream.read(blocksize=4096)
    
    # data는 shape (4096, 1) numpy 배열 → flatten으로 1차원 변환
    new_samples = data.flatten()
    
    # 누적 배열에 추가
    accumulated = np.concatenate([accumulated, new_samples])
    
    # 예: 5초마다 "지금까지의 전체 데이터"를 Whisper에 넘김
    if accumulated.shape[0] >= 80000:  # 80000개 = 5초
        print(f"누적된 샘플 수: {accumulated.shape[0]}")
```

---

### 5. snapshot() 메서드의 역할

**현재까지 누적된 데이터를 "비파괴적으로" 복사해서 반환한다.**

```python
class MicRecorder:
    def __init__(self):
        self.accumulated = np.array([])
    
    def snapshot(self):
        # 지금까지의 누적 데이터를 복사해서 반환
        # 원본 accumulated는 그대로 유지됨
        return self.accumulated.copy()
```

**왜 copy()를 사용할까?**
```
# 안 좋은 예 (참조만 반환)
def snapshot(self):
    return self.accumulated  # 이건 참조일 뿐

# 호출부
data = recorder.snapshot()
data[0] = 999  # 변경하면 원본도 바뀜! (의도하지 않은 부작용)

# 좋은 예 (복사본 반환)
def snapshot(self):
    return self.accumulated.copy()  # 진짜 복사본

data = recorder.snapshot()
data[0] = 999  # 복사본만 바뀜, 원본은 안전
```

**실제 사용:**
```python
while True:
    time.sleep(5)  # 5초 대기
    
    # 지금까지의 모든 데이터를 가져옴 (원본은 계속 누적됨)
    full_buffer = recorder.snapshot()
    
    # Whisper에 전달
    segments, info = model.transcribe(full_buffer, language='ko')
```

---

### 6. save_wav() 메서드: 디스크에 저장

```python
import soundfile as sf

class MicRecorder:
    def save_wav(self, file_path):
        # numpy 배열을 WAV 파일로 저장
        # soundfile이 알아서 16kHz, mono, float32 포맷으로 쓴다
        sf.write(str(file_path), self.accumulated, self.sample_rate)
        print(f"저장: {file_path}")
```

**WAV 파일 포맷의 의미:**
```
WAV = Waveform Audio File Format (마이크로소프트)

WAV 파일 구조:
┌─────────────┬──────────────┬──────────┐
│   헤더      │   메타데이터  │   음성   │
│ (RIFF info) │ (16kHz, mono) │(16bit)   │
└─────────────┴──────────────┴──────────┘

예: 5초 녹음
   - 샘플 수: 80,000
   - 파일 크기: 약 160KB (80,000 × 2바이트, float32→int16으로 변환)
```

---

## 🎯 Step 1 구현: 실제 코드

### 전체 `mic_recorder.py`

```python
"""마이크 입력을 numpy 버퍼에 누적하고 WAV로 저장하는 모듈.

사용 예:
    # 방법 1: 독립 실행 (N초 녹음 후 저장)
    python mic_recorder.py --seconds 5 --out data/live_audio/test.wav
    
    # 방법 2: 클래스로 사용 (계속 녹음하며 스냅샷 가져오기)
    recorder = MicRecorder()
    recorder.start()
    
    # ... 계속 마이크 녹음 중 ...
    
    buffer = recorder.snapshot()  # 지금까지 누적된 데이터
    recorder.save_wav("result.wav")
    recorder.stop()
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


class MicRecorder:
    """마이크를 백그라운드에서 계속 녹음하는 클래스.
    
    스레드 안전: numpy 배열의 append는 GIL 하에서 안전하고,
    snapshot()은 copy()를 통해 비파괴적 읽기를 보장한다.
    """

    def __init__(
        self,
        sample_rate: int = 16000,  # Whisper 표준
        channels: int = 1,          # 모노
        dtype: str = "float32",     # float32 형식
        blocksize: int = 4096,      # 256ms 블록
    ):
        """초기화. 아직 녹음하지 않음.
        
        Args:
            sample_rate: 샘플링 레이트 (Hz). Whisper는 16000 고정.
            channels: 채널 수 (1=모노, 2=스테레오). Whisper는 모노 기대.
            dtype: 데이터 타입 (float32 권장).
            blocksize: 한 번에 읽을 샘플 수. 4096 ≈ 256ms @ 16kHz.
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self.blocksize = blocksize

        # 누적 버퍼
        self.accumulated = np.array([], dtype=self.dtype)
        
        # 스트림 (아직 시작 안 함)
        self.stream: sd.InputStream | None = None
        
        # 녹음 중단 신호 (스레드 안전)
        self.should_stop = False

    def start(self):
        """마이크 녹음 시작. 백그라운드 스레드에서 계속 실행."""
        if self.stream is not None:
            print("⚠️ 이미 녹음 중입니다", file=sys.stderr)
            return

        self.should_stop = False
        self.stream = sd.InputStream(
            channels=self.channels,
            samplerate=self.sample_rate,
            dtype=self.dtype,
            blocksize=self.blocksize,
        )
        self.stream.start()
        
        # 백그라운드 스레드에서 계속 읽기
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()
        
        print(f"🎤 마이크 녹음 시작 (샘플레이트: {self.sample_rate}Hz, 채널: {self.channels})")

    def _read_loop(self):
        """백그라운드에서 계속 블록을 읽어 누적. start()에서 호출됨."""
        while not self.should_stop and self.stream is not None:
            try:
                # blocksize개의 새 샘플 읽기
                data, overflow = self.stream.read(self.blocksize)
                
                if overflow:
                    print("⚠️  오버플로우 감지 (일부 샘플 손실 가능)", file=sys.stderr)
                
                # data는 (blocksize, channels) 모양
                # 모노라면 (4096, 1) → flatten으로 (4096,) 변환
                new_samples = data.flatten()
                
                # 누적 배열에 추가
                self.accumulated = np.concatenate([self.accumulated, new_samples])
            except Exception as e:
                print(f"❌ 읽기 오류: {e}", file=sys.stderr)
                break

    def snapshot(self) -> np.ndarray:
        """현재까지 누적된 오디오 데이터를 복사본으로 반환.
        
        원본 버퍼는 변경되지 않으므로, 반환된 배열을 수정해도 안전.
        
        Returns:
            (N,) 모양의 float32 numpy 배열 (N = 누적된 샘플 수).
        """
        return self.accumulated.copy()

    def save_wav(self, file_path: Path | str):
        """현재까지의 누적 데이터를 WAV 파일로 저장.
        
        Args:
            file_path: 저장 위치 (예: data/live_audio/session.wav).
        """
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        sf.write(str(file_path), self.accumulated, self.sample_rate)
        duration_sec = self.accumulated.shape[0] / self.sample_rate
        print(f"💾 저장: {file_path} ({duration_sec:.1f}초)")

    def stop(self):
        """마이크 녹음 중지. 백그라운드 스레드 종료."""
        if self.stream is None:
            print("⚠️  녹음이 시작되지 않았습니다", file=sys.stderr)
            return

        self.should_stop = True
        
        # 스레드가 종료될 때까지 대기 (최대 1초)
        if hasattr(self, 'thread'):
            self.thread.join(timeout=1.0)
        
        self.stream.stop()
        self.stream.close()
        self.stream = None
        
        duration_sec = self.accumulated.shape[0] / self.sample_rate
        print(f"🛑 녹음 중지 (총 {duration_sec:.1f}초)")

    def reset(self):
        """누적 버퍼를 초기화. (새 세션 시작할 때)"""
        self.accumulated = np.array([], dtype=self.dtype)


def record_fixed_seconds(
    duration_sec: float,
    out_path: Path | str,
    model: str = "base",
) -> None:
    """스모크 테스트용: N초 녹음 후 WAV로 저장.
    
    Args:
        duration_sec: 녹음 시간 (초).
        out_path: 저장 경로.
        model: (미사용, 향후 로깅용).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    recorder = MicRecorder()
    recorder.start()
    
    print(f"🎤 {duration_sec}초 동안 마이크에 대고 말하세요...")
    time.sleep(duration_sec)
    
    recorder.save_wav(out_path)
    recorder.stop()
    
    print("✅ 완료!")


def main():
    parser = argparse.ArgumentParser(
        description="마이크를 녹음해서 WAV 파일로 저장합니다."
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=5,
        help="녹음 시간 (초, 기본: 5)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/live_audio/recording.wav"),
        help="저장 경로 (기본: data/live_audio/recording.wav)",
    )
    args = parser.parse_args()
    
    record_fixed_seconds(args.seconds, args.out)


if __name__ == "__main__":
    main()
```

---

## ✅ Step 1 실행 흐름 (시각화)

```
python mic_recorder.py --seconds 5 --out data/live_audio/smoke_test.wav
    │
    ├─ MicRecorder() 생성
    │   └─ accumulated = []  (빈 배열)
    │
    ├─ recorder.start()
    │   ├─ sounddevice.InputStream 시작
    │   └─ 백그라운드 스레드 시작
    │       └─ 루프: 계속 4096개 샘플씩 읽어서 accumulated에 추가
    │
    ├─ "🎤 5초 동안 마이크에 대고 말하세요..." (터미널 출력)
    │
    ├─ time.sleep(5)  (메인 스레드는 5초 대기)
    │   ├─ 0초:     백그라운드에서 1번째 블록 도착 → accumulated = [샘플 1-4096]
    │   ├─ 0.25초:  백그라운드에서 2번째 블록 도착 → accumulated = [샘플 1-8192]
    │   ├─ 0.50초:  3번째 블록 → accumulated = [샘플 1-12288]
    │   ├─ ...
    │   └─ 5초:     20번째 블록 → accumulated = [샘플 1-81920] (약 5.12초)
    │
    ├─ recorder.save_wav(...)
    │   └─ soundfile.write(파일경로, accumulated, 16000)
    │       └─ WAV 파일 생성: data/live_audio/smoke_test.wav
    │
    ├─ recorder.stop()
    │   └─ 백그라운드 스레드 중지
    │
    └─ "✅ 완료!" (터미널 출력)
```

---

## 🧪 검증 단계 (Step 1 완료 후)

### 1️⃣ 파일 생성 확인
```bash
ls -lh data/live_audio/smoke_test.wav
# 예상: -rw-r--r--  1 user  staff  160K Aug  1 21:50 data/live_audio/smoke_test.wav
```

### 2️⃣ 파일 정보 확인 (macOS)
```bash
afinfo data/live_audio/smoke_test.wav
# 예상 출력:
# File:           data/live_audio/smoke_test.wav
# Data format:     Linear PCM
# Channels:        1 (Mono)
# Sample rate:     16000.0 Hz
# Duration:        5.12 s
```

### 3️⃣ 재생 확인 (선택)
```bash
# 음소거 해제하고 실행 (소리가 날 수 있음)
afplay data/live_audio/smoke_test.wav
```

---

## 🎓 학습 포인트

| 개념 | 의미 | 코드 |
|---|---|---|
| **sounddevice** | 마이크 입출력 라이브러리 | `sd.InputStream(...)` |
| **블록(block)** | 한 번에 읽는 샘플 묶음 (4096개 ≈ 256ms) | `blocksize=4096` |
| **누적(accumulate)** | 여러 블록을 이어붙이기 | `np.concatenate([...])` |
| **snapshot()** | 지금까지의 전체 데이터 복사본 반환 | `.copy()` |
| **WAV** | 음성 파일 포맷 | `sf.write(...)` |
| **16kHz** | Whisper가 요구하는 샘플링 레이트 | `sample_rate=16000` |
| **float32** | 각 샘플이 -1.0 ~ 1.0 실수 | `dtype='float32'` |
| **모노(mono)** | 1채널 (왼쪽/오른쪽 구분 없음) | `channels=1` |

---

## ⚠️ Step 1에서 주의할 점

1. **마이크 권한**: macOS에서 터미널이 마이크 접근 권한이 있는지 확인
   - 시스템 설정 > 개인정보 보호 > 마이크 > 터미널 앱 체크

2. **오버플로우**: 시스템이 바쁘면 일부 샘플이 손실될 수 있음
   - 로그에 "⚠️ 오버플로우" 메시지가 보이면 시스템 부하 확인

3. **파일 크기**: 5초 녹음 ≈ 160KB (생각보다 작음)
   - 이는 음성이 낮은 주파수(음성 대역)만 포함되기 때문

4. **numpy 버전**: `concatenate` 성능
   - 현재 구현은 매 블록마다 배열을 다시 쓰므로 매우 장시간 녹음(>30분)할 때는 느려질 수 있음
   - 향후 개선 가능 (예: deque 사용)
