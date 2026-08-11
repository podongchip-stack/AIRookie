# simulation3 — 시연 화면 겸 사전 튜닝 하네스

**실운영 경로가 아니다.** 실제 파이프라인은 `voice/transcribe.py`이고, 이 폴더는
같은 처리를 화면에 띄워 보여주는 껍데기다. 두 가지 용도로 쓴다.

1. **팀 시연** — 음성 하나를 넣고 STT → 교정 → 구조화가 흐르는 걸 보여준다
2. **사전 튜닝** — `corrections.json`을 늘려가며 모델·프롬프트를 바꿔 결과를 비교한다

```
음성 파일
   │ faster-whisper (cuda 시도 → 실패 시 cpu 폴백)
   ▼
STT 텍스트 ──▶ 오인식 교정 (voice/corrections.json, 정확 일치)
   ▼
교정된 텍스트 ──▶ Ollama LLM 2회 호출
   │                ├─ SBAR 구조화 (voice/summarizer.py와 동일 프롬프트)
   ▼                └─ 환자 상태 1~2문장 요약
화면 표시 (CallSummaryMessage 형태 JSON + patient_brief)
```

> **교정 필터와 사전은 `voice/`에 있다.** `text_postprocess.py`와
> `corrections.json`은 실운영 파이프라인과 **공유**한다 — 여기서 실험하며 늘린
> 항목이 그대로 실운영에 반영된다. 사전 편집 규칙과 자체 점검 방법은
> [`voice/README.md`의 "오인식 사전 관리"](../README.md#오인식-사전-관리) 참고.

---

## 실행

사전 조건: **Ollama 앱 켜기** (요약 LLM용). 이 폴더는 Ollama 자동 부트스트랩을
쓰지 않는다.

```bat
conda activate AIRookieProject
cd C:\Dev\Project\AIRookie\voice\simulation3

:: GUI (시연용)
python stt_summary_gui.py

:: CLI (GUI 없이 확인용)
python pipeline.py "<오디오파일>" --model small

:: LLM 없이 STT+교정만 (Ollama 불필요)
python pipeline.py "<오디오파일>" --model small --no-summary
```

사전을 고친 뒤 자체 점검은 `voice/`에서 돌린다.

```bat
cd C:\Dev\Project\AIRookie\voice
python text_postprocess.py
```

---

## GUI 화면

```
┌──────────────────────────────────────────────────────────┐
│  골든링크 — 응급이송 통화 자동 구조화        [개발자 옵션 ▾] │
│  통화 [ 2.m4a  (origin_data) ▾ ] [새로고침][찾아보기][▶실행]│
├──────────────────────────────────────────────────────────┤
│  ● 음성 ──▶ ● STT ──▶ ◐ 교정 ──▶ ○ 구조화    18초 경과    │
├──────────────────────────────────────────────────────────┤
│  환자 상태                                                │
│  73세 여성, 갑자기 왼팔과 다리 힘 빠짐, 말 어눌해짐...     │
├──────────────────────────────────────────────────────────┤
│  구조화 결과                                              │
│   환자  70대 여성     기전  뇌졸중 · 왼쪽 팔다리 마비      │
│   증상  [의식 혼탁][왼쪽 팔다리 마비][언어 장애]           │
│   처치  [산소 공급][정맥로 확보]      진료과  신경과       │
│                                        중증도  HIGH        │
├───────────────────────────┬──────────────────────────────┤
│  STT 원문 (교정 전)        │  교정 후 (LLM 입력)  교정 6건 │
│  ...내졸중 의심되고...     │  ...뇌졸중 의심되고...        │
│      ^^^^^^ 빨강           │      ^^^^^^ 초록              │
└───────────────────────────┴──────────────────────────────┘
```

**통화 선택**은 아래 두 폴더의 오디오를 자동으로 훑어 드롭다운에 올린다.
시연 중에 파일 탐색기를 여는 게 산만해서다 (없는 파일은 `찾아보기…`로 연다).

- `voice/data/origin_data/` — 손으로 넣어둔 통화 녹음
- `data/voice_data/origin_data/` — `call_capture.py`/`app.py`가 마이크로 녹음한 파일

**교정 전후 대비**는 교정된 구간에 색을 칠하고(전=빨강, 후=초록), 첫 교정 위치로
자동 스크롤한다 — 긴 통화에서 하이라이트가 화면 밖에 있으면 안 보이기 때문이다.

**[개발자 옵션]** 버튼을 누르면 STT 모델·장치·LLM·교정 on/off·최대 n-gram 설정과
[진행 로그 / 결과 JSON / 시스템 프롬프트] 탭이 나온다. 시스템 프롬프트를 고쳐
실행하면 그 실행에만 반영된다 (`기본값 복원`으로 되돌린다). 시연 중에는 접어두면
된다.

---

## 처리 속도 (실측)

RTX 5080 · `medium` + `qwen3:14b` · CUDA. Whisper 모델 로딩(약 4초)은 프로세스
내 캐시라 2회차부터 빠진다.

| 녹음 | 길이 | STT | 교정 | 구조화 | 요약 | 합계 |
|---|---|---|---|---|---|---|
| `1.m4a` | 108.6초 | 14.6초 | 0.0초 | 9.7초 | 4.2초 | **28.5초** |
| `2.m4a` | — | 15.8초 | 0.0초 | 11.2초 | 7.3초 | **34.3초** |

통화 1건이 **30초 안팎**이라 시연을 실시간으로 돌려도 흐름이 끊기지 않는다.
미리 돌려둔 결과를 재생하는 장치는 그래서 두지 않았다.

교정 단계는 사실상 0초다 — 정확 일치 사전 조회라 연산량이 없다.

---

## 교정 효과 (실측)

실제 전화 통화 녹음 5건을 whisper로 전사하고, 그 대본(정답)과 대조해 오인식을 뽑아
사전에 등록했다. 같은 데이터로 측정한 효과:

| 모델 | 교정 건수 | 정답과의 유사도 |
|---|---|---|
| small | 31건 | 86.24% → **88.32%** (+2.08%p) |
| medium | 15건 | 88.67% → **90.24%** (+1.56%p) |
| large-v3 | 16건 | 88.92% → **89.68%** (+0.76%p) |

같은 사전을 정답 대본에 돌리면 **교정 0건**이다 — 정상 발화는 건드리지 않는다.

사전을 늘린 뒤 실측 텍스트 45건(녹음 5 × 디코딩 설정 9종)에 적용한 결과:
**교정 161건, 정답에 가까워진 텍스트 28건, 멀어진 텍스트 0건.**

잡히는 예:

```
짐근경색을    -> 심근경색을        한은고제의   -> 항응고제의
협신증이나     -> 협심증이나         영상의약과   -> 영상의학과
의식콘탁속연이고요 -> 의식혼탁 소견이고요   내 추렬을    -> 뇌출혈을
반신 불안전 마비속연이고 -> 반신불완전마비 소견이고
```

`"1흔대"`(← 70대), `"번지회"`(← 2회) 같은 숫자·나이 오인식도 등록만 하면 잡힌다.
유사도 기반 방식으로는 원리상 불가능했던 것들이다.

---

## 폴더 구조

```
voice/
├── transcribe.py          ┐
├── summarizer.py          │ 실운영 모듈 — simulation3가 그대로 import해서 쓴다
├── text_postprocess.py    │ (사본을 두지 않으므로 처리 내용이 갈릴 수 없다)
├── corrections.json       │
├── cuda_setup.py          ┘
│
└── simulation3/
    ├── README.md              이 문서
    ├── pipeline.py            STT → 교정 → LLM. GUI가 쓰기 좋은 형태로 감싼 것
    └── stt_summary_gui.py     tkinter GUI (화면·스레드만)
```

이 폴더에는 **파일이 2개뿐이다.** 처리 로직은 전부 `voice/`에 있고, 여기 있는
건 그걸 화면에 띄우는 껍데기다.

### `pipeline.py`

`run_pipeline()` 하나가 음성 파일을 끝까지 처리해 dict로 돌려준다.

| 반환 키 | 내용 |
|---|---|
| `call_summary_message` | `voice/schema.py`의 `CallSummaryMessage`와 같은 모양 (전송은 안 함) |
| `patient_brief` | 환자 상태 1~2문장. 전송 포맷에 없는 값이라 **message 밖**에 둔다 |
| `text_postprocess` | 교정 내역(`corrections`/`correction_notice`/`max_ngram`) |
| `segments` | STT 세그먼트 원본 `[{start, end, text}]` — GUI의 "STT 원문" 탭용 |
| `timings` | 단계별 소요 시간(초) |

`voice/`에서 가져다 쓰는 것:

```python
from transcribe import STT_INITIAL_PROMPT, DEFAULT_BEAM_SIZE, UNDIARIZED_SPEAKER_LABEL
from summarizer import STRUCTURE_SYSTEM_PROMPT, structure_call_summary, summarize_patient_state
from text_postprocess import postprocess_text, CORRECTIONS_PATH, DEFAULT_MAX_NGRAM
import cuda_setup
```

자체적으로 갖고 있는 것은 `transcribe_audio()`(장치 폴백 + 모델 캐시)와
`run_pipeline()`(진행 콜백·시간 측정·결과 조립)뿐이다.

### `stt_summary_gui.py`

화면과 스레드만 담당한다. 처리는 `run_pipeline(progress=...)`에 넘기고,
콜백으로 오는 진행 메시지를 `queue`에 쌓아 `after(150ms)` 폴링으로 위젯에
반영한다 (tkinter는 워커 스레드에서 위젯을 직접 못 건드린다).

| 구성 요소 | 하는 일 |
|---|---|
| 통화 드롭다운 | `voice/data/origin_data/`와 마이크 녹음 폴더를 자동으로 훑어 목록화 |
| 단계 표시등 | 진행 메시지를 키워드로 판정해 `○ 대기 → ◐ 진행 → ● 완료` 표시 |
| 환자 상태 / SBAR 카드 | `patient_brief`와 `summary`를 큰 글씨·칩·색상 배지로 |
| 교정 전후 대비 | 교정 구간에 색을 칠하고(전=빨강, 후=초록) 첫 교정 위치로 자동 스크롤 |
| 전송 포맷 탭 | `call_summary_message`를 고정폭 폰트로 — hub가 받는 JSON 원형 |
| 개발자 옵션 | 모델·장치·LLM·교정 on/off·n-gram, 진행 로그, 시스템 프롬프트 편집 |

교정 하이라이트 위치는 교정 후 텍스트에서 길이가 달라지므로, 앞선 교정들의
길이 변화를 누적해 다시 계산한다(`_correction_spans`).

---

## 실운영 파이프라인과 다른 점

**처리 내용은 같다.** STT 프롬프트·디코딩 옵션, 교정 필터와 사전, SBAR·환자상태
프롬프트, LLM 호출, JSON 파싱, GPU 폴백 순서, CUDA DLL 등록을 전부 `voice/`에서
import해서 쓴다. 같은 오디오를 양쪽에 넣어 `raw_text`·`filtered_text`·전송 포맷이
글자 단위로 일치하는 것까지 확인했다.

다른 것은 **주변 장치**뿐이다.

| | `voice/` (실운영) | `simulation3/` |
|---|---|---|
| hub 전송·파일 저장·pydantic 검증 | 있음 | **없음** (dict 반환만) |
| `caseId` | hub가 내려준 값 | 파일명 기반 자동 생성 (CLI 단독 실행과 같은 규칙) |
| 진행 콜백·단계별 소요 시간 | 없음 | **있음** (GUI 단계 표시등용) |
| Whisper 모델 캐시 | 없음 (프로세스당 1회) | **있음** (반복 실행용) |
| SBAR 프롬프트 실행 중 교체 | 없음 | **있음** (GUI 편집) |
| 환자 상태 1~2문장 요약 | 없음 | **있음** — 정해진 전송 포맷에 없는 값이라 `call_summary_message` **밖**에 담는다 |
| `language` / `compute_type` 조절 | CLI 인자 | `ko` / `auto` 고정 |

> 전송 포맷(`CallSummaryMessage`)은 hub·dashboard와의 **고정 계약**이다. 시뮬레이터가
> 임의로 필드를 늘리지 않는다 — 화면에 보이는 JSON이 실제로 hub가 받는 것과
> 달라지면 시연이 거짓말이 된다.

### 알려진 문제

- `summary` 값(증상 표현 등)은 같은 입력에도 실행마다 조금씩 달라진다. LLM 샘플링이
  비결정적이라 시뮬을 두 번 돌려도 마찬가지다. 판정에 쓰이는 `severity_tag`·
  `required_department`는 실측에서 일치했다. 완전히 고정하려면 Ollama 호출에
  `temperature: 0`을 줘야 하는데 실운영 동작이 바뀌는 일이라 별도 결정이 필요하다
- 위 "교정 효과" 수치는 `STT_INITIAL_PROMPT`가 팀 것으로 통일되기 전에 측정한
  값이다. 지금 기준으로 다시 재야 한다
