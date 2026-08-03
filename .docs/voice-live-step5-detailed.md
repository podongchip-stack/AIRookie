# Step 5 상세 가이드: SBAR JSON 주기적 갱신 + 최종 요약

## 📚 개념: "라이브 데이터에서 의료 판단 JSON 생성"

Step 1~4는 **텍스트 처리**에만 집중했다. STT, 필터링, 의료/비의료 판정.

Step 5는 **필터링된 의료 텍스트를 실제 의료 정보 JSON(SBAR 포맷)으로 구조화**한다.

```
Step 4 출력 (텍스트):
  환자는 의식이 없습니다
  호흡이 얕습니다
  맥박도 빨라요

Step 5 출력 (JSON):
{
  "summary": {
    "patient": "",
    "mechanism": "",
    "symptoms": ["의식 저하", "호흡 얕음", "빠른 맥박"],
    "treatment": [],
    "severity_tag": "high",
    "required_department": "응급의학"
  }
}
```

---

## 🔄 Step 5의 "주기적 갱신"

Step 3에서 텍스트를 "주기적으로 갱신"했듯이, Step 5도 **주기적으로 JSON을 생성한다**.

```
마이크 계속 녹음 중
│
├─ 0초:    5초 누적 → JSON 생성 1회 (20초 주기)
├─ 5초:    10초 누적 (텍스트만 갱신)
├─ 10초:   15초 누적 (텍스트만 갱신)
├─ 15초:   20초 누적 (텍스트만 갱신)
├─ 20초:   25초 누적 → JSON 생성 2회 (20초 주기)
│          (이전 JSON과 비교해서 symptoms 추가되었나? severity 올랐나?)
└─ ...
```

**효율성:**
- STT: 5초마다 (텍스트 스트리밍)
- 필터링: 5초마다 (필터링된 텍스트)
- LLM: **20초마다** (JSON 생성, 비용 큼)

---

## 🧠 LLM 구조화: "기존 함수 그대로 재사용"

Step 5에서 할 일은 **새로 만드는 게 아니라, 기존 `transcribe.py`의 함수를 재호출하는 것**.

```python
# transcribe.py에 이미 있는 함수
def build_and_emit_call_summary(
    full_text: str,
    turn_texts: list[str],
    turn_offsets: list[float],
    duration_sec: float,
    language: str,
    model_size: str,
    llm_model: str,
    audio_path: Path,
) -> None:
    """기존 배치 파이프라인에서 사용하는 함수"""
    
    # 1. 필터링 (이미 했으니 스킵)
    # 2. LLM 호출
    structured = structure_call_summary(filtered_text, llm_model)
    # 3. JSON 조립 및 저장
    message = CallSummaryMessage(...)
    summary_path.write_text(output_json, encoding="utf-8")
```

Step 5에서 우리가 할 일:

```python
# live_transcribe.py에서
from transcribe import build_and_emit_call_summary

# 20초마다
if iteration % (sbar_interval_sec // stt_interval_sec) == 0:
    build_and_emit_call_summary(
        full_text=" ".join(all_turn_texts),
        turn_texts=all_turn_texts,
        turn_offsets=all_turn_offsets,
        duration_sec=elapsed,
        language=language,
        model_size=model_size,
        llm_model=llm_model,
        audio_path=LIVE_AUDIO_DIR / f"{session}.wav"  # 실제 파일 불필요
    )
```

---

## 🎯 Step 5: live_transcribe.py 수정

Step 3, 4 코드에 다음을 추가.

### 추가할 import

```python
from transcribe import build_and_emit_call_summary
```

### 루프 설정 (루프 전)

```python
recorder = MicRecorder()
recorder.start()

relevance_filter = MedicalRelevanceFilter()

# ← 여기 추가
sbar_interval_sec = 20  # SBAR 생성 주기 (초)
sbar_iterations = sbar_interval_sec // stt_interval_sec  # 몇 사이클마다?
# 예: sbar_interval_sec=20, stt_interval_sec=5 → 4사이클마다
```

### 루프 내 (각 사이클 말미)

```python
# Step 3, 4의 기존 코드 다음에 추가

# SBAR 주기적 갱신 (20초마다)
if iteration % sbar_iterations == 0 and iteration > 0:
    print(f"\n[SBAR 생성 중... ({iteration * stt_interval_sec}초)]")
    
    try:
        build_and_emit_call_summary(
            full_text=" ".join(all_turn_texts),
            turn_texts=all_turn_texts,
            turn_offsets=all_turn_offsets,
            duration_sec=elapsed,
            language=language,
            model_size=model_size,
            llm_model="qwen3:14b",  # 기본값
            audio_path=LIVE_AUDIO_DIR / f"{session}.wav"
        )
    except Exception as e:
        print(f"❌ SBAR 생성 실패: {e}")
```

### 종료 처리 (finally)

```python
finally:
    recorder.stop()
    
    # 최종 SBAR 생성 (Ctrl+C 직후)
    if all_turn_texts:
        print("\n=== 최종 통화 요약 (세션 종료) ===")
        try:
            build_and_emit_call_summary(
                full_text=" ".join(all_turn_texts),
                turn_texts=all_turn_texts,
                turn_offsets=all_turn_offsets,
                duration_sec=elapsed,
                language=language,
                model_size=model_size,
                llm_model="qwen3:14b",
                audio_path=LIVE_AUDIO_DIR / f"{session}.wav"
            )
        except Exception as e:
            print(f"❌ 최종 SBAR 생성 실패: {e}")
```

---

## ✅ Step 5 실행 및 검증

### 준비
```bash
# Ollama 서버 실행 (별도 터미널)
ollama serve

# (또는 이미 실행 중이면 skip)
ollama list  # qwen3:14b 확인
```

### 실행
```bash
python live_transcribe.py --session live_test3 --model base \
    --stt-interval 5 --sbar-interval 20 --llm-model qwen3:14b
```

### 예상 터미널 출력

```
모델 로딩 중... (base, device=auto, compute_type=auto)
모델 로딩 완료 (10.23초)

🎤 라이브 재변환 시작 (주기: 5초)
말하세요... Ctrl+C로 중지

[1차] 재변환 중... 누적 5.2초
[00:00:00.320] 환자는 의식이 없습니다
  [0.850] 유지  환자는 의식이 없습니다
[00:00:02.140] 호흡이 얕습니다
  [0.790] 유지  호흡이 얕습니다
[00:00:04.500] 맥박도 빨라요
  [0.820] 유지  맥박도 빨라요
(재변환: 2.34초, 누적 텍스트: data/live_text/live_test3.txt)

[2차] 재변환 중... 누적 10.5초
(아직 새 세그먼트 없음)
(재변환: 2.38초, 누적 텍스트: data/live_text/live_test3.txt)

[3차] 재변환 중... 누적 15.8초
(아직 새 세그먼트 없음)
(재변환: 2.41초, 누적 텍스트: data/live_text/live_test3.txt)

[4차] 재변환 중... 누적 20.2초
[00:00:06.200] 의식이 계속 저하되고 있습니다
  [0.880] 유지  의식이 계속 저하되고 있습니다

[SBAR 생성 중... (20초)]
실시간 음성 필터링: 의료 관련 문장 분류 중...
분류 완료 (0.15초, threshold=0.4)
  [0.850] 유지  환자는 의식이 없습니다
  [0.790] 유지  호흡이 얕습니다
  [0.820] 유지  맥박도 빨라요
  [0.880] 유지  의식이 계속 저하되고 있습니다

SBAR 구조화 중... (qwen3:14b)

=== feature/dashboard로 전송될 JSON (현재는 터미널 출력만, 통신 미연동) ===
{
  "transcript": {
    "raw_text": "...",
    "filtered_text": "환자는 의식이 없습니다 호흡이 얕습니다 맥박도 빨라요 의식이 계속 저하되고 있습니다",
    "language": "ko",
    "timestamp": "2026-08-01T14:30:00Z",
    "duration_sec": 20.2,
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

JSON 파일 저장: data/summary_text/live_test3_call_summary.json

[5차] 재변환 중... 누적 25.5초
...

🛑 녹음 중지 (Ctrl+C)

=== 최종 통화 요약 (세션 종료) ===
실시간 음성 필터링: 의료 관련 문장 분류 중...
분류 완료 (0.17초, threshold=0.4)
SBAR 구조화 중... (qwen3:14b)

=== feature/dashboard로 전송될 JSON (현재는 터미널 출력만, 통신 미연동) ===
{ ... (최종 JSON) ... }

JSON 파일 저장: data/summary_text/live_test3_call_summary.json

📊 세션 요약:
  총 시간: 25.5초
  총 턴: 4
  텍스트 파일: data/live_text/live_test3.txt
  내용: 환자는 의식이 없습니다 호흡이 얕습니다 맥박도 빨라요 의식이 계속 저하되고 있습니다
```

---

## 🧪 검증 단계

### 1️⃣ JSON 파일 생성 확인
```bash
ls -lh data/summary_text/live_test3_call_summary.json

# 예상: 20초마다 파일 갱신, Ctrl+C 후 1회 더
```

### 2️⃣ JSON 내용 확인
```bash
python -m json.tool data/summary_text/live_test3_call_summary.json | head -50

# 확인사항:
# - symptoms에 올바른 증상이 있는가?
# - severity_tag가 "high"인가? (의식 저하, 호흡 얕음 → high 맞음)
# - required_department가 "응급의학"인가?
```

### 3️⃣ JSON 파일 실시간 갱신 확인
```bash
# 터미널 1: 녹음 중
python live_transcribe.py --session live_test3 --model base --sbar-interval 20

# 터미널 2: 파일 갱신 감시
watch -n 1 'stat data/summary_text/live_test3_call_summary.json | grep Modify'
```

### 4️⃣ 여러 세션 동시 실행 (선택)
```bash
# 터미널 1
python live_transcribe.py --session session_A --sbar-interval 20

# 터미널 2
python live_transcribe.py --session session_B --sbar-interval 20

# 두 JSON이 독립적으로 갱신되는지 확인
ls -lh data/summary_text/
```

---

## ⚠️ Step 5의 주의사항

| 문제 | 원인 | 해결책 |
|---|---|---|
| **Ollama 에러** | `ollama serve` 미실행 | 별도 터미널에서 Ollama 시작 |
| **LLM이 느림** | 첫 호출 (모델 로드) | 첫 호출은 느림, 2번째부터 빠름 |
| **JSON이 비어있음** | LLM 프롬프트 에러 | summarizer.py의 STRUCTURE_SYSTEM_PROMPT 확인 |
| **symptoms가 중복** | 필터링된 텍스트 누적 | 정상 (매번 전체 텍스트로 재생성) |
| **severity_tag이 변함** | 누적 텍스트가 달라짐 | 정상 (새 증상 추가되면 재평가) |

---

## 🎓 Step 5 핵심 포인트

1. **기존 함수 재사용**: `build_and_emit_call_summary()`를 매번 호출
2. **주기적 갱신**: 같은 JSON 파일에 덮어쓰기 (매 주기마다 최신 상태)
3. **최종 요약**: Ctrl+C 시 1회 더 생성해 "최종 상태" 기록
4. **누적 텍스트**: 매번 모든 턴을 LLM에 전달 (전체 맥락 유지)
5. **스트레스 테스트**: 5분 이상 녹음하면 재변환 비용 증가 체감 가능

---

## 📊 성능 고려사항

```
STT (Whisper): O(n)
  - 누적 시간 n초 → 처리 시간 약 0.3~0.5초 (GPU 기준)
  - 5초마다 실행 → 점진적 슬로우다운

필터링: O(m)
  - 턴 개수 m개 → 처리 시간 약 0.01~0.05초
  - 비용 무시할 수 있음

LLM: O(k)
  - 필터링된 토큰 k개 → 처리 시간 약 1~3초
  - 20초마다 실행 → 큰 부하 없음
```

**예상 딜레이:**
```
20초 누적 + 5초 STT 재변환 + 2초 LLM SBAR
= 총 27초 (실시간이 아님, "준-라이브")
```

---

## 🚀 다음 단계 (Phase 3+)

Step 5 완료 후 가능한 개선:

1. **WebSocket 연동** - JSON을 feature/dashboard로 실시간 전송
2. **롤링 윈도우 STT** - 누적 버퍼 크기 제한 (성능 개선)
3. **진짜 스트리밍 STT** - Whisper 대신 스트리밍 모델 (완전 실시간)
4. **전화 시스템 연동** - 5계층 ABC 추상화 (AudioInput/STTStreamer/...)

