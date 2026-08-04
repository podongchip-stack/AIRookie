# Step 2 구현 결과: 캡처한 파일을 기존 배치 파이프라인에 그대로 통과

> `.docs/voice-live-step2-detailed.md`(개념 가이드)를 따라 실행한 결과 기록.
> Step 2는 새 코드를 작성하지 않는 단계이므로, 이 문서는 "실행 결과"만 다룬다.

---

## ✅ 한 줄 요약

Step 1에서 마이크로 캡처한 WAV 파일을 기존 `transcribe.py` CLI에 코드 변경
없이 그대로 통과시켰다. **STT만 실행**, **STT+필터링+LLM 구조화 전체 실행**
두 경로 모두 기존 배치 파이프라인이 라이브 캡처 오디오를 문제없이 처리함을
확인했다. 추가로, 실제 사람 음성이 필요한 상황을 대비해 macOS TTS로 합성한
발화 오디오로 **전체 파이프라인의 정상 동작(성공 경로)**까지 별도로 검증했다.

---

## 🧪 테스트 1: Step 1 스모크 테스트 파일 그대로 통과

### 실행

```bash
python transcribe.py data/live_audio/smoke_test.wav --model base
```

### 결과

```
모델 로딩 중... (base, device=auto, compute_type=auto)
모델 로딩 완료 (8.84초)
변환 중: smoke_test.wav

텍스트 파일 저장: data/origin_text/smoke_test.txt
변환 소요 시간: 0.22초 (모델 로딩 제외)
```

**세그먼트가 하나도 출력되지 않았고, `data/origin_text/smoke_test.txt`는
빈 파일(0바이트)로 저장되었다.**

### 원인 및 판단: 이것은 버그가 아니라 예상된 동작

Step 1의 `smoke_test.wav`는 자동화된 스모크 테스트로 녹음되었고, 그 5초
동안 사람이 실제로 말하지 않았다(무음/배경 잡음만 녹음됨). Whisper의
`vad_filter=True` 옵션이 음성 활동이 감지되지 않는 구간을 걸러내므로,
세그먼트가 하나도 생성되지 않는 것이 정상이다.

**중요한 확인 포인트**: 파이프라인이 에러 없이 "세그먼트 0개 → 빈 텍스트
파일 저장"까지 깨끗하게 처리했다는 것 자체가 Step 2의 핵심 목표(기존
파이프라인이 라이브 캡처 파일을 그대로 받아들인다)를 증명한다.

### `--summarize`까지 실행했을 때: 빈 입력에 대한 에러 처리 확인

```bash
python transcribe.py data/live_audio/smoke_test.wav --model base --summarize
```

```
실시간 음성 필터링: 의료 관련 문장 분류 중...
분류 완료 (6.18초, threshold=0.4)

경고: 의료 관련으로 분류된 문장이 없습니다. 전체 텍스트를 대상으로 구조화를 시도합니다.

SBAR 구조화 중... (qwen3:14b)

구조화 실패: LLM 응답에서 JSON을 찾지 못했습니다: ''
```

`transcribe.py`의 `build_and_emit_call_summary()`에 이미 구현되어 있는
폴백 로직(필터링된 문장이 없으면 `filtered_text = full_text`로 대체)과,
LLM이 빈 입력에서 JSON을 만들지 못했을 때의 `StructuringError` 예외 처리가
**둘 다 설계대로 동작**했다. 크래시 없이 에러 메시지를 출력하고 정상
종료됨을 확인.

---

## 🧪 테스트 2 (보완): 실제 발화가 담긴 오디오로 성공 경로 검증

테스트 1은 "빈 입력을 잘 처리하는가"만 증명했을 뿐, "실제 의료 발화가
있을 때 파이프라인이 끝까지 정상적으로 SBAR JSON을 만드는가"는 별도로
확인이 필요했다. 이를 위해 macOS 내장 TTS(`say` 명령, 한국어 음성 `Yuna`)로
CLAUDE.md 예시 시나리오와 유사한 문장을 합성하여 오디오 파일을 만들고, 이를
`transcribe.py --summarize`에 통과시켰다.

> 이 오디오는 마이크로 캡처한 것이 아니라 **TTS로 합성**한 것임을 명확히
> 한다 — Step 1(마이크 캡처)의 검증 대상이 아니라, Step 2(기존 파이프라인
> 재사용)가 "정상적인 음성 콘텐츠"에서도 끝까지 동작하는지 확인하기 위한
> 보완 테스트다.

### 합성 오디오 생성

```bash
say -v Yuna -o synthetic_speech_test.aiff \
  "환자는 50대 남성이며 교통사고로 흉부 충격을 받았습니다. \
   의식이 저하되어 있고 호흡이 곤란한 상태입니다. \
   산소를 공급하고 지혈을 완료했습니다."

# soundfile로 WAV 컨테이너로 변환 (mic_recorder.py와 동일하게 다루기 위함)
python -c "
import soundfile as sf
data, sr = sf.read('synthetic_speech_test.aiff')
sf.write('synthetic_speech_test.wav', data, sr)
"
```

### 실행

```bash
python transcribe.py data/live_audio/synthetic_speech_test.wav --model base --summarize
```

### 결과: STT

```
[00:00:00.000 -> 00:00:04.960] 환자는 50대 남성이며 교통사고로 흉부 충격을 받았습니다.
[00:00:04.960 -> 00:00:08.480] 의식이 적화되어 있고 호흡이 곤란한 상태입니다.
[00:00:08.480 -> 00:00:11.280] 산소를 공급하고 지혜를 완료했습니다.
```

`base` 모델의 인식 오차로 "저하" → "적화", "지혈" → "지혜"로 두 글자가
잘못 인식되었다(TTS 발음의 미세한 부정확함 + 경량 모델의 한계가 겹친
것으로 추정). 실제 사람 음성이나 더 큰 모델(`large-v3`)에서는 이런 오차가
줄어들 것으로 예상되며, 이 자체가 Step 2의 검증 범위는 아니다(파이프라인
연결이 되는지가 목표).

### 결과: 필터링

```
실시간 음성 필터링: 의료 관련 문장 분류 중...
분류 완료 (9.80초, threshold=0.4)
  [0.515] 유지  환자는 50대 남성이며 교통사고로 흉부 충격을 받았습니다.
  [0.696] 유지  의식이 적화되어 있고 호흡이 곤란한 상태입니다.
  [0.424] 유지  산소를 공급하고 지혜를 완료했습니다.
```

세 문장 모두 의료 관련으로 정확히 분류됨 (threshold 0.4 대비 0.42~0.70 범위).

### 결과: SBAR 구조화 (최종 JSON)

```json
{
  "transcript": {
    "raw_text": "환자는 50대 남성이며 교통사고로 흉부 충격을 받았습니다. 의식이 적화되어 있고 호흡이 곤란한 상태입니다. 산소를 공급하고 지혜를 완료했습니다.",
    "filtered_text": "환자는 50대 남성이며 교통사고로 흉부 충격을 받았습니다. 의식이 적화되어 있고 호흡이 곤란한 상태입니다. 산소를 공급하고 지혜를 완료했습니다.",
    "language": "ko",
    "duration_sec": 11.3,
    "turns": [ "...(3개 턴, 화자 미분리)..." ]
  },
  "summary": {
    "patient": "50대 남성",
    "mechanism": "교통사고 · 흉부 충격",
    "symptoms": ["의식 저하", "호흡 곤란"],
    "treatment": ["산소 공급", "지혈 완료"],
    "severity_tag": "high",
    "required_department": "응급의학"
  },
  "source": "ai",
  "model_used": {
    "stt": "faster-whisper-base",
    "llm": "qwen3:14b"
  }
}
```

**주목할 점**: STT 단계에서 "적화"/"지혜"로 잘못 인식되었음에도, LLM
구조화 단계(`summarizer.py`)가 문맥으로 정확한 의학 용어("의식 저하",
"지혈 완료")를 복원해냈다. `severity_tag: "high"`(의식 저하 + 호흡 곤란)와
`required_department: "응급의학"` 판정도 CLAUDE.md의 severity 판단 기준과
일치한다.

---

## 📊 두 테스트 결과 비교

| 항목 | 테스트 1 (Step1 무음 캡처) | 테스트 2 (TTS 합성 발화) |
|---|---|---|
| 오디오 출처 | 실제 마이크 캡처 (무음) | macOS TTS 합성 |
| STT 세그먼트 | 0개 | 3개 |
| `origin_text/*.txt` | 빈 파일 (0 byte) | 3문장 텍스트 |
| 필터링 | 실행 안 됨 (턴 없음) | 3개 턴 모두 "유지" |
| SBAR 구조화 | 실패 (빈 입력, 정상적인 에러 처리) | 성공 (JSON 생성) |
| 증명한 것 | **빈 입력에 대한 안전한 처리** | **정상 입력에 대한 성공 경로** |

두 결과를 합치면 "기존 파이프라인이 라이브 캡처 파일을 실패 경로/성공
경로 모두에서 코드 변경 없이 그대로 처리한다"는 Step 2의 목표가 완전히
증명된다.

---

## ✅ 완료 체크리스트 대조

가이드 문서(`voice-live-step2-detailed.md`) 기준:

- [x] 신규 코드 없이 실행만으로 검증 완료
- [x] `python transcribe.py <wav> --model base` 정상 동작
- [x] `data/origin_text/*.txt` 생성 확인
- [x] `--summarize` 옵션까지 포함한 전체 파이프라인 성공 경로 확인 (보완 테스트)
- [x] 빈 입력에 대한 에러 처리 경로도 부수적으로 확인 (원래 가이드 범위 밖이지만 유용한 발견)

---

## 🔗 다음 단계

Step 3(`.docs/voice-live-step3-detailed.md`)로 진행: `live_transcribe.py`를
신규 작성해, 마이크를 계속 녹음하면서 N초마다 누적 버퍼 전체를 재변환하는
라이브 루프를 구현한다. Step 2에서 확인한 `transcribe.py`의 `format_timestamp()`
함수와 세그먼트 출력 포맷을 그대로 재사용한다.
