# voice-live 시작 가이드: 마이크 라이브 캡처 파이프라인 사용법

> 이 문서 하나만 읽으면 voice-live(Step 1~5) 전체가 무엇이고, 어떤 순서로
> 실행하며, 실제로 실행하면 무엇이 나오는지 알 수 있도록 정리했다. 각
> 단계의 더 깊은 개념 설명은 `voice-live-step{N}-detailed.md`, 실제 구현
> 시 발견한 이슈/실측 결과는 `voice-live-step{N}-result.md`를 참고.

---

## 🚀 빠른 시작 (환경 세팅 → 바로 실행까지 한 번에)

> 각 Step이 뭘 검증하는지 궁금하지 않고 "일단 지금 당장 라이브로 돌려보고
> 싶다"면 이 섹션만 순서대로 따라 하면 된다. 아래 각 명령의 자세한 설명과
> 중간 결과 확인법은 이 섹션 다음의 "2. 준비물"부터 "4. Step별로 순서대로
> 실행해보기"에 있다.

```bash
# 0) 저장소 루트로 이동 (아직 안 했다면)
cd AIRookie

# 1) Python 환경 준비 (최초 1회)
conda activate rookie                      # 없으면: conda create -n rookie python=3.11
pip install -r requirements.txt            # sounddevice/soundfile 포함 전체 의존성 설치

# 2) 마이크 권한 확인 (최초 1회, macOS)
#    처음 아래 명령을 실행하면 "터미널이 마이크에 접근하려고 합니다" 팝업이 뜬다 → 허용
#    (Ollama는 별도로 켜둘 필요 없음 — summarizer.py가 필요할 때 자동으로 설치/실행/모델 pull까지 처리함)

# 3) 마이크가 잘 잡히는지 5초짜리 스모크 테스트 (선택, Step 1)
#    --out을 생략하면 실행 시각(예: 2026_0801_2312.wav)으로 자동 저장된다
python mic_recorder.py --seconds 5

# 4) 바로 전체 라이브 파이프라인 실행 (Step 3~5가 합쳐진 최종 스크립트)
#    --session을 생략하면 실행 시각(예: 2026_0801_2312)이 세션 이름으로 자동 사용된다
#    실행 후 마이크에 대고 자유롭게 말하고, 끝나면 Ctrl+C
python live_transcribe.py --model base \
    --stt-interval 5 --sbar-interval 30 --llm-model qwen3:14b

# 5) 결과 확인 (세션 이름은 터미널 출력에 찍힌 값으로 바꿔서 확인 — 예: 2026_0801_2312)
cat data/live_text/<세션 이름>.txt                                  # 누적 STT 텍스트
python -m json.tool data/summary_text/<세션 이름>_call_summary.json # 최종 SBAR JSON
afinfo data/live_audio/<세션 이름>.wav                              # 전체 녹음 오디오 (인터벌마다 잘렸던 걸 이어붙일 필요 없이, 처음부터 하나의 파일로 누적 저장됨)
```

이게 전부다. `mic_recorder.py`(Step 1)는 마이크 자체가 잘 잡히는지
확인하는 선택적 스모크 테스트이고, `live_transcribe.py` 한 줄이 Step
3~5(라이브 재변환 + 의료 관련도 필터링 + SBAR 구조화)를 전부 수행하는
최종 실행 파일이다. `--session`을 지정하지 않으면 실행 시각을
`YYYY_MMDD_HHMM` 형식(예: `2026_0801_2312`)으로 자동 세션 이름을 만들어
텍스트/오디오/JSON 파일명에 일관되게 사용한다. Step 2는 별도 코드 없이
기존 `transcribe.py`로 Step 1 결과물을 검증하는 단계라 "빠른 시작"에서는
생략했다(궁금하면 아래 Step 2 섹션 참고).

---



## 1. 이게 뭔가요?

기존 GoldenLink 음성 파이프라인(`transcribe.py`)은 **이미 완성된 오디오
파일**을 입력받아 한 번에 처리하는 배치 방식이다.

```bash
python transcribe.py 녹음파일.mp3 --summarize
```

**voice-live**는 이 파이프라인을 **마이크로 실시간에 가깝게** 확장한
것이다. 사람이 말하는 동안 계속 텍스트가 갱신되고, 주기적으로 SBAR
(의료 정보 구조화) JSON이 자동 생성된다.

### 왜 "실시간에 가깝게"라고 표현하나요?

STT 엔진(Whisper)은 **완결된 오디오 전체**를 한 번에 처리하는 배치
API라서, 단어가 들어올 때마다 바로바로 텍스트를 뱉어주는 진짜 스트리밍
방식이 아니다. 그래서 voice-live는 다음과 같은 방식으로 "라이브처럼"
동작하게 만든다:

> 마이크로 계속 녹음하면서, **몇 초마다 그 시점까지 녹음된 오디오
> 전체를 다시 통째로 Whisper에 넣어 재변환**한다. 새로 생긴 부분만
> 화면에 보여준다.

완벽한 실시간 스트리밍은 아니지만("정직한 제약"으로 남겨둠), 몇 초
단위로 갱신되는 라이브 화면 효과는 충분히 만들어낸다.

### 전체 흐름 한눈에 보기

```
마이크로 계속 녹음
   │
   ├─ 5초마다: 지금까지 녹음된 전체를 다시 STT (재변환)
   │           → 새로 나온 문장만 화면 출력 + 텍스트 파일에 저장
   │
   ├─ (같은 사이클) 지금까지의 모든 문장을 "의료 관련도" 재채점
   │           → [점수] 유지/제외 로 화면에 표시
   │
   ├─ 20초마다: "유지"된 문장들만 모아서 LLM에게 SBAR 구조화 요청
   │           → JSON 파일로 저장 (환자정보, 증상, 처치, 중증도 등)
   │
   └─ Ctrl+C로 종료 시: 마지막으로 한 번 더 SBAR 생성 (최종 요약)
```

---



## 2. 준비물



### 2.1 Python 환경

이 저장소는 `rookie`라는 conda 환경(Python 3.11)을 기준으로 검증되었다.

```bash
conda activate rookie
```



### 2.2 새로 추가된 패키지 설치 (한 번만)

Step 1에서 마이크 캡처를 위해 `sounddevice`, `soundfile`이
`requirements.txt`에 추가되었다. 아직 설치하지 않았다면:

```bash
pip install -r requirements.txt
# 또는 개별 설치:
pip install sounddevice==0.5.5 soundfile==0.14.0
```



### 2.3 macOS 마이크 권한

처음 실행 시 "터미널이 마이크에 접근하려고 합니다" 팝업이 뜬다. **허용**을
눌러야 한다. 놓쳤다면: `시스템 설정 > 개인정보 보호 및 보안 > 마이크`에서
사용 중인 터미널 앱(Terminal, iTerm 등)에 권한을 직접 켜주면 된다.

### 2.4 (Step 5를 쓰려면) Ollama — 별도로 켜둘 필요 없음

SBAR 구조화는 로컬 LLM(Ollama)을 호출하지만, `ollama serve`**를 미리
실행해둘 필요가 없다.** `summarizer.py`가 LLM을 호출하기 직전에
`ollama_bootstrap.ensure_ollama_ready()`를 자동으로 호출해서:

1. `ollama` 바이너리가 없으면 Homebrew로 설치 시도
2. 서버가 꺼져 있으면 백그라운드로 `ollama serve` 자동 실행
3. 지정한 모델(`--llm-model`, 기본 `qwen3:14b`)이 없으면 자동 `pull`

까지 전부 알아서 처리한다. 즉 `python live_transcribe.py --session ... --sbar-interval 20`을 그냥 실행하면 SBAR 생성 시점에 필요한 걸 스스로
준비한다.

**실측**: 서버를 완전히 꺼둔 상태에서 `ensure_ollama_ready("qwen3:14b")`를
호출해보니 "Ollama 서버가 꺼져 있어 백그라운드로 실행합니다" 메시지와
함께 1초 만에 서버가 뜨고 준비 완료로 확인되었다(모델은 이미 pull되어
있던 상태 — 처음 pull하는 모델이라면 크기에 따라 수 분~수십 분 걸릴 수
있다).

> 다만 Homebrew가 없는 환경(Linux 등)에서는 자동 설치가 불가능해 안내
> 메시지만 뜨고 예외가 발생한다 — 그 경우에만 [https://ollama.com](https://ollama.com) 에서
> 수동 설치가 필요하다.

---



## 3. 새로 생긴 파일들


| 파일                   | 역할                                          |
| -------------------- | ------------------------------------------- |
| `mic_recorder.py`    | 마이크 녹음 모듈. `MicRecorder` 클래스 + 스모크 테스트용 CLI |
| `live_transcribe.py` | 실제로 사용할 라이브 오케스트레이터. 녹음+재변환+필터링+SBAR를 모두 수행 |


`transcribe.py`, `filtering.py`, `summarizer.py`, `schema.py`는 **기존
그대로**다 — voice-live는 이 파일들을 고치지 않고 그대로 재사용한다.

---



## 4. Step별로 순서대로 실행해보기



### Step 1 — 마이크가 잘 잡히는지만 확인 (약 10초)

가장 먼저, STT/필터링/LLM 전부 빼고 "마이크 녹음 자체가 되는가"만
확인한다.

```bash
python mic_recorder.py --seconds 5 --out data/live_audio/smoke_test.wav
```

**5초 동안 마이크에 대고 아무 말이나 해본다.** (조용히 있으면 무음 파일이
생성되는데, 그것도 정상 동작이다 — Step 2에서 무음 파일이 왜 안전하게
처리되는지 확인 가능.)

**실행 결과 예시:**

```
녹음 시작 (5.0초)... 마이크에 대고 말하세요.
녹음 완료: data/live_audio/smoke_test.wav (5.0초)
```

**확인 방법:**

```bash
ls -la data/live_audio/smoke_test.wav
afinfo data/live_audio/smoke_test.wav   # macOS 내장 도구: 길이/샘플레이트 확인
```

`afinfo` 출력에서 `16000 Hz`, `1 ch`(모노)가 보이면 정상이다.

> 💡 **실제로 테스트해보니**: 요청한 5.0초와 실제 녹음 길이가 미세하게
> 다를 수 있다(예: 4.86초). 마이크 스트림이 켜지는 데 걸리는 아주 짧은
> 지연 때문인데, 이후 단계들은 "정확히 N초"가 아니라 "그때까지 녹음된
> 만큼"을 기준으로 동작하므로 문제되지 않는다. 자세한 내용은
> `voice-live-step1-result.md` 참고.

---



### Step 2 — 그 녹음 파일이 기존 파이프라인에서도 잘 돌아가는지 확인 (새 코드 없음)

Step 1에서 만든 파일을 **아무 수정 없이** 기존 배치 파이프라인에 넣어본다.

```bash
# STT만
python transcribe.py data/live_audio/smoke_test.wav --model base

# STT + 필터링 + LLM 구조화까지 전체
python transcribe.py data/live_audio/smoke_test.wav --model base --summarize
```

**실제 발화가 담긴 경우 실행 결과 예시:**

```
모델 로딩 중... (base, device=auto, compute_type=auto)
모델 로딩 완료 (8.84초)
변환 중: smoke_test.wav
[00:00:00.320 -> 00:00:02.140] 환자는 의식이 없습니다

텍스트 파일 저장: data/origin_text/smoke_test.txt
```

`--summarize`까지 실행하면 필터링 점수와 최종 SBAR JSON까지 터미널에
출력되고 `data/summary_text/smoke_test_call_summary.json`에 저장된다.

> 💡 **실제로 테스트해보니**: 아무 말도 하지 않고 녹음했다면(무음 파일)
> STT 결과가 빈 텍스트가 되는데, 이때 `--summarize`를 붙이면 "구조화
> 실패: LLM 응답에서 JSON을 찾지 못했습니다" 메시지와 함께 **에러 없이
> 안전하게 종료**된다. 파이프라인이 예외 상황도 잘 처리한다는 뜻이라
> 오히려 좋은 신호다. 자세한 내용은 `voice-live-step2-result.md` 참고.

---



### Step 3 — 진짜 "라이브": 마이크를 계속 켜놓고 주기적으로 재변환 (신규 CLI)

여기서부터가 진짜 voice-live의 핵심이다. 마이크가 계속 켜진 채로, 5초마다
지금까지 말한 내용 전체를 다시 인식해서 화면에 새로 생긴 부분만 보여준다.

```bash
python live_transcribe.py --session my_test --model base --stt-interval 5
```

**실행하면서 자유롭게 말해본다.** 종료는 `Ctrl+C`.

**실행 결과 예시:**

```
모델 로딩 중... (base, device=auto, compute_type=auto)
모델 로딩 완료 (0.59초)

🎤 라이브 재변환 시작 (주기: 5초)
말하세요... Ctrl+C로 중지

[1차] 재변환 중... 누적 4.9초
[00:00:00.320] 환자는 의식이 없습니다
(재변환: 0.23초, 누적 텍스트: data/live_text/my_test.txt)

[2차] 재변환 중... 누적 10.5초
[00:00:04.500] 호흡이 얕습니다
(재변환: 0.19초, 누적 텍스트: data/live_text/my_test.txt)

🛑 녹음 중지 (Ctrl+C)

🎧 전체 녹음 오디오 저장: data/live_audio/my_test.wav

📊 세션 요약:
  총 시간: 10.5초
  총 턴: 2
  텍스트 파일: data/live_text/my_test.txt
```

**다른 터미널을 하나 더 열어서** 텍스트 파일이 실시간으로 커지는 것도
확인할 수 있다:

```bash
tail -f data/live_text/my_test.txt
```

**오디오 파일도 함께 저장된다.** `--stt-interval`마다 잘라서 재변환하는
건 STT 처리 단위일 뿐, 실제 녹음 자체는 세션 시작부터 끝까지 하나의
버퍼에 계속 누적된다. 그래서 인터벌로 잘린 조각들을 나중에 따로
이어붙일 필요가 없다 — 세션이 끝나는 시점(Ctrl+C)에 그 누적 버퍼
전체를 통째로 `data/live_audio/my_test.wav` 하나로 저장한다.

```bash
afinfo data/live_audio/my_test.wav   # 세션 전체 길이만큼의 오디오인지 확인
```

> 💡 **실제로 테스트해보니**: 조용한 환경에서도 VAD(음성 감지)가 배경
> 소음을 가끔 짧은 말소리로 오인식하는 경우가 있었다(예: "하하하하").
> 이건 버그가 아니라 VAD + 경량 STT 모델의 자연스러운 한계이며, Step 4의
> 필터링 단계가 이런 무의미한 오탐을 걸러주는 데 도움이 된다. 자세한
> 내용은 `voice-live-step3-result.md` 참고.

---



### Step 4 — 잡담과 의료 발화를 구분해서 보여주기

Step 3와 실행 명령은 동일하다. **내부적으로** `filtering.py`**가 추가되어**,
새로 인식된 문장마다 "의료 관련 발화인지" 점수와 함께 유지/제외 판정이
같이 출력된다.

```bash
python live_transcribe.py --session my_test2 --model base --stt-interval 5
```

**의료 관련 내용과 잡담을 섞어서 말해본다.** 예: "안녕하세요" (잡담) →
"환자가 의식이 없어요" (의료).

**실행 결과 예시:**

```
[1차] 재변환 중... 누적 10.5초
[00:00:05.360] 네 안녕하세요
  [0.306] 제외  네 안녕하세요

[2차] 재변환 중... 누적 16.9초
[00:00:12.900] 환자가 의식이 없어요
  [0.612] 유지  환자가 의식이 없어요
```

`[점수]`는 0~1 사이 값으로, 1에 가까울수록 의료 관련도가 높다는 뜻이다.
기본 기준선(threshold)은 0.4다.

> 💡 **실제로 테스트해보니**: 재변환 특성상, 이미 별개로 인식됐던 두
> 문장이 다음 재변환 사이클에서 어쩌다 하나의 문장으로 다시 인식되는
> 경우가 있었다. 이때 잡담이 의료 발화와 한 덩어리로 묶이면 "유지"
> 판정을 받을 수도 있다 — VAD 경계가 사이클마다 100% 고정되지 않기
> 때문에 생기는 현상이다(허용 오차로 남겨둔 설계). 순수 STT 판정
> 자체(잡담=제외, 의료=유지)는 정확하게 동작했다. 자세한 내용은
> `voice-live-step4-result.md` 참고.

---



### Step 5 — 주기적으로 SBAR JSON까지 자동 생성 (전체 파이프라인 완성)

이제 필터링된 문장들을 LLM에 보내 정식 SBAR(환자정보/증상/처치/중증도)
JSON을 주기적으로 만든다. STT는 5초마다, SBAR는 그보다 긴 주기(기본
20초)로 실행한다 — LLM 호출 비용이 크기 때문이다.

```bash
python live_transcribe.py --session my_test3 --model base \
    --stt-interval 5 --sbar-interval 20 --llm-model qwen3:14b
```

**실행 결과 예시 (Step 1~4의 모든 출력 + 아래가 추가됨):**

```
[SBAR 생성 중... (20초 경과)]

실시간 음성 필터링: 의료 관련 문장 분류 중...
분류 완료 (0.08초, threshold=0.4)
  [0.850] 유지  환자는 의식이 없습니다
  [0.790] 유지  호흡이 얕습니다

SBAR 구조화 중... (qwen3:14b)

=== feature/dashboard로 전송될 JSON (현재는 터미널 출력만, 통신 미연동) ===
{
  "transcript": { "filtered_text": "...", "turns": [...] },
  "summary": {
    "patient": "",
    "mechanism": "",
    "symptoms": ["의식 저하", "호흡 얕음"],
    "treatment": [],
    "severity_tag": "high",
    "required_department": "응급의학"
  },
  "source": "ai",
  "model_used": { "stt": "faster-whisper-base", "llm": "qwen3:14b" }
}

JSON 파일 저장: data/summary_text/my_test3_call_summary.json
```

**Ctrl+C로 종료하면** `=== 최종 통화 요약 (세션 종료) ===` 헤더와 함께
마지막 상태로 JSON이 한 번 더 저장된다. 최종 파일은 다음으로 확인:

```bash
python -m json.tool data/summary_text/my_test3_call_summary.json
```

> 💡 **실제로 테스트해보니**: 세션 중 첫 LLM 호출은 Ollama가 모델을
> 메모리에 새로 올려야 해서 눈에 띄게 느릴 수 있다(체감 1분 내외).
> 이후 호출부터는 훨씬 빨라진다. 또한, 필터링에서 "제외"된 문장은 실제로
> LLM 입력에서 빠지고 JSON의 `turns[].excludedFromSummary: true`로
> 표시되는 것도 실측으로 확인했다 — 필터링→구조화 연결이 라이브
> 루프에서도 기존 배치 파이프라인과 동일하게 작동한다는 뜻이다. 자세한
> 내용은 `voice-live-step5-result.md` 참고.

---



## 5. CLI 옵션 전체 정리



### `mic_recorder.py`


| 옵션          | 기본값                           | 설명                                          |
| ----------- | ----------------------------- | ------------------------------------------- |
| `--seconds` | `5.0`                         | 녹음할 시간(초)                                   |
| `--out`     | `data/live_audio/<실행 시각>.wav` | 저장 경로. 생략하면 실행 시각(`YYYY_MMDD_HHMM`)으로 자동 생성 |




### `live_transcribe.py`


| 옵션                | 기본값                             | 설명                                                     |
| ----------------- | ------------------------------- | ------------------------------------------------------ |
| `--session`       | `<실행 시각>` (예: `2026_0801_2312`) | 세션 이름. 생략하면 실행 시각으로 자동 생성되어 텍스트/오디오/JSON 파일명에 일관되게 사용됨 |
| `--model`         | `base`                          | Whisper 모델 크기 (`base`, `small`, `large-v3` 등)          |
| `--language`      | `ko`                            | 언어 코드                                                  |
| `--device`        | `auto`                          | 연산 장치 (`auto`/`cpu`/`cuda`, Mac은 항상 cpu로 동작)           |
| `--compute-type`  | `auto`                          | 연산 정밀도                                                 |
| `--stt-interval`  | `5`                             | 재변환 주기(초) — 짧을수록 반응은 빠르지만 CPU 사용량 증가                   |
| `--sbar-interval` | `20`                            | SBAR JSON 생성 주기(초) — `--stt-interval`의 배수로 지정 권장       |
| `--llm-model`     | `qwen3:14b`                     | SBAR 구조화에 쓸 Ollama 모델                                  |


---



## 6. 결과물이 저장되는 위치

```
data/
├── live_audio/       ← Step 1/3: 마이크로 녹음한 WAV 파일
│                        (Step 1 스모크 테스트 파일 + Step 3~5 세션 종료 시 저장되는
│                         "세션 처음부터 끝까지" 전체 오디오 1개, 인터벌 조각을 이어붙일 필요 없음)
├── live_text/         ← Step 3: 라이브 세션의 누적 STT 텍스트 (세션마다 1개 파일, 계속 갱신)
├── origin_text/       ← Step 2: 기존 배치 파이프라인이 생성한 STT 텍스트 (재사용, 변경 없음)
└── summary_text/      ← Step 5: SBAR JSON (배치/라이브 세션 결과 공존)
```

세션 이름(`--session`, 생략 시 자동 생성된 실행 시각)이 `live_audio/`,
`live_text/`, `summary_text/` 세 곳의 파일명에 공통으로 쓰이므로, 같은
세션의 오디오·텍스트·JSON을 파일명만으로 바로 짝지어 찾을 수 있다.

`data/` 폴더 전체가 `.gitignore`에 걸려 있어 저장소에는 올라가지 않는다.
새 파일이 생겨도 별도 gitignore 수정은 필요 없다.

---



## 7. 자주 겪을 수 있는 상황


| 상황                                       | 원인                                                                       | 해결                                                                                             |
| ---------------------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| 마이크 권한 팝업이 안 뜨고 조용히 실패                   | 이전에 권한을 거부한 적 있음                                                         | 시스템 설정 > 개인정보 보호 > 마이크에서 터미널 앱 권한 직접 켜기                                                        |
| STT 결과가 계속 비어있음                          | 실제로 마이크에 소리가 안 들어감 (무음)                                                  | 마이크에 더 가까이서 크게 말해보기. `mic_recorder.py`로 먼저 단독 테스트                                              |
| 조용한데도 이상한 말이 한두 번 인식됨                    | VAD가 배경 소음을 오탐                                                           | 정상적인 한계. Step 4 필터링이 대부분 걸러줌                                                                   |
| SBAR 생성이 안 됨 / "구조화 실패"                  | `ensure_ollama_ready()`가 자동 설치·실행·pull을 시도했지만 실패(Homebrew 없음, 네트워크 문제 등) | 에러 메시지 확인 후 `ollama list`로 서버·모델 상태 점검, 필요 시 [https://ollama.com](https://ollama.com) 에서 수동 설치 |
| 첫 SBAR 생성 시 "Ollama 서버가 꺼져 있어..." 메시지가 뜸 | 정상 동작 — `ensure_ollama_ready()`가 자동으로 서버를 띄우는 중                          | 별다른 조치 불필요, 몇 초 기다리면 계속 진행됨                                                                    |
| 첫 SBAR JSON 생성이 오래 걸림                    | Ollama가 모델을 처음 메모리에 로드                                                   | 정상. 같은 세션의 다음 SBAR부터는 빨라짐                                                                      |
| 시간이 갈수록 재변환이 느려짐                         | 매 사이클 누적 버퍼 전체를 재처리(설계상 트레이드오프)                                          | `--stt-interval`을 늘리거나(예: 10초), 짧게 세션을 끊어서 사용                                                  |


---



## 8. 지금 하지 않은 것 (Phase 3+, 향후 과제)

- **진짜 스트리밍 STT**: 지금은 매번 전체 버퍼를 재처리하는 방식. 통화가
길어질수록 처리 비용이 늘어난다. 롤링 윈도우나 스트리밍 지원 모델로
교체하면 개선 가능.
- **전화(SIP/텔레포니) 연동**: 지금은 마이크 하나만 지원. 실제 전화
연동이 필요해지면 `.docs/voice-live-streaming-design.md`에 정리된
5계층 추상화(ABC)로 전환 예정.
- **feature/dashboard 실시간 전송**: 지금은 JSON을 파일로 저장하고
터미널에 출력만 한다. WebSocket 연동은 별도 작업.

---



## 9. 더 깊이 알고 싶다면


| 문서                                                   | 내용                                        |
| ---------------------------------------------------- | ----------------------------------------- |
| `voice-live-step1-detailed.md` ~ `step5-detailed.md` | 각 단계의 개념 설명 + 구현 가이드 (구현 전 참고용)           |
| `voice-live-step1-result.md` ~ `step5-result.md`     | 실제로 구현하고 테스트하며 발견한 것들 (실측 데이터, 이슈, 원인 분석) |
| `voice-live-streaming-design.md`                     | Phase 3+ 전화 연동을 위한 5계층 추상화 참고 설계          |


이 문서(`voice-live-getting-started.md`)는 위 문서들의 "요약 + 실행
순서" 버전이다. 더 깊이 이해하고 싶다면 각 Step의 `-detailed.md`와
`-result.md`를 함께 읽는 것을 권장한다.