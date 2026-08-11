# feature/voice — 음성 STT · 오인식 교정 · 로컬 LLM SBAR 구조화 파이프라인

> **폴더 구조 안내(모노레포)**: 이 저장소는 `feature/voice`·`feature/hub`·
> `feature/info`·`feature/dashboard`가 하나의 저장소를 공유하며, 각 브랜치는
> 자기 작업 폴더(`voice/`·`hub/`·`info/`·`dashboard/`)만 갖는다. **지금 이
> 브랜치에는 `voice/` 폴더만 있고 `hub/`·`info/`·`dashboard/`는 없다.** 만약
> 작업 중 낯선 폴더가 보인다면 `develop`을 머지했거나 다른 브랜치를 체크아웃한
> 상태라는 뜻이니, 실수로 만들어진 게 아닌지 걱정하지 않아도 된다.

## 담당자

- 이승주 — 리드 개발자
- 곽호영 — 리드 개발자

## 목차

- [빠른 시작](#빠른-시작)
- [이 브랜치가 하는 일](#이-브랜치가-하는-일)
- [실행 방법](#실행-방법)
- [STT 정확도 개선 / SBAR 구조화](#stt-정확도-개선--sbar-구조화)
- [오인식 사전 관리](#오인식-사전-관리)
- [사용한 AI / 모델](#사용한-ai--모델)
- [입출력 데이터 포맷](#입출력-데이터-포맷)
- [폴더 구조](#폴더-구조)
- [알려진 제약사항 / TODO](#알려진-제약사항--todo)

---

## 빠른 시작

```bash
cd voice
conda create -n rookie python=3.11
conda activate rookie
pip install -r requirements.txt
```

설치가 끝나면 마이크로 바로 시작해볼 수 있다 (아래 명령부터는 전부 `voice/` 안에서 실행):

```bash
python call_capture.py
```

마이크로 통화를 녹음하다가 Ctrl+C를 누르면(통화 종료), 그 즉시 STT → SBAR
구조화까지 자동으로 이어서 실행된다. 자세한 사용 예시는 아래
["2-2. 통화 캡처"](#2-2-통화-캡처--종료-시-자동-파이프라인-실행-권장) 참고.

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--session` | 자동 생성 | 세션(파일) 이름. 지정 안 하면 `YYYY_MMDD_HHMM` 형식 |
| `--model` | `medium` | Whisper 모델 크기 |
| `--language` | `ko` | 언어 코드 |
| `--device` | `auto` | 연산 장치 (`auto` / `cuda` / `cpu`) |
| `--compute-type` | `auto` | 연산 정밀도 |
| `--llm-model` | `qwen3:14b` | 구조화에 사용할 Ollama 모델 |
| `--beam-size` | `5` | Whisper 빔 서치 크기. 클수록 도메인 용어 인식 정확도↑, 속도↓ |

---

## 이 브랜치가 하는 일

음성 파일을 텍스트로 변환 → 오인식 교정 → SBAR 구조화 → `feature/hub` 전달용
JSON 생성까지 이어지는 파이프라인. dashboard로는 직접 보내지 않고 `feature/hub`를
거쳐 전달된다.

```
음성 → [STT] faster-whisper → 텍스트 → [교정] corrections.json 정확 일치
     → [구조화] Ollama sLLM → SBAR JSON → feature/hub
```

> STT 결과를 의료/비의료로 걸러내던 "실시간 음성 필터링"(`filtering.py`)은
> 제거됐고, 그 자리에 **오인식 교정**이 들어갔다. 문장을 뺄지 말지 고르는 대신
> 틀린 표기를 고치는 방향으로 바꾼 것이다 (판단 근거는 아래
> [STT 정확도 개선](#stt-정확도-개선--sbar-구조화) 참고).

**진입점은 3개**다. "통화가 끝나면 그 통화 전체가 파일 하나가 되어 STT에 들어간다"는
같은 흐름을 트리거 방식만 달리해 구현한 것이라, 셋 다 `transcribe.py`의
`transcribe()`로 수렴하고 출력 JSON 스키마도 동일하다.

| 진입점 | 언제 쓰나 | 통화 시작 / 종료 |
| --- | --- | --- |
| `app.py` | **실운영.** hub가 dashboard의 신호를 HTTP로 중계 | `POST /call/start` / `/call/end` |
| `call_capture.py` | 마이크로 직접 통화를 흉내내는 CLI 테스트 | 실행 / `Ctrl+C` |
| `transcribe.py` | 이미 녹음된 파일 배치 처리 | (해당 없음) |

파일별 역할과 호출 관계는 [폴더 구조](#폴더-구조) 참고.

---

## 실행 방법

### 1. 배치 처리: 사전 녹음 파일

**1-1. 테스트용 오디오 준비**

`data/origin_data/`에 처리할 오디오 파일(.wav, .mp3, .m4a 등)을 넣는다.

**1-2. 음성 → 텍스트 변환 + 오인식 교정 + SBAR 구조화**

```bash
python transcribe.py data/origin_data/파일명.wav --summarize
```

`--summarize`를 빼면 STT까지만 하고 끝난다 (교정·구조화는 건너뛴다).

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
| `--summarize` | (off) | SBAR 구조화까지 수행 |
| `--llm-model` | `qwen3:14b` | 구조화에 사용할 Ollama 모델 |
| `--beam-size` | `5` | Whisper 빔 서치 크기. 클수록 도메인 용어 인식 정확도↑, 속도↓ |
| `--no-correction` | (off) | 오인식 교정을 건너뛰고 STT 원문을 그대로 요약에 넘김 (교정 효과 비교용) |

<details>
<summary>최초 실행 시 자동 다운로드되는 것들</summary>

`--summarize`를 쓸 때 Ollama를 미리 설치·실행·pull해둘 필요는 없다 (macOS +
Homebrew 기준). `ollama_bootstrap.py`가 필요한 걸 자동으로 준비한다 — 최초 1회는
Ollama 설치(brew) + `--llm-model`로 지정한 모델 다운로드 때문에 시간이 걸릴 수
있다. 자동 설치를 원치 않으면 미리 `ollama serve` / `ollama pull <모델명>`을 직접
실행해두면 그대로 재사용한다.

</details>

### 2. 마이크 캡처

#### 2-1. 스모크 테스트: 마이크로 5초 녹음

```bash
python mic_recorder.py --seconds 5
```

```
녹음 시작 (5.0초)... 마이크에 대고 말하세요.
녹음 완료: data/voice_data/live_audio/2026_0803_2314.wav (5.0초)
```

마이크 권한 요청이 나면 시스템 설정 > 개인정보 보호 > 마이크에서 터미널 앱에
권한을 부여해야 한다 (macOS).

#### 2-2. 통화 캡처 → 종료 시 자동 파이프라인 실행 (권장)

실제 운영 흐름("전화가 시작되고 끝나면, 그 통화 전체가 하나의 음성 파일이 되어
STT 파이프라인에 들어간다")을 그대로 구현한 진입점. 통화 중에는 녹음만 하고,
Ctrl+C(통화 종료)를 누른 시점에 한 번만 전체 오디오를 STT에 넣는다.

```bash
python call_capture.py --session live_test1
```

<details>
<summary>실행 예시 출력 보기</summary>

```
통화 시작. 마이크에 대고 말하세요.
통화가 끝나면 Ctrl+C를 누르세요 (통화 종료 신호).

^C
통화 종료 (Ctrl+C)
녹음 저장: data/voice_data/origin_data/live_test1.wav

=== 파이프라인 시작: STT -> SBAR 구조화 ===
모델 로딩 중... (medium, device=auto, compute_type=auto)
모델 로딩 완료 (2.10초)
변환 중: live_test1.wav (beam_size=5)
[00:00:00.320 -> 00:00:04.140] 환자는 의식이 없습니다
텍스트 파일 저장: data/voice_data/origin_text/live_test1.txt

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

**마이크 캡처 공통 특징**

- 배치 처리(`transcribe.py`)와 동일한 STT/교정/구조화 로직을 재사용한다 — 코드 중복 없음
- 마이크 권한, Ollama 자동 부트스트래핑 등은 배치 처리와 동일하게 자동 처리된다

> 통화 **중** 실시간 자막을 내던 `live_transcribe.py`(N초마다 누적 버퍼를 통째로
> 재변환하는 실험적 구현)는 제거했다. Whisper가 진짜 스트리밍 STT가 아니라
> 재변환 사이클마다 세그먼트 경계가 흔들려 같은 발화가 다른 텍스트로 중복
> 출력되는 문제가 있었고, 실제 운영 흐름은 "통화가 끝나면 그 통화 전체가 파일
> 하나가 되어 STT에 들어간다"라 필요하지 않았다. dashboard의 실시간 자막은
> 브라우저 마이크로 처리한다.

#### 2-3. `app.py` — hub가 원격으로 트리거하는 실제 파이프라인

`call_capture.py`의 "녹음만 하다가 종료 시 배치 파이프라인 실행" 흐름을 Ctrl+C
대신 HTTP 요청(feature/hub가 중계하는 통화 시작/종료 신호)으로 트리거하도록
감싼 게 실제 운영 경로다. 이 프로세스 자체는 구급차 1대 전용이다 — 마이크가
그 구급차 장비 하나뿐이라 통화도 한 번에 하나만 가능하다. 여러 구급차를
지원하는 건 hub가 여러 대의 voice 인스턴스를 구분해 각자에게 신호를
중계해주는 방식으로 이뤄진다(feature/hub README.md 참고).

```bash
VOICE_APID=A0000001 VOICE_PORT=6000 python app.py
```

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `VOICE_APID` | (없음) | 이 voice 인스턴스가 담당하는 구급차 식별자. hub의 구급차 레지스트리(apid)와 일치해야 하며, 없으면 hub 자가등록 자체를 건너뛴다(단독 CLI 테스트용) |
| `VOICE_PORT` | `6000` | 이 인스턴스가 실제로 바인딩할 포트. 포트 배정표(hub=5001, info=5002 고정, voice=구급차마다 6000대)의 voice 몫 — 구급차 레지스트리의 `AmbulanceInfo.voicePort`와 같은 값으로 맞춰야 한다. 한 장비에서 여러 구급차를 흉내낼 땐 인스턴스마다 다르게 줘야 한다(안 그러면 포트 충돌) |
| `HUB_BASE_URL` | `http://127.0.0.1:5001` | hub 주소. 자가등록 요청 및 자기 IP 자동 탐지(이 주소로 나가는 인터페이스 확인) 둘 다에 쓰인다 |
| `VOICE_REGISTER_RETRY_SEC` | `5` | hub 자가등록 실패 시 재시도 간격(초) |
| `VOICE_STT_MODEL` / `VOICE_LANGUAGE` / `VOICE_DEVICE` / `VOICE_COMPUTE_TYPE` / `VOICE_LLM_MODEL` | `call_capture.py`의 CLI 기본값과 동일 | STT/구조화 파라미터 |

**동작 순서**
1. 서버가 뜨자마자(별도 백그라운드 스레드) 자기 IP를 자동 탐지해 hub의
   `POST /voice/register`로 자가등록한다. 구급차 노트북마다 와이파이/핫스팟 등
   네트워크가 달라 IP가 고정돼 있지 않아, Supabase 등에 미리 저장해두지 않고
   매번 실행 시점에 탐지한다(포트는 hub의 구급차 레지스트리에 이미 있음). hub가
   이 apid를 아직 모르면(feature/info가 구급차 정보를 아직 안 보냈으면) 실패하는데,
   `VOICE_REGISTER_RETRY_SEC`마다 계속 재시도하므로 순서를 엄격히 맞출 필요는 없다
2. `POST /call/start`로 오는 `caseId`를 세션에 기억해둔다
3. `POST /call/end`가 오면 녹음을 멈추고, 기억해둔 caseId를 그대로 실어
   배치 파이프라인(STT→SBAR→hub 전송)을 백그라운드 스레드로 실행한다
4. hub가 다시 정지된 경우를 대비해 caseId가 없어도(=CLI 단독 테스트 등)
   `transcribe.py`가 파일명 기반으로 자동 생성한 값을 대신 채운다

---

## STT 정확도 개선 / SBAR 구조화

**STT 도메인 프롬프트** (`transcribe.py`의 `STT_INITIAL_PROMPT`)

Whisper 호출 시 `initial_prompt`로 "이 통화가 어떤 종류의 대화인가"(119
구급대원이 병원 응급실에 환자 수용 가능 여부를 확인하는 통화라는 장르/구조)를
문장으로 흘려준다. 등장 어휘의 사전 확률을 도메인 쪽으로 기울이는 문맥 힌트일
뿐 강제 디코딩은 아니다. 구체적인 시나리오 어휘(교통사고, 흉부 충격 등)는
일부러 안 넣었다 — 테스트 샘플의 실제 발화를 보고 답을 역산해서 프롬프트에
끼워넣으면 일반화되는 개선이 아니라 그 샘플 하나에 대한 오버피팅이기 때문
(실제로 초기 버전은 이 실수를 했다가 되돌렸다 — `simulation3/pipeline.py`에는
아직 그 구버전이 남아있다). `beam_size`도 CLI(`--beam-size`, 기본 5)로 조정
가능하다.

**오인식 교정** (`text_postprocess.py` + `corrections.json`)

STT와 LLM 사이에 오인식 교정 단계가 있다. `corrections.json`에 등록된
"오인식 → 정답" 쌍과 **정확히 일치**하는 구간만 치환하고, 그 결과를 요약에
넘긴다. 등록하지 않은 말은 절대 건드리지 않으므로 **오교정이 구조적으로 발생할
수 없고**, 유사도 임계값 같은 튜닝 대상도 없다. 대신 **등록한 만큼만 잡힌다** —
통화 녹음에서 오인식을 발견할 때마다 사전에 한 줄씩 추가하는 것이 운영 방법이다.

정확 일치를 보되 실제 문장에서 걸리게 하려고 세 가지는 처리한다. (1) **조사·종결어미
분리** — `"재세동이"`는 `"이"`를 떼야 사전의 `"재세동"`에 걸리고, 치환 후 다시 붙여
`"제세동이"`가 된다. (2) **공백 정규화** — whisper가 `"번지 회"`처럼 띄어 쓸 수 있어
1~3어절 구간을 붙여서 조회한다. (3) **긴 구간 우선** — 겹치는 자리는 더 긴 구간이
가져간다.

사전 편집 규칙과 자체 점검 방법은 [오인식 사전 관리](#오인식-사전-관리) 참고.
사전 파일이 없거나 JSON이 깨져 있으면 교정만 건너뛰고 STT 원문을 그대로 요약에
넘긴다 — `app.py`는 상시 서버라 여기서 예외가 올라가면 그 통화를 통째로 잃는데,
교정은 정확도 보조 단계일 뿐이라 통화 처리를 막을 이유가 없다.

> 이 자리에는 원래 발화 턴을 의료/비의료로 분류하는 "실시간 음성
> 필터링"(`filtering.py`, 다국어 문장 임베딩 코사인 유사도 ≥ 0.4)이 있었다.
> 단어 오인식 자체를 고치지 못하는 데다 threshold가 실제 통화 데이터로 검증된
> 적이 없어 중요한 문장을 잘못 제외할 리스크가 있었고, `summarizer.py`의
> 프롬프트가 이미 잡담·인사말을 스스로 걸러낼 만큼 구체적이라 정확도에
> 기여한다는 근거가 없었다. 그래서 걷어내고 위 교정 방식으로 바꿨다.

**원본 보존 원칙**은 그대로다. `transcript.raw_text`와 `transcript.turns`에는
**교정 전** 발화가 그대로 남고, `transcript.filtered_text`에만 교정 결과가 들어간다
(= LLM에 실제로 들어간 입력). 개별 턴의 `excludedFromSummary`는 필터링 전용
필드라 이제 채워지는 일이 없다 (스키마 필드 자체는 dashboard 타입과 1:1 대응이라
삭제 시 파급력이 커서 보류 중).

**구조화** (`summarizer.py`)

STT 결과 텍스트를 Ollama(`/api/generate`)에 전달해 `patient` / `mechanism` /
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
- **STT 정확도가 여전히 병목이다.** "산소포화도", "심정지" 같은 의료 용어를 Whisper가 오인식하는 경우가 실제로 관찰됨 (예: "심정지가 왔었습니다" → "심정도 너무 왔었습니다"). 소음 제거·정규화·고주파 강조 형태의 신호 전처리(`audio_preprocess.py`)를 시도했으나 실제 통화 녹음 3건으로 검증한 결과 개선 효과가 없었고 일부는 오히려 오인식을 유발해(`구급대원`→`9급대원`) 제거함
  - `STT_INITIAL_PROMPT`(위 참고)로 일부 오류(`수형 가능`→`수용 가능`, `진조 가능`→`진료 가능`)는 실측으로 고쳐졌으나, `구급대회`(→구급대) 같은 일부 오류는 프롬프트만으로는 못 이기는 acoustic 신호로 보여 여전히 남아있음
  - 프롬프트로 못 이기는 오인식은 [오인식 교정](#stt-정확도-개선--sbar-구조화)이 사후에 잡는다. **다만 사전에 등록된 것만 잡히므로 커버리지가 곧 한계다** — 지금 162개이고, 실제 통화가 쌓이는 만큼 늘려야 한다
  - **편집거리·유사도 기반 사전 매칭은 채택하지 않기로 했다.** 의학용어집(대한의사협회 `kma_pages.jsonl`, 5만여 표제어) 같은 대규모 사전에 편집거리를 걸면 정상 발화를 오교정할 위험이 커진다. 응급실↔구급차 통화는 어휘가 한정적이라, 실제로 틀린 것만 정확 일치로 등록하는 편이 안전하고 검증도 쉽다. 용어집은 사전 **오른쪽(정답) 표기를 검증하는 용도**로만 쓴다
  - 이 모든 실측은 통화 샘플 1개(`test1.wav`) 기준이라 일반화는 검증 안 됨
- 통신(WebSocket으로 `feature/hub`에 실시간 전송)은 아직 미구현. 지금은 JSON을 터미널 출력 + 파일 저장까지만 한다
- macOS + Homebrew가 아닌 환경에서는 Ollama 자동 설치가 동작하지 않음. [ollama.com](https://ollama.com)에서 직접 설치 필요

---

## 오인식 사전 관리

`corrections.json`은 사람이 직접 편집하는 데이터 파일이다. 왼쪽이 whisper가 잘못
뱉는 표기, 오른쪽이 정답이다.

```json
{
  "corrections": {
    "재세동": "제세동",
    "번지회": "2회",
    "1흔대": "70대"
  }
}
```

### 적는 규칙

| 위치 | 규칙 |
| --- | --- |
| 왼쪽 | **띄어쓰기는 신경 안 써도 된다** — `"지혈 때"`와 `"지혈때"`가 같게 동작한다. STT 출력에서 그대로 복사해 붙여도 된다 |
| 왼쪽 | 2글자 이상 (1글자는 `"안"` 같은 흔한 말을 통째로 치환해 위험) |
| 왼쪽 | **조사·종결어미는 빼고** (`"재세동이"`·`"재세동입니다"`가 아니라 `"재세동"`. 교정기가 붙여준다) |
| 왼쪽 | **정상 한국어 단어는 절대 금지** (아래 참고) |
| 오른쪽 | 제약 없음 — 공백·숫자·영문 다 가능 |

**왼쪽에 정상 단어를 넣으면 안 되는 이유.** whisper가 `"수용"`을 `"수영"`으로 여러 번
틀렸다고 `"수영" → "수용"`을 등록하면 정상 발화가 파괴된다.

```
"수영 중에 다리에 쥐가 났다고 합니다"  ->  "수용 중에 다리에 쥐가 났다고 합니다"
```

두 어절을 붙여 비단어로 만들면 안전하다: `"수영 가능" → "수용 가능"`.
`"앞면"`(정상 단어)은 안 되지만 `"앞면마비"`(비단어)는 되는 것과 같은 원리다.

**오른쪽 주의 — 받침이 바뀌면 조사가 어색해진다.** 교정기는 떼어낸 조사를 그대로
다시 붙이므로, 오른쪽 끝 글자의 받침이 왼쪽과 달라지면 조사가 틀어진다.
`"소개" → "소견"`을 등록하면 `"소개는"`이 `"소견는"`이 된다(`"소견은"`이어야 함).
이런 경우는 등록하지 않는 편이 낫다.

### 고친 뒤에는 자체 점검을 돌린다

```bash
python text_postprocess.py
```

세 가지를 본다 (음성 불필요, 1초 안쪽. 검사 데이터가 코드 안에 있어 별도 파일이 필요 없다).

- **형식 검사** — 공백 든 표기, 1글자 표기, 중복 항목, 오인식과 정답이 같은 항목. 이 위반들은 실행 중에 에러를 내지 않고 **조용히 무시**되므로 눈으로는 알기 어렵다
- **교정 동작** — 실측 STT 출력에서 조사 분리와 숫자 교정이 제대로 도는지
- **무교정 확인** — 오인식이 없는 정상 통화 문장에서 교정이 **0건**인지. 여기서 교정이 나오면 정상 단어를 오인식 표기로 잘못 등록했다는 뜻이다

### 오인식을 모으는 법

1. 통화를 STT로 돌려 텍스트를 뽑는다 (`--no-correction`으로 교정 전 원문 확인)
2. 정답 대본과 대조해 틀린 표기를 찾는다
3. `corrections.json`에 `"틀린표기": "정답"` 한 줄 추가
4. `python text_postprocess.py`로 점검

숫자·나이·약어처럼 whisper가 반복해서 틀리는 것부터 넣으면 효과가 크다.
`simulation3/`의 GUI(`stt_summary_gui.py`)를 쓰면 같은 사전을 공유하면서 모델·프롬프트를
바꿔가며 교정 결과를 눈으로 비교할 수 있다.

---

## 사용한 AI / 모델

| 구분 | 모델 | 용도 |
| --- | --- | --- |
| STT | [Whisper medium](https://huggingface.co/Systran/faster-whisper-medium) (faster-whisper) | 음성 → 텍스트, `--model`로 변경 가능. `STT_INITIAL_PROMPT`로 도메인 문맥 힌트 제공 |
| 오인식 교정 | *(모델 없음 — 규칙 기반)* | 사전 정확 일치 치환. AI를 쓰지 않아 결과가 결정적이고 교정 내역을 그대로 설명할 수 있다 |
| 정보 구조화 | [Qwen3-14B](https://huggingface.co/Qwen/Qwen3-14B) (Ollama `qwen3:14b`) | 교정된 텍스트 → SBAR JSON, `--llm-model`로 변경 가능 |

> CLAUDE.md "핵심 AI 활용 원칙" 표 기준: STT·정보 구조화는 **AI 처리**,
> 오인식 교정은 **규칙 기반**이다. 예전에 이 자리에 있던 의료 관련성
> 분류(`paraphrase-multilingual-MiniLM-L12-v2` 임베딩 유사도)는 제거됐다.

**개발 환경**: Python 3.11, faster-whisper / Ollama / pydantic / flask.
로컬 실행 (GPU 있으면 CUDA 12.x, macOS는 CTranslate2가 Metal/MPS 미지원이라
항상 CPU).

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
  "caseId": "case-abc123",
  "transcript": {
    "raw_text": "여보세요, 안녕하세요. 환자 50대 남성이고 교통사고 흉부 충격입니다...",
    "filtered_text": "환자 50대 남성이고 교통사고 흉부 충격입니다. 의식 저하 있고 호흡 곤란...",
    "language": "ko",
    "timestamp": "2026-07-28T14:32:31Z",
    "duration_sec": 42.3,
    "turns": [
      { "speaker": "미분리", "timestamp": "14:32:07", "text": "여보세요, 안녕하세요." },
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
| `caseId` | string | 여러 구급차가 동시에 사건을 진행할 수 있어, hub가 이 요약을 어느 사건과 짝지을지 구분하는 값. `app.py`가 hub의 통화 시작 신호에서 받은 caseId를 세션에 들고 있다가 그대로 돌려준다. `transcribe.py`/`call_capture.py`를 CLI로 단독 실행하면(caseId 개념이 없음) 오디오 파일명 기반으로 자동 생성된다(`--case-id`로 직접 지정 가능) |
| `transcript.raw_text` | string | STT 원본 전문. **교정 전** 전체 발화, 삭제하지 않고 보존 |
| `transcript.filtered_text` | string | 요약(LLM)에 실제로 들어간 입력값 = **오인식 교정 후** 텍스트. 교정할 게 없었으면 `raw_text`와 같다 |
| `transcript.language` | string | 언어 코드 |
| `transcript.timestamp` | string (ISO 8601) | 통화 시작 시각 (사전 녹음 파일 처리 특성상 근사값) |
| `transcript.duration_sec` | number | 통화 길이(초) |
| `transcript.turns` | array | 발화 턴별 **교정 전** 원본 로그 (`speaker`/`timestamp`/`text`, `excludedFromSummary`는 필터링 제거로 현재 항상 비어있음) |
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
AIRookie/                        (.gitignore·CLAUDE.md·pull-all.sh는 브랜치 공통이라 생략)
├── voice/
│   ├── README.md                이 문서
│   ├── DEVELOPMENT.md           개발 환경 가이드
│   ├── requirements.txt         의존성 목록
│   │
│   │   ── 진입점 ──
│   ├── app.py                   실운영. hub 신호를 HTTP로 수신 (Flask)
│   ├── call_capture.py          CLI. 마이크 녹음 → Ctrl+C로 종료
│   ├── transcribe.py            배치 CLI + 파이프라인 본체 (위 둘이 호출)
│   │
│   │   ── 파이프라인 단계 ──
│   ├── mic_recorder.py          [녹음]   마이크 입력 → numpy 버퍼 → WAV
│   ├── text_postprocess.py      [교정]   오인식 사전 대조 필터 + 자체 점검
│   ├── corrections.json         [교정]   오인식 사전 (손으로 편집)
│   ├── summarizer.py            [구조화] 교정된 텍스트 → LLM SBAR JSON
│   ├── ollama_bootstrap.py      [구조화] Ollama 설치·기동·모델 pull 자동화
│   ├── schema.py                [출력]   pydantic 스키마 (hub 전송용 JSON)
│   │
│   │   ── 그 외 ──
│   ├── cuda_setup.py            pip nvidia DLL 경로 등록 (Windows GPU 가속)
│   └── simulation3/             시연 화면 겸 사전 튜닝 하네스 (실운영 경로 아님)
│       ├── README.md            시뮬레이터 사용법
│       ├── pipeline.py          STT → 교정 → LLM 2회 호출
│       └── stt_summary_gui.py   tkinter GUI
│
└── data/                        (.gitignore의 data/ 규칙에 걸려 저장소에는 안 올라감)
    └── voice_data/
        ├── origin_data/         원본 음성 파일 (직접 추가) + 마이크 녹음 저장 위치
        ├── origin_text/         STT 원문 텍스트 (.txt)
        ├── summary_text/        SBAR 구조화 JSON (*_call_summary.json)
        └── live_audio/          mic_recorder.py 스모크 테스트 녹음 WAV
```

### 호출 관계

```
app.py ─────────┐
call_capture.py ┼──→ transcribe.transcribe()
transcribe.py ──┘         │
   (main)                 ├─ faster-whisper ──────────────→ 세그먼트
   ↑                      │
mic_recorder.py           └─→ build_and_emit_call_summary()
 (앞 둘이 녹음에 사용)              │
                                   ├─ correct_transcript() ─→ text_postprocess ─ corrections.json
                                   ├─ summarizer ───────────→ ollama_bootstrap ─ Ollama
                                   └─ schema ───────────────→ 파일 저장 + hub POST
```

### 파일별 역할

| 계층 | 파일 | 역할 |
| --- | --- | --- |
| **진입점** | `app.py` | 실운영 경로. hub가 중계한 `POST /call/start`·`/call/end`로 녹음을 제어하고, 종료 시 파이프라인을 백그라운드 스레드로 실행(STT가 수십 초라 응답을 막지 않으려고). 부팅 시 자기 IP를 탐지해 hub에 자가등록하고(`VOICE_APID`), 통화 시작 신호의 `caseId`를 세션에 들고 있다가 요약에 실어 돌려준다 |
| | `call_capture.py` | `app.py`의 CLI 버전. 트리거가 HTTP 대신 Ctrl+C인 것만 다르다. STT 로직을 새로 짜지 않고 `transcribe()`를 그대로 재사용 |
| | `transcribe.py` | 녹음 파일을 직접 처리하는 CLI인 **동시에 파이프라인 본체**다. `transcribe()`(STT)와 `build_and_emit_call_summary()`(교정→구조화→전송)로 나뉘어 있고, 데이터 경로 상수와 `STT_INITIAL_PROMPT`도 여기 모여 있다 |
| **녹음** | `mic_recorder.py` | 마이크 입력을 백그라운드 스레드에서 numpy 버퍼에 누적. 16kHz 모노 고정(Whisper 기대값이라 리샘플링 회피). `snapshot()`이 락을 걸고 복사본을 돌려줘 녹음 중에도 비파괴적으로 읽을 수 있다. 단독 실행 시 `--seconds` 스모크 테스트 |
| **교정** | `text_postprocess.py` | STT 텍스트를 사전과 **정확 일치** 대조해 치환. 조사·종결어미 분리 후 재부착, 공백 정규화, 긴 구간 우선. 직접 실행하면 사전 자체 점검이 돈다 |
| | `corrections.json` | 오인식 사전. **손으로 편집하는 데이터 파일** — 편집 규칙과 점검 방법은 [오인식 사전 관리](#오인식-사전-관리) 참고 |
| **구조화** | `summarizer.py` | Ollama `/api/generate` 호출부를 독점한다. `<think>` 태그 제거 → JSON 관대 추출 → 필드 정규화(`severity_tag`가 이상하면 `medium`으로 낙착). LLM 백엔드를 바꿔도 이 파일만 교체하면 된다 |
| | `ollama_bootstrap.py` | LLM 호출 직전에 바이너리·서버·모델을 자동 준비. 자동 **설치**는 macOS+Homebrew만 지원하지만, 서버 기동과 모델 pull은 OS 무관하게 동작한다 |
| | `schema.py` | 출력 JSON pydantic 스키마. dashboard의 `CallSummaryMessage` 타입과 1:1 대응이라 필드 변경 시 양쪽을 같이 고쳐야 한다 |
| **환경** | `cuda_setup.py` | pip으로 깐 `nvidia-cublas-cu12`/`nvidia-cudnn-cu12`의 DLL 폴더를 Windows 검색 경로에 등록한다. `faster_whisper`보다 **먼저** import돼야 해서 별도 모듈로 뺐고(알파벳순이라 import 정렬에도 순서가 유지됨), 맥·리눅스에서는 아무것도 하지 않는다 |

### `simulation3/` — 사전 튜닝용 실험 하네스

**실운영 경로가 아니다.** `corrections.json`을 늘려가며 STT 모델·LLM·프롬프트를
바꿔 결과를 눈으로 비교하는 용도다. 교정 필터와 사전은 `voice/` 것을 그대로
import해 **공유**하므로, 여기서 실험하며 추가한 항목이 곧 실운영에 반영된다
(사본을 두면 갈라지므로 일부러 하나로 유지).

| 파일 | 역할 |
| --- | --- |
| `pipeline.py` | STT → 교정 → LLM **2회** 호출(SBAR 구조화 + 환자 상태 1~2문장 요약). CLI 포함 |
| `stt_summary_gui.py` | tkinter GUI. 화면과 스레드만 담당하고 처리는 전부 `pipeline.py`에 맡긴다 |
| `README.md` | 시뮬레이터 사용법과 실측 결과 |

본 파이프라인과 의도적으로 다른 점:

| | 이유 |
| --- | --- |
| hub 전송·파일 저장·`caseId`·스키마 검증 **없음** | 시뮬레이터라 결과를 화면에 띄우고 끝낸다. 그래서 `transcribe.py`를 이걸로 대체할 수는 없다 |
| **GPU 폴백 있음** | `device="auto"`를 cuda 시도 → 실패 시 cpu 재시도로 직접 해석하고, pip으로 깐 nvidia DLL 경로를 등록한다 (RTX 5080 + ctranslate2 대응). `transcribe.py`에는 없다 |
| **모델 캐시 있음** | 같은 파일을 반복 실행할 때 Whisper 모델을 재사용 |
| **환자 상태 요약** | SBAR와 별개로 1~2문장 요약을 추가 생성 (팀 스키마에 없는 필드라 JSON 밖에 둔다) |
| **프롬프트 편집 가능** | GUI에서 SBAR 시스템 프롬프트를 고쳐 그 실행에만 반영 |

> ⚠️ `pipeline.py`의 `STT_INITIAL_PROMPT`는 팀이 오버피팅으로 판단해 롤백한
> **구버전이 남아 있다** (`transcribe.py` 것과 다름). simulation3 README의 실측
> 수치도 그 프롬프트로 측정한 값이므로, 팀 기준으로 다시 재려면 이걸 먼저 맞춰야 한다.

### 경로 규칙

모든 파이썬 코드가 `voice/` 한 폴더에 평평하게 있어 상호 import(`from
text_postprocess import ...`)가 그대로 동작한다. 데이터 경로는 파일
위치(`__file__`) 기준으로 계산되므로 `voice/` 안에서 `python transcribe.py ...`로
실행하든 저장소 루트에서 `python voice/transcribe.py ...`로 실행하든 결과가 같다
(다만 `requirements.txt`가 `voice/`에 있으므로 설치·실행은 `voice/` 안에서 하는
쪽으로 통일했다).

`corrections.json`이 `data/`가 아니라 `voice/` 직속에 있는 이유: `.gitignore`가
`data/`를 통째로 무시해서, 사전을 그 아래 두면 저장소에 올라가지 않는다. 사전은
데이터가 아니라 **코드처럼 버전 관리해야 하는 자산**이다.

`youtube_downloader.py`는 실제로 쓰이지 않아 저장소에서 뺐다 (`.gitignore` 참고,
로컬에는 남아있음).

---

## 알려진 제약사항 / TODO

- macOS(Apple Silicon 포함)에서는 CTranslate2가 Metal/MPS GPU 가속을 지원하지 않아 항상 CPU로 동작. 기본값은 `medium`(정확도·속도 절충)이며, 더 정확한 결과가 필요하면 `--model large-v3`로 올릴 수 있으나 느려짐
- GPU 사용 시 NVIDIA CUDA 12.x 및 cuDNN 9 필요
- `data/voice_data/` 하위 전 폴더는 `.gitignore`에 포함되어 있어 오디오 원본과 변환 결과물은 저장소에 올라가지 않음
- 마이크 캡처(`app.py`·`call_capture.py`)는 통화 중에 STT를 돌리지 않고 녹음만 한다 — 실시간 자막이 필요한 화면은 dashboard의 브라우저 마이크가 담당
- 마이크 권한 설정 필수 (macOS: 시스템 설정 > 개인정보 보호 > 마이크)
- STT/구조화 관련 제약사항은 위 ["알려진 한계"](#stt-정확도-개선--sbar-구조화) 참고

---

## 추가사항
