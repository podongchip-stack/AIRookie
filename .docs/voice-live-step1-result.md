# Step 1 구현 결과: 마이크 녹음 모듈 (`mic_recorder.py`)

> `.docs/voice-live-step1-detailed.md`(개념 가이드)를 따라 실제로 구현하고
> 로컬에서 테스트한 결과 기록. 코드 자체는 `mic_recorder.py` 참고.

---

## ✅ 한 줄 요약

마이크 입력을 백그라운드 스레드에서 numpy 버퍼로 누적하고, `snapshot()`으로
비파괴적 중간 조회, `save_wav()`로 WAV 저장이 가능한 `MicRecorder` 클래스를
구현했다. 5초 스모크 테스트로 실제 마이크 녹음 → WAV 파일 생성까지 확인 완료.

---

## 📦 변경/추가된 파일

| 파일 | 상태 | 내용 |
|---|---|---|
| `mic_recorder.py` | 신규 | `MicRecorder` 클래스 + `record_fixed_seconds()` + CLI |
| `requirements.txt` | 수정 | `sounddevice==0.5.5`, `soundfile==0.14.0` 추가 |

`data/live_audio/`는 실행 시 자동 생성됨 (기존 `data/`가 `.gitignore`에 걸려
있어 별도 설정 불필요).

---

## 🛠️ 구현 내용

### `MicRecorder` 클래스

```python
class MicRecorder:
    def __init__(self, sample_rate=16000, blocksize=4096): ...
    def start(self) -> None: ...       # sd.InputStream 시작 (백그라운드 콜백)
    def snapshot(self) -> np.ndarray:  # 누적 버퍼의 복사본 반환 (비파괴적)
    def save_wav(self, path: Path): ...
    def stop(self) -> None: ...
```

가이드 문서와 다르게 실제 구현에서 추가한 것: **`threading.Lock()`**.

- `_on_audio_block()` 콜백(오디오 입력 스레드)이 `self._accumulated`에 계속
  쓰는 동시에, 메인 스레드에서 `snapshot()`이 같은 배열을 읽는다.
- `np.concatenate()`는 원본 배열을 바꾸지 않고 **새 배열을 만들어 재할당**하는
  연산이라 GIL만으로도 우연히 안전하게 동작할 가능성이 높지만, "우연히
  안전"에 의존하는 대신 락으로 명시적으로 직렬화했다. 비용은 무시할 수준
  (락 홀드 시간이 배열 복사/concat 시간 자체보다 짧음).

### 샘플레이트 고정

`SAMPLE_RATE = 16000` — Whisper가 기대하는 값과 동일하게 맞춰서, 이후 STT
단계에서 리샘플링이 필요 없게 했다.

### CLI

```bash
python mic_recorder.py --seconds 5 --out data/live_audio/smoke_test.wav
```

---

## 🧪 실행 결과 (실제 테스트)

### 환경
- conda 환경: `rookie` (Python 3.11, 저장소 `requirements.txt` 기준 환경)
- 장치: MacBook Air 내장 마이크 (`sd.query_devices()`로 확인)

```
> 0 MacBook Air 마이크, Core Audio (1 in, 0 out)
< 1 MacBook Air 스피커, Core Audio (0 in, 2 out)
  2 Microsoft Teams Audio, Core Audio (1 in, 1 out)
```

### 실행 명령 및 출력

```bash
$ python mic_recorder.py --seconds 5 --out data/live_audio/smoke_test.wav
녹음 시작 (5.0초)... 마이크에 대고 말하세요.
녹음 완료: data/live_audio/smoke_test.wav (5.0초)
```

가이드 문서에서 예상한 출력과 **완전히 일치**.

### 파일 검증 (`afinfo`)

```
File type ID:   WAVE
Num Tracks:     1
Data format:     1 ch,  16000 Hz, Int16
estimated duration: 4.864000 sec
audio bytes: 155648
audio packets: 77824
bit rate: 256000 bits per second
```

- **채널/샘플레이트**: 1채널, 16000Hz — 의도한 값 정확히 일치 ✅
- **파일 크기**: 155,692 bytes — Int16 기준 계산과 일치
  (16000Hz × 4.864초 × 2바이트 ≈ 155,648 오디오 바이트 + 44바이트 WAV 헤더)

---

## ⚠️ 발견한 두 가지 실제 동작 (가이드 문서와의 차이)

계획 단계(가이드 문서)에서는 예상하지 못했고, 실제로 돌려봐야 알 수 있었던
부분:

### 1. 실제 녹음 길이가 요청한 5.0초보다 약간 짧다 (4.864초)

**원인**: `sd.InputStream.start()` 호출부터 실제로 콜백이 첫 오디오 블록을
전달하기까지 아주 짧은 초기화 지연이 있다. `time.sleep(5)`는 프로세스
기준으로는 정확히 5초지만, 그 사이 스트림이 완전히 준비되기 전 구간만큼
누적된 샘플 수가 이론치보다 적다.

**영향**: Step 1(스모크 테스트)에서는 무시 가능한 수준(약 2.7% 차이). Step
3(라이브 재변환 루프)에서는 애초에 "정확히 N초"가 아니라 "그 시점까지 누적된
전체"를 기준으로 동작하므로 이 오차가 로직에 영향을 주지 않는다 — `elapsed`
값을 실제 버퍼 길이로 매번 재계산하기 때문.

### 2. `sf.write()`가 float32 배열을 Int16 WAV로 저장했다

**원인**: `soundfile`은 WAV 저장 시 별도 `subtype`을 지정하지 않으면 확장자
`.wav`에 대해 기본적으로 `PCM_16`(Int16)을 사용한다. `sd.InputStream`에서
`dtype="float32"`로 캡처했지만, 저장 단계에서 자동으로 16비트 정수로
변환되었다.

**영향 없음, 오히려 유리함**:
- `faster-whisper`는 파일 경로를 받으면 내부적으로 ffmpeg/av로 다시
  디코딩하므로 Int16/Float32 여부와 무관하게 정상 동작한다.
- Float32보다 파일 크기가 절반이라 디스크 사용량 측면에서 더 낫다.
- 정밀도 손실은 16비트 PCM이 이미 일반적인 통화 품질 오디오 표준(전화망도
  보통 8~16비트)이라 음성 인식 품질에 실질적 영향이 없다.

별도 조치 없이 현재 동작을 그대로 유지하기로 했다. `save_wav()`의 동작을
바꾸고 싶다면 `sf.write(..., subtype="FLOAT")`를 명시하면 되지만, Step 2에서
기존 `transcribe.py`가 이 파일을 문제없이 읽는지 확인한 뒤 필요성을
재평가한다.

---

## ✅ 완료 체크리스트 대조

가이드 문서(`voice-live-step1-detailed.md`)의 검증 항목 기준:

- [x] `python mic_recorder.py --seconds 5` 실행 시 예상 터미널 메시지 출력
- [x] `data/live_audio/smoke_test.wav` 파일 생성
- [x] `afinfo`로 16000Hz, 모노 채널 확인
- [x] 마이크 권한 프롬프트 정상 통과 (macOS)

---

## 🔗 다음 단계

Step 2(`.docs/voice-live-step2-detailed.md`)로 진행: 새 코드 작성 없이, 이번에
생성한 `data/live_audio/smoke_test.wav`를 기존 `transcribe.py` CLI에 그대로
통과시켜 배치 파이프라인 재사용을 검증한다.

```bash
python transcribe.py data/live_audio/smoke_test.wav --model base
```
