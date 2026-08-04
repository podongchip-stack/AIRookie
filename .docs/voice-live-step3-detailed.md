# Step 3 상세 가이드: 주기적 재변환 오케스트레이터

## 📚 개념: "Step 2를 N초마다 반복"

Step 3는 **라이브처럼 보이게 하는 핵심 단계**.

```
Step 1: mic_recorder.py
    └─ 마이크 → WAV 파일 (한 번)

Step 3: live_transcribe.py
    └─ 마이크 → 계속 누적
       ├─ 5초마다: "누적 버퍼 전체를 Whisper에 다시 넣음" (재변환)
       ├─ 새 세그먼트만 터미널 출력
       └─ 텍스트 파일에 append (계속 증가)
```

---

## 🔄 핵심 아이디어: "재변환(Re-transcription)"

Whisper는 **스트리밍 API가 아니므로**, 누적 버퍼 **전체**를 매번 다시 처리한다.

```
마이크 (계속 녹음)
│
├─ 0초:   [0초~5초 오디오 누적] → Whisper → 세그먼트 1, 2, 3
├─ 5초:   [0초~10초 오디오 누적] → Whisper → 세그먼트 1, 2, 3, 4, 5
│         (세그먼트 1, 2, 3은 이미 출력했으니 skip, 새로운 4, 5만 출력)
├─ 10초:  [0초~15초 오디오 누적] → Whisper → 세그먼트 1~7
│         (세그먼트 1~5는 skip, 새로운 6, 7만 출력)
└─ ...
```

**"새 세그먼트만 출력"을 어떻게 판단할까?**

```python
printed_until = 0.0  # 마지막으로 출력한 세그먼트의 끝 시간

for seg in segments:
    if seg.end <= printed_until:
        continue  # 이미 출력했으니 skip
    
    print(f"[{format_timestamp(seg.start)}] {seg.text}")
    printed_until = seg.end  # 업데이트
```

---

## 💾 파일 구조

### 입력
```
data/live_audio/     ← sounddevice가 계속 마이크 데이터를 이 폴더에 누적
```

### 출력
```
data/live_text/
├─ session1.txt   (0초: 빈 파일)
│                 (5초: "환자는 의식이 없습니다")
│                 (10초: "환자는 의식이 없습니다 호흡이 얕습니다")
│                 (15초: "환자는 의식이 없습니다 호흡이 얕습니다 맥박 빨라요")
└─ session2.txt   (다른 세션)
```

즉, **같은 파일이 계속 덮어씌워지면서 커진다**.

---

## 🎯 Step 3 실제 코드

### `live_transcribe.py` (신규, 저장소 루트)

```python
"""마이크를 계속 녹음하면서 N초마다 누적 버퍼를 재변환하는 오케스트레이터.

사용 예:
    python live_transcribe.py --session live_test1 --model base --stt-interval 5
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

from mic_recorder import MicRecorder
from transcribe import format_timestamp  # 기존 함수 재사용


BASE_DIR = Path(__file__).resolve().parent
LIVE_AUDIO_DIR = BASE_DIR / "data" / "live_audio"
LIVE_TEXT_DIR = BASE_DIR / "data" / "live_text"


def live_transcribe(
    session: str,
    model_size: str = "base",
    language: str = "ko",
    device: str = "auto",
    compute_type: str = "auto",
    stt_interval_sec: int = 5,
) -> None:
    """마이크를 계속 녹음하면서 N초마다 재변환.
    
    Args:
        session: 세션 이름 (파일명에 사용, 예: "live_test1")
        model_size: Whisper 모델 크기
        language: 언어 코드
        device: "auto", "cpu", "cuda"
        compute_type: "auto", "int8", "float32"
        stt_interval_sec: 재변환 주기 (초)
    """
    
    # 준비
    print(f"모델 로딩 중... ({model_size}, device={device}, compute_type={compute_type})")
    load_start = time.perf_counter()
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    load_elapsed = time.perf_counter() - load_start
    print(f"모델 로딩 완료 ({load_elapsed:.2f}초)")
    
    recorder = MicRecorder()
    recorder.start()
    
    # 상태 변수
    printed_until = 0.0  # 마지막으로 출력한 세그먼트의 끝 시간
    all_turn_texts: list[str] = []
    all_turn_offsets: list[float] = []
    out_path = LIVE_TEXT_DIR / f"{session}.txt"
    
    print(f"\n🎤 라이브 재변환 시작 (주기: {stt_interval_sec}초)")
    print("말하세요... Ctrl+C로 중지")
    
    try:
        iteration = 0
        while True:
            time.sleep(stt_interval_sec)
            iteration += 1
            
            # 현재 누적 버퍼
            buffer = recorder.snapshot()
            if buffer.shape[0] == 0:
                continue
            
            elapsed = buffer.shape[0] / recorder.sample_rate
            print(f"\n[{iteration}차] 재변환 중... 누적 {elapsed:.1f}초")
            
            # 재변환
            transcribe_start = time.perf_counter()
            try:
                # 방법 1: numpy 배열 직접 전달 (빠름)
                # faster-whisper는 파일 경로뿐 아니라 배열도 받음
                segments, info = model.transcribe(
                    buffer.flatten(),  # 1D 배열로 변환
                    language=language,
                    vad_filter=True
                )
            except TypeError:
                # 방법 2: 배열 전달이 안 되면 임시 파일로 폴백
                print("⚠️  배열 입력 미지원, 임시 WAV로 폴백...")
                temp_path = LIVE_AUDIO_DIR / f"_temp_{session}.wav"
                recorder.save_wav(temp_path)
                segments, info = model.transcribe(
                    str(temp_path),
                    language=language,
                    vad_filter=True
                )
                temp_path.unlink()  # 삭제
            
            transcribe_elapsed = time.perf_counter() - transcribe_start
            
            # 새 세그먼트 추출
            new_segments = []
            for seg in segments:
                if seg.end <= printed_until:
                    continue  # 이미 출력함
                
                ts = format_timestamp(seg.start)
                text = seg.text.strip()
                print(f"[{ts}] {text}")
                
                all_turn_texts.append(text)
                all_turn_offsets.append(seg.start)
                new_segments.append(seg)
                printed_until = seg.end
            
            # 텍스트 파일 갱신 (모든 턴을 공백으로 연결)
            if all_turn_texts:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                full_text = " ".join(all_turn_texts)
                out_path.write_text(full_text, encoding="utf-8")
            
            print(f"(재변환: {transcribe_elapsed:.2f}초, 누적 텍스트: {out_path})")
    
    except KeyboardInterrupt:
        print("\n\n🛑 녹음 중지 (Ctrl+C)")
    
    finally:
        recorder.stop()
        
        # 최종 상태
        if all_turn_texts:
            duration_sec = buffer.shape[0] / recorder.sample_rate
            print(f"\n📊 세션 요약:")
            print(f"  총 시간: {duration_sec:.1f}초")
            print(f"  총 턴: {len(all_turn_texts)}")
            print(f"  텍스트 파일: {out_path}")
            print(f"  내용: {out_path.read_text()[:100]}...")


def main():
    parser = argparse.ArgumentParser(
        description="마이크를 계속 녹음하면서 N초마다 재변환합니다."
    )
    parser.add_argument(
        "--session",
        type=str,
        required=True,
        help="세션 이름 (예: live_test1)",
    )
    parser.add_argument(
        "--model",
        default="base",
        help="Whisper 모델 크기 (기본: base)",
    )
    parser.add_argument(
        "--language",
        default="ko",
        help="언어 코드 (기본: ko)",
    )
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cuda", "cpu"],
        help="연산 장치 (기본: auto)",
    )
    parser.add_argument(
        "--compute-type",
        default="auto",
        help="연산 정밀도 (기본: auto)",
    )
    parser.add_argument(
        "--stt-interval",
        type=int,
        default=5,
        help="STT 재변환 주기 (초, 기본: 5)",
    )
    args = parser.parse_args()
    
    live_transcribe(
        session=args.session,
        model_size=args.model,
        language=args.language,
        device=args.device,
        compute_type=args.compute_type,
        stt_interval_sec=args.stt_interval,
    )


if __name__ == "__main__":
    main()
```

---

## ✅ Step 3 실행 및 검증

### 실행
```bash
python live_transcribe.py --session live_test1 --model base --stt-interval 5
```

### 예상 터미널 출력
```
모델 로딩 중... (base, device=auto, compute_type=auto)
모델 로딩 완료 (10.23초)

🎤 라이브 재변환 시작 (주기: 5초)
말하세요... Ctrl+C로 중지

[1차] 재변환 중... 누적 5.2초
[00:00:00.320] 환자는 의식이 없습니다
[00:00:02.140] 호흡이 얕습니다
(재변환: 2.34초, 누적 텍스트: data/live_text/live_test1.txt)

[2차] 재변환 중... 누적 10.5초
[00:00:04.500] 맥박도 빨라요
(재변환: 2.45초, 누적 텍스트: data/live_text/live_test1.txt)

[3차] 재변환 중... 누적 15.8초
(재변환: 2.38초, 누적 텍스트: data/live_text/live_test1.txt)

🛑 녹음 중지 (Ctrl+C)

📊 세션 요약:
  총 시간: 15.8초
  총 턴: 3
  텍스트 파일: data/live_text/live_test1.txt
  내용: 환자는 의식이 없습니다 호흡이 얕습니다 맥박도 빨라요
```

### 병렬 검증 (터미널 2에서)
```bash
# 텍스트 파일이 실시간으로 커지는지 확인
tail -f data/live_text/live_test1.txt
```

### 최종 파일 확인
```bash
# 텍스트 파일 내용
cat data/live_text/live_test1.txt

# 파일 크기 변화
watch -n 1 'ls -lh data/live_text/live_test1.txt'  # 1초마다 갱신
```

---

## 🧵 스레드 안전성

Step 3에서는 **두 개의 스레드**가 동시에 실행된다:

```
백그라운드 스레드 (mic_recorder의 _read_loop):
  ├─ 계속 sounddevice에서 블록 읽기
  └─ self.accumulated에 append

메인 스레드 (live_transcribe의 while 루프):
  ├─ 5초마다 깨어남
  ├─ recorder.snapshot() 호출 (배열 복사)
  └─ Whisper에 전달
```

**numpy 배열의 concatenate는 GIL 하에서 안전**하므로 동시성 문제 없음.

```python
# 백그라운드 스레드 (안전)
self.accumulated = np.concatenate([self.accumulated, new_samples])

# 메인 스레드 (안전, 복사본을 반환)
buffer = recorder.snapshot()  # self.accumulated.copy()
```

---

## ⚠️ Step 3의 주의사항

| 문제 | 원인 | 해결책 |
|---|---|---|
| **모델이 로드되지 않음** | Whisper 없음 | `pip install faster-whisper` |
| **배열 입력 에러** | faster-whisper 버전 | 자동 폴백 (임시 WAV 사용) |
| **CPU 점점 올라감** | 재변환 누적 시간 | interval을 5초에서 10초로 늘리기 |
| **WAV 파일 없음** | 마이크 권한 부족 | macOS 시스템 설정 확인 |
| **세그먼트 중복 출력** | VAD 경계 흔들림 | 허용 오차 (이번 단계는 용인) |

---

## 🎓 Step 3 핵심 포인트

1. **버퍼 관리**: `snapshot()`으로 비파괴적 복사
2. **중복 방지**: `printed_until`로 이미 처리한 부분 skip
3. **파일 갱신**: 매 사이클마다 `out_path.write_text()` (덮어쓰기)
4. **스레드 안전**: numpy GIL + copy() 사용
5. **폴백 처리**: 배열 입력 실패 시 임시 WAV 생성

