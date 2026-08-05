# feature/voice — 유튜브/음성 파일 STT 변환 및 로컬 LLM 요약 파이프라인

## 담당자

- 이승주 — 리드 개발자
- 곽호영 — 리드 개발자

## 목차

- [빠른 시작](#빠른-시작)
- [이 브랜치가 하는 일](#이-브랜치가-하는-일)
- [실행 방법](#실행-방법)
- [실시간 음성 필터링](#실시간-음성-필터링)
- [사용한 AI / 모델](#사용한-ai--모델)
- [입출력 데이터 포맷](#입출력-데이터-포맷)
- [폴더 구조](#폴더-구조)
- [알려진 제약사항 / TODO](#알려진-제약사항--todo)

---

## 빠른 시작

```bash
conda create -n rookie python=3.11
conda activate rookie
pip install -r requirements.txt
```

설치가 끝나면 마이크로 바로 시작해볼 수 있다:

```bash
python voice/call_capture.py
```

마이크로 통화를 녹음하다가 Ctrl+C를 누르면(통화 종료), 그 즉시 STT → 실시간 음성
필터링 → SBAR 구조화까지 자동으로 이어서 실행된다. 자세한 사용 예시는 아래
["3-2. 통화 캡처"](#3-2-통화-캡처--종료-시-자동-파이프라인-실행-권장) 참고.

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--session` | 자동 생성 | 세션(파일) 이름. 지정 안 하면 `YYYY_MMDD_HHMM` 형식 |
| `--model` | `medium` | Whisper 모델 크기 |
| `--language` | `ko` | 언어 코드 |
| `--device` | `auto` | 연산 장치 (`auto` / `cuda` / `cpu`) |
| `--compute-type` | `auto` | 연산 정밀도 |
| `--llm-model` | `qwen3:14b` | 구조화에 사용할 Ollama 모델 |

---

## 이 브랜치가 하는 일

음성 파일을 텍스트로 변환 → 실시간 음성 필터링(의료 관련 문장 분류) → SBAR 구조화
→ `feature/hub` 전달용 JSON 생성까지 이어지는 파이프라인. dashboard로는 직접
보내지 않고 `feature/hub`를 거쳐 전달된다.

**배치 처리**

| 파일 | 역할 |
| --- | --- |
| `transcribe.py` | 오디오 파일 → STT → (선택)필터링+SBAR 구조화 CLI |
| `audio_preprocess.py` | STT 직전 소음 제거·정규화·고주파 강조 |
| `filtering.py` | 발화 턴별 의료 관련성 분류 |
| `summarizer.py` | 필터링된 텍스트 → LLM SBAR 구조화 |
| `ollama_bootstrap.py` | Ollama 설치·서버 실행·모델 pull 자동화 |
| `schema.py` | 출력 JSON pydantic 스키마 |
| `add_noise.py` | 강건성 테스트용 노이즈 합성 |

**마이크 캡처**

| 파일 | 역할 |
| --- | --- |
| `call_capture.py` | **(권장)** 통화 캡처 → 종료 시 배치 파이프라인 자동 실행 |
| `mic_recorder.py` | 마이크 입력 버퍼 축적/WAV 저장 |
| `live_transcribe.py` | *(실험적)* N초 주기 재변환으로 실시간 자막처럼 보이게 함 |

> **`call_capture.py` vs `live_transcribe.py`**: 실제 운영 흐름은 "통화가 끝나면
> 그 통화 전체가 파일 하나가 되어 STT 파이프라인에 들어간다"이며, `call_capture.py`가
> 이를 그대로 구현한다. `live_transcribe.py`는 통화 중 실시간 자막이 필요할 때만
> 쓰는 별도의 실험적 구현으로, 재변환 사이클마다 세그먼트가 중복 출력될 수 있는
> 한계가 있다 (자세한 내용은 [알려진 제약사항](#알려진-제약사항--todo) 참고). 셋 다
> 출력 포맷은 [입출력 데이터 포맷](#입출력-데이터-포맷)에 정의된 동일한 JSON 스키마를
> 따른다.

---

## 실행 방법

### 1. 배치 처리: 사전 녹음 파일

**1-1. 테스트용 오디오 준비**

`data/origin_data/`에 처리할 오디오 파일(.wav, .mp3 등)을 넣는다.

<details>
<summary>소음 합성 테스트 데이터 만들기 (선택)</summary>

```bash
python add_noise.py data/origin_data/원본.mp3 10
```

STT/필터링이 소음 환경에서도 잘 동작하는지 확인하고 싶을 때 쓴다. 두 번째
인자(SNR dB)를 낮출수록 더 심한 소음이 섞인다 (예: 10=중간, 0=심함). 결과는
`data/origin_noise_data/`에 `원본_noisy10db.wav` 형태로 자동 저장된다
(`--output`으로 경로 직접 지정 가능).

</details>

**1-2. 음성 → 텍스트 변환 + 실시간 음성 필터링 + SBAR 구조화**

```bash
python transcribe.py data/origin_data/파일명.wav --summarize
# 노이즈 합성본을 돌릴 때는 origin_noise_data/ 안의 파일을 그대로 넣으면 된다
python transcribe.py data/origin_noise_data/파일명_noisy10db.wav --summarize
```

입력 오디오는 `origin_data/`든 `origin_noise_data/`든 상관없이 처리되고, 결과물은
파일명 기준으로 항상 같은 폴더에 모인다. `--summarize`를 빼면 STT까지만 하고 끝난다.

| 산출물 | 저장 위치 |
| --- | --- |
| STT 원문 텍스트 (`.txt`) | `data/origin_text/파일명.txt` |
| SBAR 구조화 JSON (`--summarize` 시) | `data/summary_text/파일명_call_summary.json` |

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--model` | `medium` | Whisper 모델 크기 (`tiny`/`base`/`small`/`medium`/`large-v3`) |
| `--language` | `ko` | 언어 코드 |
| `--device` | `auto` | 연산 장치 (`auto` / `cuda` / `cpu`) |
| `--compute-type` | `auto` | 연산 정밀도 |
| `--summarize` | (off) | 필터링 + SBAR 구조화까지 수행 |
| `--llm-model` | `qwen3:14b` | 구조화에 사용할 Ollama 모델 |

<details>
<summary>최초 실행 시 자동 다운로드되는 것들</summary>

`--summarize`를 쓸 때 Ollama를 미리 설치·실행·pull해둘 필요는 없다 (macOS +
Homebrew 기준). `ollama_bootstrap.py`가 필요한 걸 자동으로 준비한다 — 최초 1회는
Ollama 설치(brew) + `--llm-model`로 지정한 모델 다운로드 때문에 시간이 걸릴 수
있다. 자동 설치를 원치 않으면 미리 `ollama serve` / `ollama pull <모델명>`을 직접
실행해두면 그대로 재사용한다.

분류기(`filtering.py`)가 처음 실행될 때는 `paraphrase-multilingual-MiniLM-L12-v2`
모델을 Hugging Face에서 자동 다운로드한다 (약 470MB, 최초 1회).

</details>

### 2. 마이크 캡처

**2-1. 스모크 테스트: 마이크로 5초 녹음**

```bash
python voice/mic_recorder.py --seconds 5
```

```
녹음 시작 (5.0초)... 마이크에 대고 말하세요.
녹음 완료: data/voice_data/live_audio/2026_0803_2314.wav (5.0초)
```

마이크 권한 요청이 나면 시스템 설정 > 개인정보 보호 > 마이크에서 터미널 앱에
권한을 부여해야 한다 (macOS).

### 2-2. 통화 캡처 → 종료 시 자동 파이프라인 실행 (권장)

실제 운영 흐름("전화가 시작되고 끝나면, 그 통화 전체가 하나의 음성 파일이 되어
STT 파이프라인에 들어간다")을 그대로 구현한 진입점. 통화 중에는 녹음만 하고,
Ctrl+C(통화 종료)를 누른 시점에 한 번만 전체 오디오를 STT에 넣는다.

```bash
python voice/call_capture.py --session live_test1
```

<details>
<summary>실행 예시 출력 보기</summary>

```
통화 시작. 마이크에 대고 말하세요.
통화가 끝나면 Ctrl+C를 누르세요 (통화 종료 신호).

^C
통화 종료 (Ctrl+C)
녹음 저장: data/voice_data/origin_data/live_test1.wav

=== 파이프라인 시작: STT -> 실시간 음성 필터링 -> SBAR 구조화 ===
모델 로딩 중... (medium, device=auto, compute_type=auto)
모델 로딩 완료 (2.10초)
변환 중: live_test1.wav
[00:00:00.320 -> 00:00:04.140] 환자는 의식이 없습니다
텍스트 파일 저장: data/voice_data/origin_text/live_test1.txt

실시간 음성 필터링: 의료 관련 문장 분류 중...
분류 완료 (0.08초, threshold=0.4)
SBAR 구조화 중... (qwen3:14b)
구조화 완료 (3.42초)

=== feature/dashboard로 전송될 JSON (현재는 터미널 출력만, 통신 미연동) ===
{ "transcript": {...}, "summary": {...}, "model_used": {...} }

JSON 파일 저장: data/voice_data/summary_text/live_test1_call_summary.json
```

</details>

`transcribe.py`의 `transcribe()`를 그대로 호출하므로, 녹음 파일이
`data/voice_data/origin_data/`에 저장되고 이후 산출물 위치·JSON 형식은 사전
녹음 파일을 배치 처리할 때와 동일하다 (위 "1-2" 산출물 표 참고).

옵션은 [빠른 시작](#빠른-시작)의 표와 동일하다.

### 2-3. (실험적) 라이브 캡처 → 주기적 재변환 → 실시간 텍스트 추출

> ⚠️ **Whisper는 진정한 스트리밍 STT가 아니다.** 통화 중에도 텍스트가 실시간으로
> 갱신되는 것처럼 "라이브처럼 보이게" 만든 실험적 구현이다: 마이크를 계속
> 녹음하면서 N초마다 누적 버퍼 전체를 Whisper에 다시 넣어 재변환하고, 새로 나온
> 세그먼트만 출력한다. 이 방식의 특성상 재변환 사이클마다 세그먼트 경계가
> 흔들려 같은 발화가 다른 텍스트로 중복 출력될 수 있다 ([알려진 제약사항](#알려진-제약사항--todo)
> 참고). 통화 중 실시간 자막이 실제로 필요한 경우가 아니라면 2-2의
> `call_capture.py`를 쓰는 게 맞다.

```bash
python voice/live_transcribe.py --model medium --stt-interval 5 --sbar-interval 50
```

<details>
<summary>실행 예시 출력 보기</summary>

```
🎤 라이브 재변환 시작 (주기: 5초)
말하세요... Ctrl+C로 중지

[1차] 재변환 중... 누적 10.5초
[00:00:05.360] 환자가 의식이 없어요
  [0.627] 유지  환자가 의식이 없어요

[2차] 재변환 중... 누적 16.2초
[00:00:10.120] 호흡이 약해졌습니다
  [0.734] 유지  호흡이 약해졌습니다

[SBAR 생성 중... (20초 경과)]
실시간 음성 필터링: 의료 관련 문장 분류 중...
분류 완료 (0.08초, threshold=0.4)
SBAR 구조화 중... (qwen3:14b)

=== feature/hub로 전송될 JSON ===
{ "transcript": {...}, "summary": {...}, "model_used": {...} }

JSON 파일 저장: data/voice_data/summary_text/2026_0803_2314_call_summary.json
```

Ctrl+C로 중지하면, 마지막 재변환 주기 이후 아직 STT를 거치지 않은 구간을 종료
직전 한 번 더 재변환해 텍스트 누락을 방지한 뒤 최종 요약을 생성한다:

```
🛑 녹음 중지 (Ctrl+C)
🎧 전체 녹음 오디오 저장: data/voice_data/live_audio/2026_0803_2314.wav
📊 세션 요약:
  총 시간: 35.3초
  총 턴: 5
  ...

=== 최종 통화 요약 (세션 종료) ===
...
```

</details>

| 산출물 | 저장 위치 | 설명 |
| --- | --- | --- |
| 전체 라이브 녹음 WAV | `data/voice_data/live_audio/<세션명>.wav` | 인터벌 조각들을 누적한 전체 오디오 |
| 누적 STT 텍스트 | `data/voice_data/live_text/<세션명>.txt` | 매 재변환 사이클마다 업데이트 |
| SBAR 구조화 JSON | `data/voice_data/summary_text/<세션명>_call_summary.json` | 주기적(기본 20초) 갱신, Ctrl+C 후 최종 1회 |

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--session` | 자동 생성 | 세션 이름 (`YYYY_MMDD_HHMM` 형식) |
| `--model` | `medium` | Whisper 모델 크기 |
| `--stt-interval` | `5` | STT 재변환 주기(초) |
| `--sbar-interval` | `20` | SBAR JSON 생성 주기(초, stt-interval의 배수 권장) |
| `--llm-model` | `qwen3:14b` | 구조화에 사용할 Ollama 모델 |

**마이크 캡처 공통 특징**

- 배치 처리(`transcribe.py`)와 동일한 필터링·구조화 로직을 재사용한다 — 코드 중복 없음
- 마이크 권한, Ollama 자동 부트스트래핑 등은 배치 처리와 동일하게 자동 처리된다
- 실제 구급대원 통화 시나리오를 시뮬레이션하려면 `.docs/voice-live-getting-started.md` 참고 (Step 1~5 상세 가이드)

---

## 실시간 음성 필터링

STT 결과를 발화 턴(문장) 단위로 분리한 뒤, 각 턴이 의료 관련 내용인지 분류해서
잡담·인사말·통화 연결 발화를 요약 대상에서 제외하고, 의료 관련 문장만 LLM에
전달해 SBAR 형태로 구조화한다. CLAUDE.md의 "통화 내용 필터링·구조화 (AI: sLLM +
KM-BERT)" 항목을 구현한 것이다.

**분류 방식** (`filtering.py`)

라벨링된 학습 데이터가 없어 KM-BERT를 직접 파인튜닝하는 대신, 다국어 문장 임베딩
모델(`paraphrase-multilingual-MiniLM-L12-v2`)로 "의료 관련" 예시 문장들의 중심
벡터를 만들고, 각 발화 턴과의 코사인 유사도가 threshold(기본 0.4) 이상이면
의료 관련으로 분류한다. CLAUDE.md가 "경량 분류기 또는 KM-BERT" 중 하나를
허용하므로, 이는 그중 경량 분류기 선택지에 해당한다.

<details>
<summary>검증 예시 / 나중에 KM-BERT로 교체하는 경우</summary>

anchor 문장 vs 테스트 문장 코사인 유사도: 의료 관련 문장은 0.57~0.76, 잡담/인사말은
0.13~0.29로 나와 threshold 0.4로 명확히 구분됨을 확인함. 나중에 라벨 데이터가
쌓이면 `MedicalRelevanceFilter`를 KM-BERT 분류 헤드로 교체해도 호출부
(`transcribe.py`)는 바뀌지 않는다.

</details>

**원본 보존 원칙**

필터링에서 제외된 발화도 삭제하지 않는다. `transcript.raw_text`와
`transcript.turns`에는 모든 발화가 그대로 남고, 제외된 턴에만
`excludedFromSummary: true`가 붙는다. `transcript.filtered_text`(요약 입력값)와
`summary.*`(SBAR 구조화 결과)에만 의료 관련 발화가 반영된다.

**구조화** (`summarizer.py`)

필터링된 텍스트를 Ollama(`/api/generate`)에 전달해 `patient` / `mechanism` /
`symptoms` / `treatment` / `severity_tag` / `required_department` 필드를 가진
JSON으로 구조화한다. 응답에서 `<think>...</think>` 추론 태그를 제거하고 JSON
객체만 관대하게 추출해서 파싱한다. 파싱에 실패하면 예외를 던지고 파이프라인은
중단된다 (원본 텍스트 파일은 이미 저장된 상태라 데이터 손실은 없음).

<details>
<summary>왜 <code>format: "json"</code> 옵션을 안 쓰는가</summary>

`qwen3:14b`처럼 답하기 전에 내부적으로 "생각(thinking)"부터 하도록 학습된
추론형 모델에 Ollama의 JSON 문법 강제 디코딩을 같이 쓰면, 생각 과정과 문법
제약이 충돌해서 모델이 토큰 2개(`{}`)만 뱉고 즉시 포기해버리는 문제를 실제로
겪었다 (`summary`의 모든 필드가 빈 값으로 나옴). 프롬프트로만 JSON을 요청하고
응답 텍스트에서 파싱하는 지금 방식이 실제로 안정적으로 동작함을 확인함.

</details>

**오디오 파일만 있으면 끝까지 자동 실행** (`ollama_bootstrap.py`)

사용자가 Ollama를 미리 설치·실행·pull해둘 필요가 없다. `summarizer.py`가 LLM을
호출하기 직전에 `ensure_ollama_ready()`를 불러서 (1) `ollama` 바이너리가 없으면
Homebrew로 설치, (2) 서버가 안 떠 있으면 `ollama serve`를 백그라운드로 실행,
(3) 지정한 모델이 없으면 `ollama pull`까지 전부 자동으로 처리한다. macOS +
Homebrew 환경만 자동 설치를 지원한다 (임의의 설치 스크립트를 내려받아 실행하는
건 위험해서 배제).

<details>
<summary>검증 로그</summary>

이 저장소 개발 환경에서 실제로 검증함: Ollama 미설치 상태에서 `brew install
ollama` → 서버 자동 기동 → `qwen2.5:0.5b`(스모크 테스트용 소형 모델) 자동 pull
→ 실제 LLM 호출로 SBAR JSON 생성까지 전 과정이 라이브로 성공했다.
(`qwen2.5:0.5b`는 크기가 작아 추출 품질은 낮음 — 파이프라인 동작 검증용이고,
실제 사용 시엔 `--llm-model`로 `qwen3:14b` 등 정식 모델을 지정할 것.)

</details>

**알려진 한계**

- 화자 분리(diarization)가 아직 없어 모든 턴의 `speaker`는 `"미분리"`로 고정
- threshold 기반 분류기라 애매한 경계 문장은 오분류할 수 있음. 실제 통화 녹음으로 threshold 재조정하거나 KM-BERT로 교체하는 게 다음 단계
- **필터링보다 그 앞 단계인 STT 정확도가 병목이다.** "산소포화도", "심정지" 같은 의료 용어를 Whisper가 오인식하는 경우가 실제로 관찰됨 (예: "심정지가 왔었습니다" → "심정도 너무 왔었습니다"). `audio_preprocess.py`로 저비용 개선을 시도했지만 근본 해결에는 응급실 도메인 데이터 파인튜닝이 필요할 수 있음
- 통신(WebSocket으로 `feature/hub`에 실시간 전송)은 아직 미구현. 지금은 JSON을 터미널 출력 + 파일 저장까지만 한다
- macOS + Homebrew가 아닌 환경에서는 Ollama 자동 설치가 동작하지 않음. [ollama.com](https://ollama.com)에서 직접 설치 필요

---

## 사용한 AI / 모델

| 구분 | 모델 | 용도 |
| --- | --- | --- |
| STT | [Whisper medium](https://huggingface.co/Systran/faster-whisper-medium) (faster-whisper) | 음성 → 텍스트, `--model`로 변경 가능 |
| 의료 관련성 분류 | [paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) | 발화 턴 의료 관련성 분류 |
| 정보 구조화 | [Qwen3-14B](https://huggingface.co/Qwen/Qwen3-14B) (Ollama `qwen3:14b`) | 필터링 텍스트 → SBAR JSON, `--llm-model`로 변경 가능 |

> CLAUDE.md "핵심 AI 활용 원칙" 표 기준: **[x] AI 처리** / [ ] 규칙 기반

**개발 환경**: Python 3.11, faster-whisper / sentence-transformers / Ollama /
pydantic. 로컬 실행 (GPU 있으면 CUDA 12.x, macOS는 CTranslate2가 Metal/MPS
미지원이라 항상 CPU).

---

## 입출력 데이터 포맷

**입력**: 오디오 파일 (.wav 등) — 추후 실시간 스트림 입력으로 전환 예정

**출력**: `transcribe.py --summarize` 실행 시 터미널 출력 +
`data/summary_text/*_call_summary.json` 저장. `feature/hub`로 전달되는 JSON이며
dashboard로는 직접 보내지 않는다. `feature/dashboard`의 `CallSummaryMessage`
타입과 1:1 대응하되(`turns`/`required_department`는 원본 로그 표시용으로 확장한
필드), 실제 수신처는 `feature/hub`다 (CLAUDE.md "데이터 포맷 및 흐름" 참고).

```json
{
  "transcript": {
    "raw_text": "여보세요, 안녕하세요. 환자 50대 남성이고 교통사고 흉부 충격입니다...",
    "filtered_text": "환자 50대 남성이고 교통사고 흉부 충격입니다. 의식 저하 있고 호흡 곤란...",
    "language": "ko",
    "timestamp": "2026-07-28T14:32:31Z",
    "duration_sec": 42.3,
    "turns": [
      { "speaker": "미분리", "timestamp": "14:32:07", "text": "여보세요, 안녕하세요.", "excludedFromSummary": true },
      { "speaker": "미분리", "timestamp": "14:32:11", "text": "환자 50대 남성이고 교통사고 흉부 충격입니다..." }
    ]
  },
  "summary": {
    "patient": "50대 남성",
    "mechanism": "교통사고 · 흉부 충격",
    "symptoms": ["의식 저하", "호흡 곤란"],
    "treatment": ["산소 공급", "지혈 완료"],
    "severity_tag": "high",
    "required_department": "흉부외과"
  },
  "source": "ai",
  "model_used": {
    "stt": "faster-whisper-large-v3",
    "llm": "qwen3:14b"
  }
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `transcript.raw_text` | string | STT 원본 전문. 필터링 전 전체 발화, 삭제하지 않고 보존 |
| `transcript.filtered_text` | string | 필터링 후 남은 텍스트. 요약의 실제 입력값 |
| `transcript.language` | string | 언어 코드 |
| `transcript.timestamp` | string (ISO 8601) | 통화 시작 시각 (사전 녹음 파일 처리 특성상 근사값) |
| `transcript.duration_sec` | number | 통화 길이(초) |
| `transcript.turns` | array | 발화 턴별 원본 로그 (`speaker`/`timestamp`/`text`/`excludedFromSummary?`) |
| `summary.patient` | string | 환자 인적사항 요약 |
| `summary.mechanism` | string | 사고 기전 |
| `summary.symptoms` | string[] | 증상 목록 |
| `summary.treatment` | string[] | 처치 목록 |
| `summary.severity_tag` | `"high"` \| `"medium"` \| `"low"` | 중증도 |
| `summary.required_department` | string \| null | 필요 진료과 |
| `source` | `"ai"` | AI 처리 결과 고정값 |
| `model_used.stt` / `model_used.llm` | string | 실제 사용된 모델명 |

바이탈 필드는 포함하지 않는다 (환자 바이탈 정보는 더 이상 사용하지 않기로 결정됨).

**통신(전송) 상태**: `feature/hub`로의 실시간 전송은 아직 연동 전이다. 지금은
위 JSON을 터미널 표준 출력과 `data/summary_text/*_call_summary.json` 파일로만
내보낸다 — 통신 계층은 이 JSON을 그대로 보내기만 하면 되도록 분리해뒀다.

---

## 폴더 구조

```
AIRookie/
├── .gitignore
├── CLAUDE.md
├── README.md
├── requirements.txt
├── pull-all.sh
├── voice/                   (.gitignore로 제외 안 됨)
│   ├── add_noise.py         오디오에 노이즈 합성
│   ├── audio_preprocess.py  STT 직전 소음 제거/정규화/고주파 강조
│   ├── call_capture.py      마이크로 통화 캡처 → 종료 시 배치 파이프라인 자동 실행 (권장)
│   ├── filtering.py         의료 관련성 분류기
│   ├── live_transcribe.py   (실험적) 마이크 라이브 캡처 + 주기적 재변환
│   ├── mic_recorder.py      마이크 입력 버퍼 축적 (스모크 테스트용)
│   ├── ollama_bootstrap.py  Ollama 자동 설치/실행/모델 다운로드
│   ├── schema.py            Pydantic 스키마 (전송용 JSON)
│   ├── summarizer.py        필터링 텍스트 → LLM 구조화
│   └── transcribe.py        음성 파일 → STT 변환 + 필터링/구조화
└── data/                    (.gitignore로 저장소에는 안 올라감)
    └── voice_data/
        ├── origin_data/         원본 음성 파일 (직접 추가)
        ├── origin_noise_data/   add_noise.py로 노이즈 합성한 음성 파일
        ├── origin_text/         STT 원문 텍스트 (.txt)
        ├── summary_text/        SBAR 구조화 JSON (*_call_summary.json)
        ├── live_audio/          마이크 라이브 세션 녹음 WAV
        └── live_text/           라이브 세션 누적 STT 텍스트
```

모든 파이썬 코드는 `voice/` 폴더에 있으므로 상호 import(`from filtering import
...`)는 그대로 동작하며, 실행은 저장소 루트에서 `python voice/transcribe.py ...`
형태로 한다. 모든 데이터는 `data/voice_data/` 하위에 조직되어, 각 기능 모듈이
서로 다른 데이터 폴더를 가질 수 있도록 확장 가능한 구조다.

`youtube_downloader.py`는 실제로 쓰이지 않아 저장소에서 뺐다 (`.gitignore` 참고,
로컬에는 남아있음).

---

## 알려진 제약사항 / TODO

- macOS(Apple Silicon 포함)에서는 CTranslate2가 Metal/MPS GPU 가속을 지원하지 않아 항상 CPU로 동작. 기본값은 `medium`(정확도·속도 절충)이며, 더 정확한 결과가 필요하면 `--model large-v3`로 올릴 수 있으나 느려짐
- GPU 사용 시 NVIDIA CUDA 12.x 및 cuDNN 9 필요
- `data/voice_data/` 하위 전 폴더는 `.gitignore`에 포함되어 있어 오디오 원본과 변환 결과물은 저장소에 올라가지 않음
- 유튜브 콘텐츠 다운로드 시 저작권 및 유튜브 서비스 약관 준수 책임은 사용자에게 있음
- 실시간 음성 필터링/구조화 관련 제약사항은 위 ["알려진 한계"](#실시간-음성-필터링) 참고
- `audio_preprocess.py`의 소음 제거/정규화/고주파 강조 효과는 아직 실제 통화 샘플로 정량 검증되지 않음 (랜덤 신호로 예외 없이 동작하는 것만 확인)

<details>
<summary>call_capture.py / live_transcribe.py 관련 제약사항</summary>

**`call_capture.py`**
- 통화 중에는 STT를 돌리지 않고 녹음만 하므로, 실시간 자막/화면 표시가 필요한 용도에는 맞지 않음 (그런 용도는 `live_transcribe.py` 참고)
- 마이크 권한 설정(macOS 시스템 설정 > 개인정보 보호 > 마이크) 필수

**`live_transcribe.py` (실험적)**
- Whisper는 진정한 스트리밍 STT가 아니므로, 재변환 대상 길이가 늘어날수록 처리 비용이 증가함. 장기 녹음 시 느려질 수 있으니 모델 크기 조정 필요
- **재변환 사이클마다 세그먼트 경계(VAD 판정)가 다시 흔들려서, 같은 발화가 서로 다른 텍스트로 중복 출력되는 문제가 실제로 관찰됨** (예: "구급대원입니다"가 한 사이클엔 "구급대현입니다", 다음 사이클엔 "구구 대원입니다"로 다르게 인식되어 둘 다 텍스트에 남음) — 근본 해결에는 진짜 스트리밍 STT(예: whisper_streaming의 LocalAgreement 방식)로 교체 필요
- 마이크 권한 설정 필수
- Ollama 자동 부트스트래핑은 macOS + Homebrew 환경만 지원

</details>

---

## 추가사항
