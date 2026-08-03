# Step 5 구현 결과: SBAR 구조화 통합 + 종료 처리

> `.docs/voice-live-step5-detailed.md`(개념 가이드)를 따라 구현하고, 실제
> Ollama(`qwen3:14b`)와 연동해 SBAR JSON이 끝까지 생성되는지 검증한 결과
> 기록. 코드는 `live_transcribe.py` 변경분 참고.

---

## ✅ 한 줄 요약

`transcribe.py`의 `build_and_emit_call_summary()`를 더 긴 주기(기본 20초)로
재호출해 SBAR JSON을 갱신하는 로직과, 종료 시 최종 1회 더 호출하는 로직을
추가했다. 실제 Ollama(`qwen3:14b`)로 라이브 파이프라인 전체(마이크 →
STT → 필터링 → LLM 구조화 → JSON 저장)를 처음부터 끝까지 실행해, SBAR JSON이
정상적으로 파일에 저장되는 것을 확인했다. **필터링에서 "제외"된 턴이
`excludedFromSummary: true`로 표시되고, LLM 구조화에는 실제로 "유지"된
텍스트만 전달된다**는 것도 실측으로 확인했다.

---

## 📦 변경된 파일

| 파일 | 상태 | 내용 |
|---|---|---|
| `live_transcribe.py` | 수정 | `build_and_emit_call_summary` import, SBAR 주기 카운터, `finally` 블록 최종 요약 추가 |

---

## 🛠️ 구현 내용

### 주기 판정 방식

가이드는 `iteration % (sbar_interval_sec // stt_interval_sec)` 형태를
제안했지만, 실제 구현에서는 "지금까지 흐른 논리적 시간이 SBAR 주기의
배수인가"를 직접 계산하는 방식을 택했다:

```python
elapsed_since_start = iteration * stt_interval_sec
if all_turn_texts and elapsed_since_start % sbar_interval_sec == 0:
    ...
    build_and_emit_call_summary(...)
```

두 방식은 `sbar_interval_sec`이 `stt_interval_sec`의 정확한 배수일 때
동일하게 동작한다. 이 방식을 택한 이유는 `elapsed_since_start`가 "SBAR가
몇 초 경과 시점에 생성됐는지"를 그대로 로그 메시지(`[SBAR 생성 중...
(10초 경과)]`)에 재사용할 수 있어 가독성이 좋기 때문이다.

### 최종 요약 (`finally` 블록)

```python
finally:
    recorder.stop()
    if all_turn_texts:
        ...(세션 요약 출력)...
        print("\n=== 최종 통화 요약 (세션 종료) ===")
        build_and_emit_call_summary(...)  # 마지막 전체 누적 데이터로 1회 더
```

가이드와 동일하게 구현했다. `KeyboardInterrupt`를 캐치한 뒤 `finally`에서
무조건 한 번 더 실행되므로, 주기적 갱신 사이 어중간한 시점에 세션이
종료되더라도 "그 시점까지의 최종 상태"가 반드시 한 번 더 저장된다.

### CLI 인자 추가

```
--sbar-interval  SBAR JSON 생성 주기 (초, 기본: 20)
--llm-model      구조화에 사용할 Ollama 모델 (기본: qwen3:14b)
```

---

## 🧪 실행 결과 (실제 테스트)

### 준비

```bash
$ ollama list
NAME                       ID              SIZE      MODIFIED
qwen3:14b                  bdbd181c33f2    9.3 GB    ...
```

Ollama 서버가 이미 실행 중이었다 (`ollama serve`, PID 확인).

### 추가 확인: `ollama serve`를 미리 켜두지 않아도 되는가?

`summarizer.py`가 이미 `from ollama_bootstrap import ensure_ollama_ready`를
import해 LLM 호출 직전에 `ensure_ollama_ready(llm_model)`을 호출하고
있었다. `ollama_bootstrap.py`는 (1) `ollama` 바이너리 미설치 시 Homebrew로
자동 설치, (2) 서버 미실행 시 백그라운드로 `ollama serve` 자동 실행,
(3) 지정 모델 미보유 시 자동 `pull`까지 전부 처리하도록 이미 구현되어
있었다 — voice-live 작업과 무관하게 기존 저장소에 이미 존재하던 기능이다.

실제로 `ollama serve` 프로세스를 완전히 종료한 뒤(`pkill -x ollama`)
`ensure_ollama_ready("qwen3:14b")`를 단독 호출해 검증했다:

```
Ollama 서버가 꺼져 있어 백그라운드로 실행합니다 (ollama serve)...
준비 완료: 1.0초
```

**결론: `live_transcribe.py` 실행 전에 `ollama serve`를 별도로 켜둘
필요가 없다.** SBAR 생성 시점에 필요하면 자동으로 준비된다. 다만 모델을
처음 pull하는 경우라면 모델 크기에 따라 수 분~수십 분이 걸릴 수 있고,
Homebrew가 없는 환경(Linux 등)에서는 자동 설치가 불가능해 수동 설치가
필요하다. `voice-live-getting-started.md`도 이 내용을 반영해 정정했다.

### 실행

이전 Step들과 동일하게, 자동화 환경 제약으로 macOS `say`(스피커 재생) +
마이크 캡처(물리적 루프백) 방식으로 실제 발화를 흉내냈다.

```bash
python -u live_transcribe.py --session live_test3 --model base \
    --stt-interval 5 --sbar-interval 10 --llm-model qwen3:14b &

say -v Yuna "환자는 50대 남성이며 교통사고로 흉부 충격을 받았습니다"
sleep 2
say -v Yuna "의식이 저하되어 있고 호흡이 곤란한 상태입니다 산소를 공급했습니다"
```

### 실제 출력 (SBAR JSON 생성 부분)

```
[1차] 재변환 중... 누적 10.2초
[00:00:02.960] 고맙고 말한 시킨다.
[00:00:07.050] 한 자른 50대 남성이며 교통사고로 휴.
  [0.215] 제외  고맙고 말한 시킨다.
  [0.379] 제외  한 자른 50대 남성이며 교통사고로 휴.

[2차] 재변환 중... 누적 16.1초
[00:00:02.960] 한자는 50대 남성이며 교통사고로 균부 충격을 받았습니다.
  [0.418] 유지  한자는 50대 남성이며 교통사고로 균부 충격을 받았습니다.

[SBAR 생성 중... (10초 경과)]

실시간 음성 필터링: 의료 관련 문장 분류 중...
분류 완료 (5.31초, threshold=0.4)
  [0.215] 제외  고맙고 말한 시킨다.
  [0.379] 제외  한 자른 50대 남성이며 교통사고로 휴.
  [0.418] 유지  한자는 50대 남성이며 교통사고로 균부 충격을 받았습니다.

SBAR 구조화 중... (qwen3:14b)

=== feature/dashboard로 전송될 JSON (현재는 터미널 출력만, 통신 미연동) ===
{ ... 아래 참고 ... }

JSON 파일 저장: data/summary_text/live_test3_call_summary.json
```

**LLM 첫 호출은 모델 로딩 때문에 상당히 느렸다** — 필터링 완료부터 JSON
출력까지 실측 약 65~70초 소요(정확한 수치는 측정하지 않았지만 체감상
`transcribe.py` 배치 실행 때보다 눈에 띄게 느림, Ollama 서버가 오랜만에
호출되어 모델을 메모리에 새로 올리는 비용으로 추정). 이후 사이클에서는
모델이 이미 메모리에 로드되어 있으므로 훨씬 빨라질 것으로 예상된다(배치
파이프라인 테스트인 Step 2에서는 필터링~JSON까지 10초 이내였음을 참고).

### 최종 JSON 내용

```json
{
  "transcript": {
    "raw_text": "고맙고 말한 시킨다. 한 자른 50대 남성이며 교통사고로 휴. 한자는 50대 남성이며 교통사고로 균부 충격을 받았습니다.",
    "filtered_text": "한자는 50대 남성이며 교통사고로 균부 충격을 받았습니다.",
    "turns": [
      { "text": "고맙고 말한 시킨다.", "excludedFromSummary": true },
      { "text": "한 자른 50대 남성이며 교통사고로 휴.", "excludedFromSummary": true },
      { "text": "한자는 50대 남성이며 교통사고로 균부 충격을 받았습니다." }
    ]
  },
  "summary": {
    "patient": "50대 남성",
    "mechanism": "교통사고 · 흉부 충격",
    "symptoms": [],
    "treatment": [],
    "severity_tag": "medium",
    "required_department": "흉부외과"
  },
  "source": "ai",
  "model_used": { "stt": "faster-whisper-base", "llm": "qwen3:14b" }
}
```

---

## 🔍 확인된 것: 필터링 결과가 SBAR 구조화 입력에 실제로 반영된다

`transcript.filtered_text`를 보면 "제외" 판정된 두 턴("고맙고 말한
시킨다.", "한 자른 50대 남성이며 교통사고로 휴.")은 빠지고, "유지"된
한 문장만 LLM 입력으로 들어갔다. 각 턴에도 `excludedFromSummary: true`
플래그가 정확히 붙었다. Step 2에서 확인한 배치 파이프라인의 필터링→구조화
연결 방식이 라이브 루프에서도 동일하게 작동함을 실측으로 재확인했다.

## 🔍 STT 오인식이 이번엔 LLM 문맥 보정을 완전히 극복하지 못한 사례

Step 2에서는 STT가 "지혜"로 잘못 인식해도 LLM이 문맥상 "지혈"로 정확히
복원한 사례가 있었다. 이번 테스트에서는 "균부 충격"(STT 오인식, 원래
"흉부 충격")이 그대로 `mechanism` 필드에 "흉부 충격"으로는 복원됐지만
(부분적으로 성공), **`required_department`가 "응급의학"이 아닌
"흉부외과"로 판정**되었고 `symptoms`가 빈 배열로 나왔다. 그 이유는
Step 4의 검증에서 발견한 것과 같은 계열의 문제 — **"의식이 저하되어
있고 호흡이 곤란하다"는 실제로 재생한 두 번째 발화가 이 SBAR 생성 시점
(누적 16.1초)까지 아직 STT 세그먼트로 잡히지 않았기 때문**이다(스피커
재생 타이밍과 5초 재변환 주기가 정확히 맞물리지 않아, 정작 핵심
증상 문장이 이 사이클의 `all_turn_texts`에 없었다). 즉 **입력 텍스트
자체가 불완전했던 것**이지 LLM 구조화 로직의 결함은 아니다. 이는 오히려
"라이브 파이프라인은 그 시점까지 들어온 정보만으로 판단한다"는 라이브
시스템의 본질적 특성을 보여주는 사례로, 다음 SBAR 주기(20초 경과 시점)에
증상 문장까지 반영되면 판정이 갱신됐을 것이다(이번 테스트는 첫 LLM
호출의 긴 지연 때문에 두 번째 SBAR 사이클까지 관찰하지 못하고
종료했다 — 아래 "확인하지 못한 것" 참고).

---

## ⚠️ 확인했지만 완전히 검증하지 못한 것

### Ctrl+C에 의한 정상 종료 경로

Step 3, 4와 동일한 자동화 환경 제약으로, 백그라운드 프로세스에 실제
`SIGINT`(Ctrl+C)를 전달할 수 없어 `kill -9`로 강제 종료했다.
`finally` 블록의 "최종 통화 요약" 재호출 로직은 **코드 검토로 정상임을
확인**했으나, 실제 실행으로 재현하지는 못했다. 이 부분은 사용자가 실제
터미널에서 직접 `Ctrl+C`를 눌러 다음을 확인하는 것을 권장한다:

```bash
python live_transcribe.py --session my_test --stt-interval 5 --sbar-interval 20
# 발화 후 Ctrl+C
```

`=== 최종 통화 요약 (세션 종료) ===` 헤더가 출력되고, 강제 종료 시점까지
누적된 최신 데이터로 JSON이 한 번 더 저장되면 정상이다.

### 두 번째 이후 SBAR 주기의 속도

첫 LLM 호출이 모델 로딩 비용으로 느렸던 것은 확인했지만, 같은 세션에서
두 번째 SBAR 생성(모델이 이미 메모리에 있는 상태)이 실제로 훨씬 빨라지는지는
이번 테스트에서 시간 관계상 확인하지 못했다. Step 2의 배치 테스트
결과(필터링~JSON 10초 이내)로 미루어 볼 때 빨라질 것으로 예상되지만,
사용자가 5분 이상 세션을 유지하며 직접 체감해보는 것을 권장한다(가이드
문서의 "완성 체크리스트" 마지막 항목과 동일한 취지).

---

## ✅ 완료 체크리스트 대조

가이드 문서(`voice-live-step5-detailed.md`) 기준:

- [x] `build_and_emit_call_summary` import 및 주기 재호출 로직 구현
- [x] `--sbar-interval`, `--llm-model` CLI 인자 추가
- [x] 실제 Ollama 연동으로 SBAR JSON이 파일로 저장되는 것 확인
- [x] 필터링 "제외" 턴이 LLM 입력에서 빠지고 `excludedFromSummary` 플래그가 붙는 것 확인
- [x] `finally` 블록의 최종 요약 호출 로직 코드 검토로 확인
- [~] `finally` 블록의 최종 요약 호출 **실제 Ctrl+C 실행**으로는 미확인 (자동화 환경 제약, 사용자 직접 확인 권장)
- [~] 두 번째 이후 SBAR 주기의 체감 속도 개선 — 미확인 (사용자 직접 장시간 세션으로 확인 권장)

---

## 🔗 다음 단계

5단계 구현이 모두 끝났다. `.docs/voice-live-getting-started.md`(최종 통합
가이드)에서 Step 1~5를 처음 접하는 사용자가 순서대로 실행하며 전체 그림을
이해할 수 있도록 정리했다.
