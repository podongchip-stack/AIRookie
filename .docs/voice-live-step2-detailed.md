# Step 2 상세 가이드: 기존 배치 파이프라인 재사용

## 📚 개념: "새 코드 없이 검증하기"

Step 1에서 만든 `mic_recorder.py`는 **마이크만 다룬다**. STT, 필터링, LLM은 아직 손대지 않음.

Step 2는 **Step 1의 산출물(WAV 파일)을 기존 `transcribe.py`에 그대로 넣어본다**.

```
Step 1 (마이크):
    mic_recorder.py
    └─ data/live_audio/smoke_test.wav (생성)

Step 2 (기존 파이프라인):
    transcribe.py --summarize
    └─ data/live_audio/smoke_test.wav (입력)
    └─ data/origin_text/smoke_test.txt (출력)
    └─ data/summary_text/smoke_test_call_summary.json (출력)
```

**목표:** "라이브로 캡처한 오디오도 기존 파이프라인이 그대로 처리한다"는 것을 증명.

---

## 🎯 Step 2 실행: 코드 변경 없음

Step 2는 **코드를 짜는 단계가 아니다**. 그냥 실행하는 단계.

### 실행 명령

```bash
# 최소한의 실행 (STT만)
python transcribe.py data/live_audio/smoke_test.wav --model base

# 또는 전체 파이프라인 (STT + 필터링 + LLM)
python transcribe.py data/live_audio/smoke_test.wav --model base --summarize

# Ollama가 없으면 에러. Ollama 필요:
python transcribe.py data/live_audio/smoke_test.wav --model base --summarize --llm-model qwen3:14b
```

---

## 📊 Step 2 흐름도

```
user 실행
  $ python transcribe.py data/live_audio/smoke_test.wav --summarize
    │
    ├─ transcribe.py 메인 함수
    │   │
    │   ├─ WhisperModel("large-v3") 로드
    │   │   └─ "모델 로딩 중... (large-v3, device=auto, compute_type=auto)"
    │   │
    │   ├─ model.transcribe(파일경로, language="ko", vad_filter=True)
    │   │   └─ STT 처리 시작
    │   │   ├─ [00:00:00.320 -> 00:00:02.140] 환자는 의식이 없습니다
    │   │   ├─ [00:00:02.140 -> 00:00:04.500] 호흡이 얕습니다
    │   │   └─ ... (각 세그먼트 출력)
    │   │
    │   ├─ data/origin_text/smoke_test.txt 저장
    │   │   └─ "텍스트 파일 저장: data/origin_text/smoke_test.txt"
    │   │
    │   └─ --summarize 플래그가 있으면 build_and_emit_call_summary() 호출
    │       │
    │       ├─ MedicalRelevanceFilter().classify_turns(턴_텍스트_리스트)
    │       │   └─ 실시간 음성 필터링: 의료 관련 문장 분류 중...
    │       │   ├─ [0.850] 유지  환자는 의식이 없습니다
    │       │   ├─ [0.790] 유지  호흡이 얕습니다
    │       │   └─ [0.120] 제외  네 알겠습니다
    │       │
    │       ├─ structure_call_summary(필터링된_텍스트, llm_model)
    │       │   └─ SBAR 구조화 중... (qwen3:14b)
    │       │   ├─ Ollama HTTP 호출
    │       │   └─ JSON 파싱
    │       │
    │       └─ data/summary_text/smoke_test_call_summary.json 저장
    │           └─ "JSON 파일 저장: data/summary_text/smoke_test_call_summary.json"
    │
    └─ 완료
```

---

## ✅ 예상 터미널 출력

### STT만 실행 (`--model base`)

```
모델 로딩 중... (base, device=auto, compute_type=auto)
모델 로딩 완료 (12.34초)
변환 중: smoke_test.wav
[00:00:00.320 -> 00:00:02.140] 환자는 의식이 없습니다
[00:00:02.140 -> 00:00:04.500] 호흡이 얕습니다
[00:00:04.500 -> 00:00:06.200] 맥박도 빨라요

텍스트 파일 저장: data/origin_text/smoke_test.txt
변환 소요 시간: 23.45초 (모델 로딩 제외)
```

### 전체 파이프라인 (`--summarize`)

```
모델 로딩 중... (base, device=auto, compute_type=auto)
모델 로딩 완료 (12.34초)
변환 중: smoke_test.wav
[00:00:00.320 -> 00:00:02.140] 환자는 의식이 없습니다
[00:00:02.140 -> 00:00:04.500] 호흡이 얕습니다
[00:00:04.500 -> 00:00:06.200] 맥박도 빨라요

텍스트 파일 저장: data/origin_text/smoke_test.txt
변환 소요 시간: 23.45초 (모델 로딩 제외)

실시간 음성 필터링: 의료 관련 문장 분류 중...
분류 완료 (0.23초, threshold=0.4)
  [0.850] 유지  환자는 의식이 없습니다
  [0.790] 유지  호흡이 얕습니다
  [0.620] 유지  맥박도 빨라요

SBAR 구조화 중... (qwen3:14b)

=== feature/dashboard로 전송될 JSON (현재는 터미널 출력만, 통신 미연동) ===
{
  "transcript": {
    "raw_text": "환자는 의식이 없습니다. 호흡이 얕습니다. 맥박도 빨라요",
    "filtered_text": "환자는 의식이 없습니다. 호흡이 얕습니다. 맥박도 빨라요",
    "language": "ko",
    "timestamp": "2026-08-01T14:30:00Z",
    "duration_sec": 6.2,
    "turns": [...]
  },
  "summary": {
    "patient": "",
    "mechanism": "",
    "symptoms": ["의식 저하", "호흡 얕음", "빠른 맥박"],
    "treatment": [],
    "severity_tag": "high",
    "required_department": "응급의학"
  },
  "source": "ai",
  "model_used": {
    "stt": "faster-whisper-base",
    "llm": "qwen3:14b"
  }
}

JSON 파일 저장: data/summary_text/smoke_test_call_summary.json
```

---

## 🧪 검증 단계

### 1️⃣ STT 결과 확인
```bash
# 텍스트 파일이 생겼는지 확인
ls -lh data/origin_text/smoke_test.txt

# 내용 확인
cat data/origin_text/smoke_test.txt
# 예상: "환자는 의식이 없습니다 호흡이 얕습니다 맥박도 빨라요"
```

### 2️⃣ 필터링 + LLM 결과 확인
```bash
# JSON 파일이 생겼는지 확인 (--summarize 사용 시)
ls -lh data/summary_text/smoke_test_call_summary.json

# JSON 내용 확인 (가독성 좋게)
python -m json.tool data/summary_text/smoke_test_call_summary.json | head -50

# 또는 cat
cat data/summary_text/smoke_test_call_summary.json | python -m json.tool
```

### 3️⃣ 각 파일 크기 비교
```bash
ls -lh data/live_audio/smoke_test.wav data/origin_text/smoke_test.txt data/summary_text/smoke_test_call_summary.json

# 예상:
# -rw-r--r--  1 user  staff  160K Aug  1 21:50 data/live_audio/smoke_test.wav
# -rw-r--r--  1 user  staff  2.1K Aug  1 21:55 data/origin_text/smoke_test.txt
# -rw-r--r--  1 user  staff  1.8K Aug  1 21:55 data/summary_text/smoke_test_call_summary.json
```

---

## 🎯 Step 2의 의미

**이 단계는 "우리 코드가 필요 없다"는 것을 증명한다.**

```
Step 1: 마이크 → WAV 파일
Step 2: WAV 파일 → 기존 transcribe.py (재사용)
Step 3: 라이브 루프 + Step 2를 반복

즉, Step 3는 단순히 "Step 2를 N초마다 반복"하는 것일 뿐.
```

---

## ⚠️ Step 2에서 주의할 점

| 상황 | 해결책 |
|---|---|
| **Ollama 없음** | `--summarize` 빼고 STT만 실행. 또는 `ollama serve` 백그라운드 실행 |
| **GPU 없음** | `--device cpu --compute-type int8` (느리지만 가능) |
| **에러: "모델을 찾을 수 없음"** | `pip install faster-whisper` 재설치 |
| **JSON 파일이 비어있음** | Ollama 에러 (로그 확인) 또는 프롬프트 문제 |
| **필터링 결과가 모두 "제외"** | 의료용어가 부족. `filtering.py`의 threshold 0.4 낮추기 |

---

## 📝 Step 2의 코드 흐름 (transcribe.py 내부)

사용자가 이해해야 할 부분:

```python
# transcribe.py의 main() 함수
def main():
    args = parse_args()  # CLI 인자 파싱
    
    if not args.audio.exists():
        print(f"파일을 찾을 수 없습니다: {args.audio}")
        return
    
    # 핵심: transcribe() 함수 호출
    transcribe(
        audio_path=args.audio,
        model_size=args.model,      # "base", "small", "large-v3" 등
        language=args.language,      # "ko"
        device=args.device,          # "auto", "cpu", "cuda"
        compute_type=args.compute_type,  # "auto", "int8", "float32"
        do_summarize=args.summarize,  # --summarize 플래그
        llm_model=args.llm_model,    # "qwen3:14b"
    )

# transcribe() 함수 내부 흐름
def transcribe(...):
    # 1. 모델 로드
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    
    # 2. STT
    segments, info = model.transcribe(str(audio_path), language=language, vad_filter=True)
    
    # 3. 텍스트 파일 저장
    out_path = ORIGIN_TEXT_DIR / (audio_path.stem + ".txt")
    out_path.write_text(full_text, encoding="utf-8")
    
    # 4. --summarize 플래그가 있으면
    if do_summarize:
        build_and_emit_call_summary(...)  # 필터링 + LLM
```

---

## 🎓 Step 2 학습 포인트

**Step 2는 "새로 짜는" 단계가 아니다.**

대신:
- 기존 코드의 **CLI 인자**를 이해한다
- 기존 코드의 **출력 포맷**을 확인한다
- 기존 코드의 **파일 위치**를 알아본다

이 세 가지가 Step 3에서 라이브 루프를 만들 때 필수 정보가 된다.

