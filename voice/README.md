# feature/voice — 음성 STT(Qwen3-ASR) · 정보 구조화(HMM) 파이프라인

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
- [실가동 파이프라인 상세](#실가동-파이프라인-상세)
- [모델 설명](#모델-설명)
- [사용한 AI / 모델](#사용한-ai--모델)
- [입출력 데이터 포맷](#입출력-데이터-포맷)
- [폴더 구조](#폴더-구조)
- [알려진 제약사항 / TODO](#알려진-제약사항--todo)

---

## 빠른 시작

**1. 환경** — Python 3.11. torch는 GPU 빌드를 먼저 따로 설치한다(PyPI 기본 휠은 CPU 전용).

```bash
conda create -n rookie python=3.11
conda activate rookie
pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128   # Windows + NVIDIA
cd voice
pip install -r requirements.txt
```

**2. 가중치** — 두 모델 모두 저장소에 없다(용량). 아래 경로에 두거나 환경변수로 위치를 알려준다.

| 환경변수 | 기본값 | 들어 있어야 하는 것 |
| --- | --- | --- |
| `ASR_ADAPTER_DIR` | `C:\Dev\HMM\use\adapter` | Qwen3-ASR LoRA 어댑터 (`adapter_config.json`, `adapter_model.safetensors`, 약 79MB) |
| `HMM_RUN_DIR` | `C:\Dev\HMM\model_HMM\runs\golden` | HMM 체크포인트 `best.pt`(약 1.4GB) + `tokenizer/` |

ASR 베이스 모델(`Qwen/Qwen3-ASR-1.7B-hf`, 약 4GB)과 HMM 인코더 설정(`klue/roberta-large`)은
첫 실행 때 Hugging Face 캐시(`HF_HOME`)로 자동으로 내려받는다(인터넷 필요).

**3. 실행** — 마이크로 바로 시작해볼 수 있다 (`voice/` 안에서):

```bash
python call_capture.py
```

모델을 올린 뒤(약 15~20초) 녹음이 시작된다. 말이 끊길 때마다 `[발화 인식]` 줄이 찍히고,
Ctrl+C를 누르면(통화 종료) 남은 발화를 인식한 뒤 구조화 → hub 전송까지 이어서 실행된다.

---

## 이 브랜치가 하는 일

통화 음성을 텍스트로 바꾸고 → 환자 정보 6필드로 구조화해 → `feature/hub`로 보낸다.
dashboard로는 직접 보내지 않고 `feature/hub`를 거쳐 전달된다.

```
마이크 ─▶ [STT] Qwen3-ASR + LoRA ─▶ 발화 텍스트 ─▶ [구조화] HMM + 규칙 조립 ─▶ summary 6필드 ─▶ feature/hub
          통화 중 발화 단위로 인식                    분류·태깅 모델 (생성형 아님)
```

> **2026-09-24 교체.** 이전 경로(faster-whisper → `corrections.json` 오인식 교정 →
> Ollama `qwen3:14b` SBAR 구조화)는 코드째 삭제했다. 두 모델은 팀이 따로
> 파인튜닝한 것으로(`C:\Dev\HMM`), 추론 코드만 이 폴더(`asr.py`, `hmm/`)에 복사해 넣었다.

**진입점은 3개**다. 셋 다 같은 모델·같은 후처리(`transcribe.emit_call_summary()`)를 쓰고
출력 JSON 스키마도 같다.

| 진입점 | 언제 쓰나 | 통화 시작 / 종료 | 인식 방식 |
| --- | --- | --- | --- |
| `app.py` | **실운영.** hub가 dashboard의 신호를 HTTP로 중계 | `POST /call/start` / `/call/end` | 통화 중 발화 단위 |
| `call_capture.py` | 마이크로 직접 통화를 흉내내는 CLI 테스트 | 실행 / `Ctrl+C` | 통화 중 발화 단위 |
| `transcribe.py` | 이미 녹음된 파일 배치 처리 | (해당 없음) | 파일 통째로 5초 조각 |

시연·튜닝용 화면은 `simulation3/gui.py`에 따로 있다 — 같은 모듈을 쓰면서 통화 중에 6필드·모델 판정
중간값·hub JSON을 실시간으로 보여준다(전송은 안 함). 사용법은 [`simulation3/README.md`](simulation3/README.md).

---

## 실행 방법

### 1. 배치 처리: 녹음된 파일

```bash
python transcribe.py data/voice_data/origin_data/파일명.m4a --summarize
```

wav는 soundfile로, m4a 등은 PyAV(FFmpeg)로 읽는다. `--summarize`를 빼면 STT까지만 하고 끝난다.

| 산출물 | 저장 위치 |
| --- | --- |
| STT 원문 텍스트 (`.txt`, 발화마다 줄바꿈) | `data/voice_data/origin_text/파일명.txt` |
| hub 전송 JSON (`--summarize` 시) | `data/voice_data/summary_text/파일명_call_summary.json` |

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--device` | `auto` | 연산 장치 (`auto` / `cuda` / `mps` / `cpu`) |
| `--summarize` | (off) | 구조화 + hub 전송까지 수행 |
| `--case-id` | 파일명 기반 | hub에 보낼 caseId |

### 2. 마이크 캡처

#### 2-1. 스모크 테스트: 마이크로 5초 녹음

```bash
python mic_recorder.py --seconds 5
```

마이크 권한 요청이 나면 시스템 설정 > 개인정보 보호 > 마이크에서 터미널 앱에
권한을 부여해야 한다 (macOS).

#### 2-2. 통화 캡처 (`call_capture.py`)

```bash
python call_capture.py --session live_test1
```

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--session` | 실행 시각 | 세션(파일) 이름 |
| `--device` | `auto` | 연산 장치 |
| `--case-id` | 세션 이름 기반 | hub에 보낼 caseId |

녹음 원본은 인식에 쓰지 않지만 사후 검증용으로 `data/voice_data/origin_data/<세션>.wav`에 남는다.

#### 2-3. `app.py` — hub가 원격으로 트리거하는 실제 파이프라인

`call_capture.py`의 흐름을 Ctrl+C 대신 HTTP 요청(feature/hub가 중계하는 통화 시작/종료
신호)으로 트리거하도록 감싼 게 실제 운영 경로다. 이 프로세스 자체는 구급차 1대 전용이다 —
마이크가 그 구급차 장비 하나뿐이라 통화도 한 번에 하나만 가능하다. 여러 구급차를
지원하는 건 hub가 여러 대의 voice 인스턴스를 구분해 각자에게 신호를
중계해주는 방식으로 이뤄진다(feature/hub README.md 참고).

```bash
VOICE_APID=A0000001 VOICE_PORT=6000 python app.py
```

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `VOICE_APID` | (없음) | 이 voice 인스턴스가 담당하는 구급차 식별자. hub의 구급차 레지스트리(apid)와 일치해야 하며, 없으면 hub 자가등록 자체를 건너뛴다(단독 테스트용) |
| `VOICE_PORT` | `6000` | 이 인스턴스가 바인딩할 포트. 포트 배정표(hub=5001, info=5002 고정, voice=구급차마다 6000대)의 voice 몫 — 구급차 레지스트리의 `AmbulanceInfo.voicePort`와 맞춰야 한다 |
| `HUB_BASE_URL` | `http://127.0.0.1:5001` | hub 주소. 자가등록 요청 및 자기 IP 자동 탐지에 쓰인다 |
| `HUB_VOICE_SUMMARY_URL` | `http://127.0.0.1:5001/voice/summary` | 통화 요약을 보낼 hub 엔드포인트 |
| `VOICE_REGISTER_RETRY_SEC` | `5` | hub 자가등록 실패 시 재시도 간격(초) |
| `VOICE_DEVICE` | `auto` | 연산 장치 |
| `VOICE_SILENCE_RMS` | `0.01` | 이보다 작은 소리는 말이 아닌 것으로 본다. [발화 단위 인식](#발화-단위-인식-live_transcriberpy) 참고 |
| `VOICE_UTTERANCE_HOLD_SEC` | `0.4` | 이만큼 조용하면 한 발화가 끝난 것으로 본다 |
| `ASR_ADAPTER_DIR` / `HMM_RUN_DIR` | [빠른 시작](#빠른-시작) 참고 | 가중치 위치 |

**동작 순서**
1. 서버가 뜨기 전에 두 모델을 한 번 올린다(약 15~20초). 통화마다 올리면 그만큼 늦어지므로 프로세스가 살아있는 동안 재사용한다
2. 동시에 별도 스레드에서 자기 IP를 자동 탐지해 hub의 `POST /voice/register`로 자가등록한다.
   구급차 노트북마다 네트워크가 달라 IP를 미리 저장하지 않고 매번 탐지한다. hub가 이 apid를
   아직 모르면 실패하는데, `VOICE_REGISTER_RETRY_SEC`마다 계속 재시도하므로 순서를 맞출 필요는 없다
3. `POST /call/start` — `caseId`를 세션에 기억하고, 마이크 녹음과 발화 단위 인식을 시작한다
4. `POST /call/end` — 녹음을 멈추고 즉시 200을 응답한 뒤, 백그라운드에서 남은 발화 인식 →
   구조화 → hub 전송을 실행한다. 기억해둔 caseId를 그대로 실어 보낸다

---

## 실가동 파이프라인 상세

아래는 `app.py`가 hub 신호를 받은 시점부터 hub로 결과를 돌려주기까지 실제로 일어나는 일이다.

```
POST /call/start  (hub 중계)
   │  app.py — caseId 기억, MicRecorder.start(), LiveTranscriber.start()
   ▼
┌─ 통화 중 ──────────────────────────────────────────────────────────┐
│ live_transcriber.py — 0.5초마다 새로 쌓인 녹음을 확인               │
│   0.1초 프레임 음량(RMS)으로 무음 판정                              │
│   말이 0.4초 끊기면 그 발화만 잘라 asr.transcribe_audio()           │
│   → 발화 텍스트를 구간 목록에 쌓음 ([발화 인식] 로그)               │
└────────────────────────────────────────────────────────────────────┘
   ▼
POST /call/end    (hub 중계)
   │  app.py — 녹음 저장·정지 → 200 응답 → 백그라운드 스레드
   ▼
┌──────────────────────────────────────────────────────────────────┐
│ LiveTranscriber.finish()   남은 발화(보통 1~2개)만 인식            │
│                                                                  │
│ transcribe.emit_call_summary()                                   │
│   발화들을 줄바꿈으로 이어 붙임 → origin_text/<세션>.txt 저장     │
│   HmmExtractor.extract()        HMM 점수 → 규칙 조립 → 6필드      │
│   CallSummaryMessage 조립       pydantic 검증                    │
│   summary_text/<세션>_call_summary.json 저장                     │
│   send_to_hub()                 POST /voice/summary              │
└──────────────────────────────────────────────────────────────────┘
```

### 발화 단위 인식 (`live_transcriber.py`)

Qwen3-ASR은 오디오 한 덩어리를 받아 문장을 생성하는 모델이라 말하는 도중에 글자가 하나씩
나오지는 않는다(진짜 스트리밍 아님). 대신 **말이 끊기는 지점에서 잘라 그 발화를 바로
인식**한다. 통화가 끝난 뒤 한꺼번에 인식하면 통화 길이의 절반가량을 기다려야 하지만,
통화 중에 미리 인식해 두면 종료 후에는 마지막 발화만 남는다. 전체 연산량은 같고, 그 연산을
통화 시간 동안 나눠 할 뿐이다. 방식은 `C:\Dev\HMM\simulation`의 데모에서 가져왔다.

| 규칙 | 값 |
| --- | --- |
| 무음 판정 | 0.1초 프레임 RMS < `VOICE_SILENCE_RMS`(기본 0.01) |
| 발화 끝 판정 | 말이 시작된 뒤 `VOICE_UTTERANCE_HOLD_SEC`(기본 0.4초) 이상 조용함 |
| 너무 짧은 소리 | 0.6초 미만은 발화로 보지 않음(기침·잡음) |
| 너무 긴 발화 | 12초를 넘으면 마지막 2초 중 가장 조용한 지점에서 끊음 |
| 말 없는 구간 | 0.5초만 남기고 버림(버퍼가 계속 커지지 않게) |

**무음 판정은 소리 크기만 본다.** 사람 목소리와 소음을 구분하지 못하므로, 시끄러운 곳에서
발화가 안 끊기면 `VOICE_SILENCE_RMS`를 올리고, 말하는 중에 자꾸 끊기면
`VOICE_UTTERANCE_HOLD_SEC`를 늘린다. 기본값은 브라우저 마이크 기준으로 잡힌 값이라,
실제 장비 마이크에서 한 번 맞춰봐야 한다 — `simulation3/gui.py`가 현재 음량과 판정을 보여줘서
맞추기 쉽다.

통화 중 인식이 예외로 멈춰도 통화를 잃지 않는다 — 인식이 멈춘 지점부터 `finish()`가
남은 소리를 한꺼번에 다시 인식한다.

### 데이터가 어떻게 변형되나 (`1.m4a` 실측)

| 단계 | 산출물 | 예시 |
| --- | --- | --- |
| STT | `transcript.raw_text` · `turns[]` | `62세 남성이고요.\n30분 전부터 갑자기 가슴이.\n...짐근경색을 의심하고...` |
| 구조화 입력 | `transcript.filtered_text` | `raw_text`와 같음 (교정·필터링 단계 없음) |
| 구조화 | `summary` | `{"patient": "60대 남성", "mechanism": "심장질환 · 흉통", "severity_tag": "high", "required_department": "내과", ...}` |
| 전송 | `CallSummaryMessage` | 위 전부 + `caseId`·`source`·`model_used` |

### 실측 소요 시간

RTX 5080 · CUDA · bf16 · 108.6초 통화(`1.m4a`) 기준.

| 단계 | 소요 |
| --- | --- |
| 모델 로딩 (ASR + HMM) | 14~20초 *(프로세스당 1회)* |
| **통화 종료 → hub 수신** (`app.py`, 발화 단위 인식) | **3.7초** |
| 참고: 같은 통화를 끝나고 한 번에 인식 (`transcribe.py`) | ASR 61.1초 |
| 구조화 (HMM) | 0.1초 |

`app.py` 수치는 실제 마이크 대신 파일을 실시간 속도로 흘려 넣어 잰 값이다.

### 실패해도 죽지 않는 지점 / 죽는 지점

| 상황 | 동작 |
| --- | --- |
| GPU 없음 | **계속** — ASR은 mps/cpu, HMM은 cpu로 (매우 느림, 미검증) |
| 가중치 폴더 없음 | **시작 실패** — `FileNotFoundError`로 경로를 알려주고 서버가 뜨지 않는다 |
| 통화 중 인식 예외 | **계속** — 종료 시 남은 소리를 한꺼번에 다시 인식 |
| 인식된 발화가 없음(무음 통화) | 구조화·전송을 **건너뜀** (원문 `.txt`는 빈 파일로 남음) |
| hub 미기동 | **계속** — 파일 저장까지 완료, stderr에만 알림 |

> `app.py`는 남은 처리를 백그라운드 스레드로 돌리고 `/call/end`에 이미 200을
> 응답한 뒤다. 구조화나 전송 전에 스레드가 죽거나 발화가 없어 건너뛰면 **hub는 계속
> 기다린다** — 실패를 hub로 알리는 경로가 아직 없다 (알려진 제약사항 참고).

---

## 모델 설명

### STT — Qwen3-ASR + LoRA (`asr.py`)

| 항목 | 내용 |
| --- | --- |
| 베이스 | `Qwen/Qwen3-ASR-1.7B-hf` |
| 어댑터 | LoRA r=16 (alpha 32), 학습 step 3400 시점 best |
| 학습 데이터 | AI Hub 119 신고 음성, 재난유형 4종 × 5시간 = 20시간(발화 36,651개) |
| 검증 | 학습에 안 쓴 500개 발화 기준 정규화 CER 원본 0.298 → **0.182** |
| 입력 단위 | 학습 데이터가 평균 2초 발화라 5초 안팎으로 잘라 인식(20초 단위는 문장이 통째로 빠졌음) |

- **틀린 결과도 자연스러운 문장처럼 나온다** (예: `심근경색` → `짐근경색`, `식은땀` → `찌근땀`). 구급대원 확인·수정(Override)을 거쳐야 한다
- 학습 데이터의 개인정보 마스킹 표기 때문에 `***[개인정보]`를 출력하는 경우가 있다 (처리 방법 보류 중)
- 검증은 신고자↔119 통화로 했다. **구급대원↔병원 통화, 소음이 큰 현장에서의 성능은 측정하지 않았다**

### 구조화 — HMM (`hmm/`)

KLUE RoBERTa-large 인코더에 출력층 여러 개를 붙인 다중과제 모델이 필드별 점수를 내고(AI),
규칙 조립기가 이를 hub 계약 필드로 맞춘다(규칙). **생성형 모델이 아니라** 출력 형식이 깨질
일이 없고, 같은 입력에는 항상 같은 결과가 나온다.

| 모델이 고르는 것 | 보기 |
| --- | --- |
| 원인 (cause) | 외상 7 · 비외상성 손상 11 · 질병 12 = 30개 + 판단 보류 |
| 부위 (body_part) | 머리·얼굴·목·가슴·배·등·허리·골반·팔·다리·다발성 + 판단 보류 (외상·손상일 때만) |
| 중증도 | high · medium · low |
| 나이대 · 성별 | 10세 미만 ~ 90대 이상 / 남성·여성 (+ 판단 보류) |
| 처치 (다중 선택) | 기도확보·산소투여·CPR·ECG·AED·순환보조·약물투여·고정·상처처치·분만·보온 |
| 증상 구간 | 토큰마다 증상 있음/없음 구간 태깅 → 표준명으로 정리 |

| 계약 필드 | 만드는 규칙 (`hmm/assemble.py`) |
| --- | --- |
| `patient` | 나이대 + 성별 중 아는 것만 (`"60대 남성"`) |
| `mechanism` | 원인 + (외상이면 부위 / 질병이면 대표 증상) (`"낙상 · 머리"`) |
| `symptoms` | "있음" 증상 구간의 표준명, 원문 순서 |
| `treatment` | 시행 확률 0.5 이상인 처치 |
| `severity_tag` | 중증도 그대로 |
| `required_department` | 원인·부위 → 심평원 전문과목 대응표(`hmm/department_mapping.json`). 대응이 없으면 `null` |

**성능** (golden eval 355건, 텍스트 입력 기준 — `C:\Dev\HMM\BANCHMARK`)

| 필드 | 정확도 / F1 |
| --- | --- |
| patient | 0.938 |
| severity_tag | 0.831 |
| required_department | 0.848 |
| treatment | F1 0.894 |
| mechanism (완전 일치) | 0.487 — 원인 부분만 보면 0.808 |
| symptoms | F1 0.186 — **가장 약함** |

- 학습 데이터는 "줄바꿈 = 화자 전환"인 대본 형태다. 여기 입력은 "줄바꿈 = 발화 경계"라 완전히 같은 형태가 아니고, **실제 음성 입력에서의 성능은 측정하지 않았다**
- 증상 표준명은 임시 규칙(`hmm/symptom_names.py`)이다. 사전에 없는 표현은 원문 구간이 그대로 나온다(예: `"가슴이."`)
- `department_mapping.json`의 뇌혈관질환·소화기질환·성폭행 대응은 팀 확정 전 초안이다(파일 안 `ambiguous_notes`)
- 복사해 온 코드가 원본과 같은 결과를 내는지 eval 295건으로 대조했다(transformers 4.57.6 원본 ↔ 5.17.0 복사본, 전부 동일)

---

## 사용한 AI / 모델

| 구분 | 모델 | 처리 방식 |
| --- | --- | --- |
| STT | Qwen3-ASR-1.7B + LoRA (팀 파인튜닝) | AI 처리 |
| 정보 구조화 — 필드 판정 | KLUE RoBERTa-large 다중과제 모델 HMM (팀 학습) | AI 처리 (분류·태깅, 생성형 아님) |
| 정보 구조화 — 필드 조립·진료과 도출 | *(모델 없음)* | 규칙 기반 |

**개발 환경**: Python 3.11, torch 2.11 (CUDA 12.8), transformers 5.17, peft, flask.
Qwen3-ASR이 transformers 5.13 이상을 요구한다. 전부 로컬에서 돌아가며 외부 API로 음성·텍스트가 나가지 않는다.

---

## 입출력 데이터 포맷

**입력**: 마이크(16kHz 모노) 또는 오디오 파일(wav·m4a 등)

**출력**: `feature/hub`로 전달되는 JSON. dashboard로는 직접 보내지 않는다.
`feature/dashboard`의 `CallSummaryMessage` 타입과 1:1 대응하며(`schema.py`),
**hub·dashboard와의 고정 계약이라 필드를 임의로 늘리거나 바꾸지 않는다.**

```json
{
  "caseId": "case-abc123",
  "transcript": {
    "raw_text": "62세 남성이고요.\n30분 전부터 갑자기 가슴이.\n가슴을 지어 짜는 듯한 흉통이 있었다고 합니다.",
    "filtered_text": "62세 남성이고요.\n30분 전부터 갑자기 가슴이.\n가슴을 지어 짜는 듯한 흉통이 있었다고 합니다.",
    "language": "ko",
    "timestamp": "2026-09-24T07:53:04Z",
    "duration_sec": 108.6,
    "turns": [
      { "speaker": "미분리", "timestamp": "07:53:29", "text": "62세 남성이고요." },
      { "speaker": "미분리", "timestamp": "07:53:32", "text": "30분 전부터 갑자기 가슴이." }
    ]
  },
  "summary": {
    "patient": "60대 남성",
    "mechanism": "심장질환 · 흉통",
    "symptoms": ["흉통", "왼쪽 팔까지 통증이 뻗친다", "식은땀"],
    "treatment": ["산소투여", "ECG", "AED"],
    "severity_tag": "high",
    "required_department": "내과"
  },
  "source": "ai",
  "model_used": {
    "stt": "qwen3-asr-1.7b-lora",
    "llm": "hmm-klue-roberta-large"
  }
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `caseId` | string | hub가 이 요약을 어느 사건과 짝지을지 구분하는 값. `app.py`는 통화 시작 신호의 caseId를 그대로 돌려주고, CLI는 파일·세션 이름으로 만든다(`--case-id`로 지정 가능) |
| `transcript.raw_text` | string | STT 인식 결과 전문. 발화마다 줄바꿈, 삭제하지 않고 보존 |
| `transcript.filtered_text` | string | 구조화에 실제로 들어간 입력. 교정·필터링 단계가 없어 `raw_text`와 같다 (계약 필드라 유지) |
| `transcript.language` | string | 언어 코드 (`ko` 고정 — ASR이 한국어 프롬프트로 학습됨) |
| `transcript.timestamp` | string (ISO 8601) | 통화 시작 시각 (처리 시점에서 통화 길이만큼 거슬러 올라간 근사값) |
| `transcript.duration_sec` | number | 통화 길이(초) |
| `transcript.turns` | array | 발화별 원본 로그 (`speaker`는 화자 분리가 없어 `"미분리"` 고정, `excludedFromSummary`는 채우는 곳이 없어 항상 빠짐) |
| `summary.patient` | string | 나이대·성별. 둘 다 모르면 빈 문자열 |
| `summary.mechanism` | string | 원인 · 부위/대표 증상. 원인을 모르면 빈 문자열 |
| `summary.symptoms` | string[] | 있는 증상 목록 |
| `summary.treatment` | string[] | 시행한 처치 목록 |
| `summary.severity_tag` | `"high"` \| `"medium"` \| `"low"` | 중증도. 항상 값이 있다 |
| `summary.required_department` | string \| null | 필요 진료과 (심평원 전문과목 표기) |
| `source` | `"ai"` | AI 처리 결과 고정값 |
| `model_used.stt` / `model_used.llm` | string | 실제 사용된 모델명. `llm`은 필드명만 유지할 뿐 생성형 모델이 아니다 |

바이탈 필드는 포함하지 않는다 (환자 바이탈 정보는 더 이상 사용하지 않기로 결정됨).

---

## 폴더 구조

```
AIRookie/                        (.gitignore·CLAUDE.md·pull-all.sh는 브랜치 공통이라 생략)
├── voice/
│   ├── README.md                이 문서
│   ├── DEVELOPMENT.md           브랜치 가이드
│   ├── requirements.txt         의존성 목록 (torch는 먼저 따로 설치)
│   │
│   │   ── 진입점 ──
│   ├── app.py                   실운영. hub 신호를 HTTP로 수신 (Flask)
│   ├── call_capture.py          CLI. 마이크 녹음 → Ctrl+C로 종료
│   ├── transcribe.py            배치 CLI + 공통 후처리(모델 로딩·구조화·조립·전송)
│   │
│   │   ── 파이프라인 단계 ──
│   ├── mic_recorder.py          [녹음]   마이크 입력 → numpy 버퍼 → WAV
│   ├── live_transcriber.py      [녹음→STT] 통화 중 무음 감지로 발화를 잘라 바로 인식
│   ├── asr.py                   [STT]    Qwen3-ASR + LoRA, 오디오 읽기·5초 분할
│   ├── hmm/                     [구조화] HMM 모델 + 규칙 조립기
│   │   ├── __init__.py          HmmExtractor — 체크포인트 로딩, 텍스트 → 6필드
│   │   ├── model.py             모델 정의 (체크포인트 state_dict와 구조가 같아야 함)
│   │   ├── labels.py            출력층 보기 목록 (순서를 바꾸면 체크포인트와 안 맞음)
│   │   ├── decode.py            점수 → 필드 (증상 구간은 BIO 제약 Viterbi)
│   │   ├── assemble.py          필드 → 계약 6필드 (규칙)
│   │   ├── symptom_names.py     증상 구간 → 표준명 (임시 규칙)
│   │   └── department_mapping.json  원인·부위 → 전문과목 대응표
│   ├── schema.py                [출력]   pydantic 스키마 (hub 전송용 JSON)
│   │
│   │   ── 그 외 ──
│   └── simulation3/             시연·튜닝용 데스크톱 화면 (실운영 경로 아님)
│       ├── README.md            사용법
│       └── gui.py               tkinter. 처리는 전부 위 모듈을 import
│
└── data/                        (.gitignore의 data/ 규칙에 걸려 저장소에는 안 올라감)
    └── voice_data/
        ├── origin_data/         원본 음성 파일 (직접 추가) + 통화 녹음 저장 위치
        ├── origin_text/         STT 원문 텍스트 (.txt)
        ├── summary_text/        hub 전송 JSON (*_call_summary.json)
        └── live_audio/          mic_recorder.py 스모크 테스트 녹음 WAV
```

### 호출 관계

```
      app.py            call_capture.py         transcribe.py (main)
   (HTTP 트리거)          (Ctrl+C 트리거)          (파일 배치)
        │                      │                      │
        ├── mic_recorder ──────┤                      │
        ├── live_transcriber ──┤                      │
        │         │            │                      │
        │         └──────── asr.AsrModel ─────────────┤   ← STT
        │                      │                      │
        └──────────────┬───────┴──────────────────────┘
                       ▼
        transcribe.emit_call_summary()
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   hmm.HmmExtractor  schema      send_to_hub()
   (model→decode→   (pydantic)      hub POST
    assemble)
```

화살표가 한 방향뿐이고 순환이 없다. `hmm/`·`schema.py`·`mic_recorder.py`는 다른 로컬
모듈에 의존하지 않아, 모델을 바꿔도 영향 범위가 그 폴더·파일로 묶인다.

### 경로 규칙

모든 파이썬 코드가 `voice/` 한 폴더에 평평하게 있어(`hmm/`만 패키지) 상호 import가
그대로 동작한다. 데이터 경로는 파일 위치(`__file__`) 기준으로 계산되므로 어디서 실행하든
결과는 저장소 루트의 `data/voice_data/`로 모인다. 설치·실행은 `requirements.txt`가 있는
`voice/` 안에서 하는 쪽으로 통일했다.

---

## 알려진 제약사항 / TODO

- **가중치 배포 방식 미정.** 기본 경로가 개발 PC의 `C:\Dev\HMM\...`라, 다른 장비에서는 가중치를 받아 `ASR_ADAPTER_DIR`·`HMM_RUN_DIR`로 지정해야 한다
- **실제 마이크(sounddevice)로 발화 단위 인식을 검증하지 않았다.** 파일을 실시간 속도로 흘려 넣어 확인했다. 무음 판정 기본값은 장비 마이크에서 다시 맞춰야 할 수 있다
- 화자 분리(diarization)가 없어 모든 턴의 `speaker`는 `"미분리"`로 고정. HMM 입력의 줄바꿈도 화자 전환이 아니라 발화 경계다
- 파이프라인이 중간에 실패하거나 인식된 발화가 없으면 hub로 알리는 경로가 없어 hub가 계속 기다린다
- **hub는 `summary.required_department`를 매칭에 쓰지 않는다.** hub는 `mechanism`을 예상 병명으로 보고 병원 진료과 이름과 임베딩 유사도로 비교한다(`hub_engine.process_voice_summary`). HMM이 규칙으로 뽑은 진료과(`"내과"`, `"신경외과"` 등)는 받기만 하고 버려진다 — 매칭에 쓸지는 feature/hub 쪽 결정이다
- **원인이 판단 보류면 `mechanism`이 빈 문자열로 나간다.** 이때 hub의 진료과 매칭 입력이 비어 순위가 사실상 거리로만 정해진다. hub는 후보를 제외하지 않으므로 매칭 자체가 깨지지는 않는다
- ASR이 `***[개인정보]`를 출력하는 경우의 처리 보류 중
- HMM의 증상(symptoms) 필드 성능이 낮다(F1 0.19). 증상 표준명 사전도 임시 규칙이다
- Mac(MPS)·CPU 실행은 두 모델 모두 검증하지 않았다. 1.7B ASR은 CPU에서 매우 느리다
- 마이크 권한 설정 필수 (macOS: 시스템 설정 > 개인정보 보호 > 마이크)
- `data/voice_data/` 하위 전 폴더는 `.gitignore`에 포함되어 있어 오디오 원본과 변환 결과물은 저장소에 올라가지 않음
