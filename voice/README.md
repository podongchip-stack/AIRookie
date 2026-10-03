# feature/voice — 음성 STT(Qwen3-ASR) · 정보 구조화(MF_BERT) 파이프라인

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

**2. 가중치** — 두 모델 모두 저장소에 없고(용량) Hugging Face Hub에 있다.
따로 받을 필요 없이 첫 실행 때 Hugging Face 캐시(`HF_HOME`)로 자동으로 내려받는다(인터넷 필요, 로그인 불필요).

| Hub 저장소 · 경로 | 내용 | 로컬 폴더로 대신 쓰려면 |
| --- | --- | --- |
| [`Playedwell03/qwen3-asr-0.6b-119ko-tiny`](https://huggingface.co/Playedwell03/qwen3-asr-0.6b-119ko-tiny) | Qwen3-ASR-0.6B LoRA 어댑터 (`adapter_config.json`, `adapter_model.safetensors`) | `ASR_ADAPTER_DIR` |
| [`podongchip/MF_BERT`](https://huggingface.co/podongchip/MF_BERT) | MF_BERT 체크포인트 `best.pt`(약 1.4GB) + `tokenizer/` | `MF_BERT_DIR` |

환경변수를 주면 Hub에서 받지 않고 그 폴더를 쓴다(재학습한 가중치를 올리기 전에 시험할 때 등, `weights.py`).
MF_BERT는 **2026-10-02 모델의 Hub 커밋 해시 `f1d3e1dbd41424e1bb32cf4aded891ed48b39df6`로 고정**해서 받는다
(`weights.py`의 `MF_BERT_REVISION` 기본값, 2026-10-03). `main`이나 태그 대신 해시를 쓰는 이유는, Hub에 구조가 바뀐
가중치가 올라오면 `MF_BERT/` 코드와 state_dict가 안 맞아 서버가 아예 뜨지 않기 때문이다(2026-10-03 실제로 겪음).
이전 2026-09-30 모델은 `MF_BERT_REVISION=v1-2026-09-30`으로 받을 수 있고 지금 코드로도 읽힌다 — 체크포인트의 학습
인자에 보기별 어텐션·헤드 층 수가 없으면 `args.get(...)` 기본값으로 예전 구조를 만든다(`MF_BERT/__init__.py`).
새 가중치를 들여올 때는 `MF_BERT/` 코드를 먼저 맞춘 뒤 이 해시를 바꾼다.
ASR 베이스 모델(`Qwen/Qwen3-ASR-0.6B-hf`)과 MF_BERT 인코더 설정(`klue/roberta-large`의 config만 — 인코더 가중치는
체크포인트에 들어 있어 받지 않는다)도 같은 캐시로 자동으로 내려받는다. 이전 구조화 모델 저장소
`podongchip/goldenlink-voice-models`(HMM v1·v2 가중치)는 더 이상 쓰지 않는다.

**3. 실행** — 마이크로 바로 시작해볼 수 있다 (`voice/` 안에서):

```bash
python call_capture.py
```

모델을 올린 뒤(약 15~20초) 녹음이 시작된다. 말이 끊길 때마다 `[발화 인식]` 줄이 찍히고,
Ctrl+C를 누르면(통화 종료) 남은 발화를 인식한 뒤 구조화 → hub 전송까지 이어서 실행된다.

---

## 이 브랜치가 하는 일

통화 음성을 텍스트로 바꾸고 → v2 스키마(17개 필드)로 구조화해 → `feature/hub`로 보낸다.
dashboard로는 직접 보내지 않고 `feature/hub`를 거쳐 전달된다.

```
마이크 ─▶ [STT] Qwen3-ASR + LoRA ─▶ 발화 텍스트 ─▶ [구조화] MF_BERT ─▶ summary(v2 17필드) ─▶ feature/hub
          통화 중 발화 단위로 인식                    분류·태깅 모델 (생성형 아님)
```

> **2026-09-24 교체.** 이전 경로(faster-whisper → `corrections.json` 오인식 교정 →
> Ollama `qwen3:14b` SBAR 구조화)는 코드째 삭제했다. 두 모델은 팀이 따로
> 파인튜닝한 것으로, 추론 코드만 이 폴더(`asr.py`, `MF_BERT/`)에 복사해 넣었다.
>
> **2026-10-01 구조화 모델 교체.** HMM v2(`hmm/`)를 지우고 MF_BERT(`MF_BERT/`)로 바꿨다. 출력층·디코더·
> 라벨이 같아 `summary`(v2 17필드) 형식은 그대로다. 바뀐 것은 긴 통화를 512토큰 조각으로 나눠 넣는 입력 처리와
> 가중치 저장소다([구조화 — MF_BERT](#구조화--mf_bert-mf_bert) 참고).
>
> **2026-10-03 MF_BERT를 2026-10-02 모델로 갱신.** 다중 선택 헤드에 보기별 어텐션, 분류 헤드를 2층으로 바꾼
> 모델에 맞춰 `MF_BERT/model.py`·`__init__.py`를 고치고 가중치를 커밋 해시로 고정했다. `labels.py`·`decode.py`·
> `parse.py`는 바뀌지 않아 `summary`(v2 17필드) 형식은 그대로다.

**진입점은 3개**다. 셋 다 같은 모델·같은 후처리(`transcribe.emit_call_summary()`)를 쓰고
출력 JSON 스키마도 같다.

| 진입점 | 언제 쓰나 | 통화 시작 / 종료 | 인식 방식 |
| --- | --- | --- | --- |
| `app.py` | **실운영.** hub가 dashboard의 신호를 HTTP로 중계 | `POST /call/start` / `/call/end` | 통화 중 발화 단위 |
| `call_capture.py` | 마이크로 직접 통화를 흉내내는 CLI 테스트 | 실행 / `Ctrl+C` | 통화 중 발화 단위 |
| `transcribe.py` | 이미 녹음된 파일 배치 처리 | (해당 없음) | 파일 통째로 5초 조각 |

시연·튜닝용 화면은 `simulation3/gui.py`에 따로 있다 — 같은 모듈을 쓰면서 통화 중에 v2 17필드·hub JSON을 실시간으로 보여준다(전송은 안 함). 사용법은 [`simulation3/README.md`](simulation3/README.md).

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

**실행 스크립트(2026-10-03, 권장)** — macOS·Linux·Windows(Git Bash) 공통. OS를 보고 conda 환경의 파이썬
(`rookie_voice` → `AIRookieProject` → `rookie` 순, `VOICE_PY`로 지정 가능)을 찾고, 구급차별 포트(역삼 6001·성산 6002·
회현 6003)와 hub 주소를 맞춰 넣는다. `HUB_BASE_URL`만 바꾸면 `HUB_VOICE_SUMMARY_URL`도 같은 hub로 따라간다 —
예전엔 둘을 따로 줘야 해서, hub 주소만 바꾸면 환자 정보가 voice 자신(127.0.0.1)으로 가서 사라졌다.

```bash
./voice/start-voice.sh A0000001                                  # hub가 같은 장비
HUB_BASE_URL=http://192.168.0.3:5001 ./voice/start-voice.sh A0000001   # hub가 다른 장비
```

Windows 콘솔 기본 인코딩(cp949)은 이모지 등을 못 써서 로그 한 줄에 서버가 죽을 수 있었다. 실행 진입점(`app.py`·
`call_capture.py`·`transcribe.py`·`mic_recorder.py`)이 시작할 때 `console.py`의 `use_utf8_console()`로 출력을
UTF-8로 바꾸므로 `PYTHONUTF8=1` 없이도 된다(파일 읽기·쓰기는 원래 전부 `encoding="utf-8"`).

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
| `ASR_ADAPTER_DIR` / `MF_BERT_DIR` | (없음 — Hub에서 받음) | 가중치를 로컬 폴더로 대신 쓸 때. [빠른 시작](#빠른-시작) 참고 |

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
│   MfBertExtractor.extract()     MF_BERT 점수 → v2 17필드 (decode)│
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
| 구조화 | `summary` | `{"ktas_level": 2, "chief_complaint": {"major": "I 심혈관계", "minor": "흉통(심장성)"}, "age": {"years": 62, ...}, "sex": "남성", ...}` (v2 17필드) |
| 전송 | `CallSummaryMessage` | 위 전부 + `caseId`·`source`·`model_used` |

### 실측 소요 시간

RTX 5080 · CUDA · bf16 · 108.6초 통화(`1.m4a`) 기준.

| 단계 | 소요 |
| --- | --- |
| 모델 로딩 (ASR + 구조화 모델) | 14~20초 *(프로세스당 1회, HMM v2 때 측정)* |
| **통화 종료 → hub 수신** (`app.py`, 발화 단위 인식) | **3.7초** |
| 참고: 같은 통화를 끝나고 한 번에 인식 (`transcribe.py`) | ASR 61.1초 |
| 구조화 (MF_BERT) | 0.01~0.03초 *(프로세스 첫 호출만 약 0.3초)* |

`app.py` 수치는 실제 마이크 대신 파일을 실시간 속도로 흘려 넣어 잰 값이고, 구조화 모델이 HMM v2였을 때 쟀다.
MF_BERT만 따로 잰 값(Linux · RTX 5080 · 텍스트 입력)은 캐시에서 올리는 데 5.7초, GPU 메모리 1.41GB다.
구조화는 두 모델 모두 1초 미만이라 종료 → hub 수신 시간은 거의 그대로일 것으로 보지만, 교체 후 다시 재지는 않았다.

### 실패해도 죽지 않는 지점 / 죽는 지점

| 상황 | 동작 |
| --- | --- |
| GPU 없음 | **계속** — ASR은 mps/cpu, MF_BERT는 cpu로 (매우 느림, 미검증) |
| 가중치를 못 받음(오프라인 첫 실행) / 환경변수 폴더 없음 | **시작 실패** — 다운로드 오류나 `FileNotFoundError`로 서버가 뜨지 않는다 |
| 통화 중 인식 예외 | **계속** — 종료 시 남은 소리를 한꺼번에 다시 인식 |
| 인식된 발화가 없음(무음 통화) | 구조화·전송을 **건너뜀** (원문 `.txt`는 빈 파일로 남음) |
| hub 미기동 | **계속** — 파일 저장까지 완료, stderr에만 알림 |

> `app.py`는 남은 처리를 백그라운드 스레드로 돌리고 `/call/end`에 이미 200을
> 응답한 뒤다. 구조화나 전송 전에 스레드가 죽거나 발화가 없어 건너뛰면 **hub는 계속
> 기다린다** — 실패를 hub로 알리는 경로가 아직 없다 (알려진 제약사항 참고).

---

## 모델 설명

### STT — Qwen3-ASR-0.6B + LoRA (`asr.py`)

| 항목 | 내용 |
| --- | --- |
| 베이스 | `Qwen/Qwen3-ASR-0.6B-hf` |
| 어댑터 | [`Playedwell03/qwen3-asr-0.6b-119ko-tiny`](https://huggingface.co/Playedwell03/qwen3-asr-0.6b-119ko-tiny) — LoRA r=32 (alpha 32), 학습 가능 파라미터 29.5M |
| 학습 데이터 | AI Hub 119 신고 음성 20시간 (합성 노이즈 증강 포함) |
| 검증 | 깨끗한 음성 CER 0.187 (모델 카드 기준, 1.7B 어댑터 0.188과 통계적으로 동등). 소음 환경은 1.7B가 더 낫다(군중 소음 5dB에서 CER 차이 0.124) |
| 입력 단위 | 학습 데이터가 평균 2초 발화라 5초 안팎으로 잘라 인식(20초 단위는 문장이 통째로 빠졌음) |

- 이전 1.7B 어댑터에서 0.6B로 바꿨다(2026-09-29). 프롬프트 형식(`language Korean<asr_text>`)과 5초 분할은 그대로 두었고, 새 어댑터로 실제 음성 인식 품질은 아직 측정하지 않았다
- **틀린 결과도 자연스러운 문장처럼 나온다** (예: `심근경색` → `짐근경색`, `식은땀` → `찌근땀`). 구급대원 확인·수정(Override)을 거쳐야 한다
- 학습 데이터의 개인정보 마스킹 표기 때문에 `***[개인정보]`를 출력하는 경우가 있다 (처리 방법 보류 중)
- 검증은 신고자↔119 통화로 했다. **구급대원↔병원 통화, 소음이 큰 현장에서의 성능은 측정하지 않았다**

### 구조화 — MF_BERT (`MF_BERT/`)

KLUE RoBERTa-large 인코더에 출력층 여러 개를 붙인 다중과제 모델이 필드별 점수를 내고(AI),
`decode.py`가 그 점수를 v2 스키마로 푼다. 활력징후·나이·발생 시점의 숫자는 모델이 찾은 구간을
규칙(`parse.py`)으로 읽는다. **생성형 모델이 아니라** 출력 형식이 깨질 일이 없고, 같은 입력에는
항상 같은 결과가 나온다. 필드 정의는 `C:\Dev\HMM\data_v3\필드_설명.md`가 원본이다.

긴 통화는 512토큰 조각(128토큰씩 겹침)으로 나눠 인코딩하고, 겹친 토큰은 한 조각 것만 남겨 원문 토큰
줄로 다시 이어 붙인다(`chunking.py`). 이전 HMM v2는 포지션 임베딩을 2048칸으로 늘려 한 번에 넣었지만,
MF_BERT는 사전학습된 512칸만 쓴다. 조각이 하나뿐인 짧은 통화는 두 방식의 계산이 같다.

| 출력층 | 하는 일 | v2 필드 |
| --- | --- | --- |
| 단일 선택 8개 | KTAS 등급, 주 호소 대분류·소분류, 주 기전, 질병 분류, 성별, 의식(AVPU), 복용약 유무 | `ktas_level` `chief_complaint` `incidents` `disease_category` `sex` `consciousness` `medications` |
| 다중 선택 7개 | 기전(+세부), 처치(+세부), 증상, 손상(+좌우) — 확률 0.5 이상 | `incidents` `treatments` `symptoms` `injuries` |
| 구간 태거 | 활력징후·나이·발생 시점·의심 진단·복용약 구간(BIO) 태깅 | `vitals` `age` `onset` `suspected_diagnosis` `medications` |

`call_type`·`ktas_evidence`·`notes`는 모델이 배우는 항목이 아니라 항상 `null`이고, 그 사실이 `summary.meta.not_predicted`에 들어 있다.

**모델 구조** (`MF_BERT/model.py` 머리말과 같다. 지금 받는 모델은 2026-10-02 모델)

```
조각 인코딩    H^(j)_c = Encoder(chunk_c)                    512토큰 조각마다 KLUE RoBERTa-large
토큰 복원      H^(j) = concat_c H^(j)_c[keep_c]              겹친 토큰은 한 조각 것만 남겨 원문 토큰 줄로 이어 붙임 (chunking.py)
층 혼합        h_t = gamma * sum_j softmax(w)_j H^(j)_t       마지막 4층, 문장용·토큰용 두 그룹, layer dropout
풀링           alpha_t = softmax_t(q_k . h_t / sqrt(d))       단일 선택 헤드 k마다 query 하나, 통화 전체 토큰 대상
보기별 어텐션  alpha_t = softmax_t(q_{k,o} . h_t / sqrt(d))   다중 선택 헤드 7개는 보기 o마다 query 하나 (모두 292개, LabelAttentionHead)
분류 헤드      [dropout -> Linear -> GELU -> LayerNorm] -> dropout -> dense -> tanh -> dropout -> out_proj
               대괄호가 2층 헤드로 더해진 층 (head_layers=2, head_trunk). 보기별 어텐션 헤드에도 똑같이 붙는다
구간 태거      토큰별 선형 한 겹 -> 11태그 (VITALS·AGE·ONSET·DX·MED의 BIO)
```

- **보기별 어텐션**: 예전에는 다중 선택 헤드마다 query 하나로 통화 전체를 벡터 하나로 요약하고, 그 벡터 하나로 보기 전부(증상 88개, 손상 81개 등)를 판단했다.
  "구토는 없어요"처럼 한 문장에만 있는 정보가 요약에 묻히기 쉬웠다. 이제는 보기마다 자기 근거 토큰을 따로 가중 평균한다.
  dense·tanh는 보기끼리 나눠 쓰고, 마지막 층은 보기마다 가중치 벡터 하나로 점수를 낸다. 단일 선택 8개는 헤드마다 query 하나 그대로다
- **2026-09-30 모델과의 차이**: 09-30 모델은 15개 헤드가 모두 헤드마다 query 하나, 분류 헤드는 1층이었다. 파라미터 수는 0.35B → 0.37B다(원본 `docs/MF_BERT.md`)
- **학습 쪽 변경**(원본 `docs/MF_BERT.md`, 원본 실행 폴더 `2026-10-02_120702`):
  - 다중 선택 BCE의 양성 항에 보기별 양성 가중치(`sqrt(음성 수/양성 수)`, 상한 10)를 곱한다
  - KTAS 기대 비용 손실을 더한다(등급 차이만큼 비용, 가볍게 틀리면 2배)
  - 층별 학습률 감소: 인코더 맨 위층 2e-5에서 한 층 내려갈 때마다 0.95배
  - 학습 데이터에 부정 증상을 보강했다. 원문이 분명히 부정했는데 라벨에서 빠진 부정 증상을 Sonnet 라벨러로 찾아 더했다
  - 데이터는 정제·재라벨·부정 보강을 거친 8,082건이다. 분할은 5-fold가 아니라 균형 9:1 한 번이다(학습 7,188 / 검증 894)
- 출력층 구성·보기 목록·디코딩(다중 선택 기준 0.5)은 그대로라 `labels.py`·`decode.py`·`parse.py`는 바뀌지 않았고 `summary` 형식도 같다

**성능 — 2026-09-30 모델 기준** (합성 통화 대본 8,990건, 5-fold 교차검증 — `/mnt/D/Project/BERT_Multiclass Classification/BERT/train_kfold.py`, 실행 `2026-09-30_183446`)

지금 받는 2026-10-02 모델은 아직 이 저장소 기준으로 성능을 재지 않았다. 벤치마크를 돌려 오른쪽 칸을 채울 예정이다.

| 항목 | 2026-09-30 모델 (5-fold 평균 ± 표준편차) | 2026-10-02 모델 (현재 배포) |
| --- | --- | --- |
| 종합 score | 0.6912 ± 0.0041 (배포 체크포인트였던 fold00: 0.6934) | 측정 예정 |
| 긴 통화(조각 2개 이상)만 종합 score | 0.6346 ± 0.0153 | 측정 예정 |
| 성별 / 복용약 유무 / 주 기전 정확도 | 0.996 / 0.975 / 0.950 | 측정 예정 |
| KTAS 정확도 · macro-F1 | 0.791 · 0.779 | 측정 예정 |
| 주 호소 대분류 / 소분류 정확도 | 0.923 / 0.872 | 측정 예정 |
| 증상 micro-F1 · macro-F1 | 0.672 · 0.431 | 측정 예정 |
| 처치 micro-F1 · macro-F1 | 0.730 · 0.384 | 측정 예정 |
| 손상 micro-F1 (좌우 포함 0.309) | 0.482 — **가장 약함** | 측정 예정 |
| 구간 span F1 | 0.696 | 측정 예정 |

- (09-30 모델) 배포 체크포인트는 전체 데이터로 다시 학습한 모델이 아니라 fold00이었다. 5개 fold 중 검증 score가 가장 높은 건 fold04(0.6977)이고 fold00은 두 번째다. 이 fold의 검증 데이터는 다른 fold 학습에 쓰였으므로 위 수치는 평균값을 기준으로 읽는다
- (09-30 모델) **이전 HMM v2의 수치(score 0.7312)와 직접 비교할 수 없다** — 학습·검증 데이터가 다르다(HMM v2는 `data_v3` 9,677건 중 `edge`·119 신고 제외)
- 10-02 모델은 학습 데이터(8,082건 정제본)와 분할(균형 9:1)이 달라, 측정 후에도 09-30 모델의 5-fold 수치와는 같은 조건의 비교가 아니다
- 학습 데이터는 전부 합성 통화 대본이고 라벨도 Claude로 자동 생성했다(일부 레코드 meta에 "사람 검수 전"으로 표시)
- 학습 데이터는 "줄바꿈 = 화자 전환"인 대본 형태다. 여기 입력은 "줄바꿈 = 발화 경계"라 완전히 같은 형태가 아니고, **실제 음성 입력에서의 성능은 측정하지 않았다**
- 복사해 온 코드가 원본 `mf_bert/infer.py`의 `predict()`와 같은 결과를 내는지는 **09-30 모델로만** 대조했다(fold00 검증 데이터 15건, 조각 3개짜리 긴 통화 5건 포함, 전부 동일). **2026-10-02 모델로는 같은 대조를 하지 않았다(미검증)**

---

## 사용한 AI / 모델

| 구분 | 모델 | 처리 방식 |
| --- | --- | --- |
| STT | Qwen3-ASR-0.6B + LoRA (`Playedwell03/qwen3-asr-0.6b-119ko-tiny`) | AI 처리 |
| 정보 구조화 — 필드 판정 | KLUE RoBERTa-large 다중과제 모델 MF_BERT (팀 학습, `podongchip/MF_BERT` 2026-10-02 모델 — 다중 선택 헤드 보기별 어텐션 + 2층 분류 헤드, [모델 구조](#구조화--mf_bert-mf_bert)) | AI 처리 (분류·태깅, 생성형 아님) |
| 정보 구조화 — 점수 해석·숫자 파싱 | *(모델 없음, `MF_BERT/decode.py`·`MF_BERT/parse.py`)* | 규칙 기반 |

**개발 환경**: Python 3.11, torch 2.11 (CUDA 12.8), transformers 5.17, peft, flask.
Qwen3-ASR이 transformers 5.13 이상을 요구한다. 전부 로컬에서 돌아가며 외부 API로 음성·텍스트가 나가지 않는다.

---

## 입출력 데이터 포맷

**입력**: 마이크(16kHz 모노) 또는 오디오 파일(wav·m4a 등)

**출력**: `feature/hub`로 전달되는 JSON. dashboard로는 직접 보내지 않는다.
`feature/dashboard`의 `CallSummaryMessage` 타입과 1:1 대응하며(`schema.py`),
**`summary`는 2026-09-29에 v1(6필드)에서 v2 스키마(17필드 + `meta`)로 바뀌었다(2026-10-01 구조화 모델을 MF_BERT로 바꾸고 2026-10-03 10-02 모델로 갱신했어도 형식은 같다). hub·dashboard 쪽 수정은 담당자가 따로 진행한다.**

```json
{
  "caseId": "case-abc123",
  "transcript": {
    "raw_text": "62세 남성이고요.\n30분 전부터 갑자기 가슴이 쥐어짜는 듯이 아프다고 하십니다.\n식은땀 나고 왼쪽 팔까지 아파요. 혈압 150에 90 맥박 110 산소포화도 96이고요.\n의식은 명료하고 산소 투여하고 심전도 시행했습니다. 심근경색 의심됩니다.",
    "filtered_text": "62세 남성이고요.\n30분 전부터 갑자기 가슴이 쥐어짜는 듯이 아프다고 하십니다.\n식은땀 나고 왼쪽 팔까지 아파요. 혈압 150에 90 맥박 110 산소포화도 96이고요.\n의식은 명료하고 산소 투여하고 심전도 시행했습니다. 심근경색 의심됩니다.",
    "language": "ko",
    "timestamp": "2026-09-29T07:53:04Z",
    "duration_sec": 42.3,
    "turns": [
      {
        "speaker": "미분리",
        "timestamp": "07:53:29",
        "text": "62세 남성이고요."
      }
    ]
  },
  "summary": {
    "call_type": null,
    "ktas_level": 2,
    "ktas_evidence": null,
    "chief_complaint": {
      "major": "I 심혈관계",
      "minor": "흉통(심장성)"
    },
    "suspected_diagnosis": [
      {
        "text": "심근경색 의심"
      }
    ],
    "vitals": [
      {
        "sequence": 1,
        "sbp": 150,
        "dbp": 90,
        "hr": 110,
        "rr": null,
        "bt": null,
        "spo2": 96,
        "glucose": null,
        "evidence": [
          "혈압 150에 90 맥박 110 산소포화도 96이고요"
        ]
      }
    ],
    "consciousness": [
      {
        "sequence": 1,
        "avpu": "A"
      }
    ],
    "symptoms": [
      {
        "standard_name": "흉통",
        "status": "확인"
      }
    ],
    "onset": {
      "text": "30분 전부터",
      "minutes_ago": 30
    },
    "incidents": [
      {
        "type": "질병",
        "detail": null,
        "primary": true
      }
    ],
    "disease_category": "심장질환",
    "injuries": [],
    "treatments": [],
    "age": {
      "years": 62,
      "months": null,
      "band": null,
      "evidence": [
        "62세 남성이",
        "요"
      ]
    },
    "sex": "남성",
    "medications": {
      "status": "미언급",
      "items": []
    },
    "notes": null,
    "meta": {
      "not_predicted": [
        "call_type",
        "ktas_evidence",
        "notes"
      ]
    }
  },
  "source": "ai",
  "model_used": {
    "stt": "qwen3-asr-0.6b-119ko-tiny",
    "llm": "mf-bert-klue-roberta-large"
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
| `summary` | object | MF_BERT 출력 그대로(v2 스키마) — 17개 필드(`call_type` `ktas_level` `ktas_evidence` `chief_complaint` `suspected_diagnosis` `vitals` `consciousness` `symptoms` `onset` `incidents` `disease_category` `injuries` `treatments` `age` `sex` `medications` `notes`)와 `meta`. 각 필드의 뜻은 `C:\Dev\HMM\data_v3\필드_설명.md`. 값이 없는 필드도 `null`·빈 목록으로 **빠지지 않고 나간다** |
| `summary.ktas_level` | 1~5 | Pre-KTAS 중증도. 1이 가장 위급. 항상 값이 있다 |
| `summary.call_type` `ktas_evidence` `notes` | null | 모델이 예측하지 않는 항목이라 항상 `null` |
| `source` | `"ai"` | AI 처리 결과 고정값 |
| `model_used.stt` / `model_used.llm` | string | 실제 사용된 모델명. `llm`은 필드명만 유지할 뿐 생성형 모델이 아니다 |

`summary.vitals`는 통화 속 발화에서 읽은 값일 뿐, 별도 바이탈 수집·전송 경로는 없다.

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
│   ├── MF_BERT/                 [구조화] MF_BERT 모델 + 디코더
│   │   ├── __init__.py          MfBertExtractor — 체크포인트 로딩, 텍스트 → v2 17필드
│   │   ├── model.py             모델 정의 (체크포인트 state_dict와 구조가 같아야 함)
│   │   ├── chunking.py          긴 통화 → 512토큰 조각, 조각 → 원문 토큰 줄 복원
│   │   ├── labels.py            출력층 보기 목록 (순서를 바꾸면 체크포인트와 안 맞음)
│   │   ├── decode.py            점수 → v2 필드 (주 호소는 대분류에 속한 소분류만, 구간은 BIO 태그)
│   │   └── parse.py             활력징후·나이·발생 시점 구간 → 숫자 (규칙)
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
MF_BERT.MfBertExtractor schema   send_to_hub()
   (model→decode)    (pydantic)      hub POST
```

화살표가 한 방향뿐이고 순환이 없다. `MF_BERT/`·`schema.py`·`mic_recorder.py`는 다른 로컬
모듈에 의존하지 않아, 모델을 바꿔도 영향 범위가 그 폴더·파일로 묶인다.

### 경로 규칙

모든 파이썬 코드가 `voice/` 한 폴더에 평평하게 있어(`MF_BERT/`만 패키지) 상호 import가
그대로 동작한다. 데이터 경로는 파일 위치(`__file__`) 기준으로 계산되므로 어디서 실행하든
결과는 저장소 루트의 `data/voice_data/`로 모인다. 설치·실행은 `requirements.txt`가 있는
`voice/` 안에서 하는 쪽으로 통일했다.

---

## 알려진 제약사항 / TODO

- **실제 마이크(sounddevice)로 발화 단위 인식을 검증하지 않았다.** 파일을 실시간 속도로 흘려 넣어 확인했다. 무음 판정 기본값은 장비 마이크에서 다시 맞춰야 할 수 있다
- 화자 분리(diarization)가 없어 모든 턴의 `speaker`는 `"미분리"`로 고정. MF_BERT 입력의 줄바꿈도 화자 전환이 아니라 발화 경계다
- 파이프라인이 중간에 실패하거나 인식된 발화가 없으면 hub로 알리는 경로가 없어 hub가 계속 기다린다
- **hub·dashboard가 아직 v1 `summary`(6필드)를 기대한다.** `patient`·`mechanism`·`symptoms`(문자열 목록)·`treatment`·`severity_tag`·`required_department`가 사라져 hub가 이 메시지를 그대로는 처리하지 못한다 — hub 담당자가 v2 17필드를 읽도록 고쳐야 한다
- v2에는 진료과(`required_department`)를 내는 규칙이 없다. 예전 원인·부위 → 전문과목 대응표는 v1 라벨 기준이라 함께 삭제했다
- ASR이 `***[개인정보]`를 출력하는 경우의 처리 보류 중
- MF_BERT에서 손상(injury micro-F1 0.48)·처치·증상의 희귀 라벨 성능이 낮다(macro-F1 각각 0.30·0.38·0.43 — **2026-09-30 모델 수치**). 10-02 모델은 보기별 어텐션·양성 가중치로 이 부분을 노렸지만 이 저장소 기준 수치는 측정 예정이다
- Mac(MPS)·CPU 실행은 두 모델 모두 검증하지 않았다. ASR은 CPU에서 느리다
- 마이크 권한 설정 필수 (macOS: 시스템 설정 > 개인정보 보호 > 마이크)
- `data/voice_data/` 하위 전 폴더는 `.gitignore`에 포함되어 있어 오디오 원본과 변환 결과물은 저장소에 올라가지 않음
