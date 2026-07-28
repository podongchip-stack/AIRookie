# feature/voice — 유튜브/음성 파일 STT 변환 및 로컬 LLM 요약 파이프라인

## 담당자

- 이름: 이승주
- 역할: 리드 개발자
<!-- -->
- 이름: 곽호영
- 역할: 리드 개발자

## 이 브랜치가 하는 일

유튜브 오디오 다운로드 → 음성 파일을 텍스트로 변환 → 실시간 음성 필터링(의료 관련 문장 분류) → SBAR 구조화 → feature/dashboard 전달용 JSON 생성까지 이어지는 파이프라인입니다.

- **`youtube_downloader.py`** — 유튜브 URL을 입력하면 오디오만 추출해 `data/` 폴더에 저장하는 간단한 GUI 도구 (tkinter)
- **`transcribe.py`** — 로컬 오디오 파일을 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)로 텍스트 변환하고, `--summarize` 옵션을 주면 실시간 음성 필터링 + SBAR 구조화까지 수행해 JSON을 출력하는 CLI 도구
- **`filtering.py`** — 발화 턴 단위로 의료 관련 여부를 분류하는 경량 분류기 (아래 "실시간 음성 필터링" 참고)
- **`summarizer.py`** — 필터링된 텍스트를 [Ollama](https://ollama.com)에 붙어 있는 로컬 LLM으로 SBAR 형태 JSON으로 구조화
- **`schema.py`** — feature/dashboard의 `CallSummaryMessage`와 1:1로 대응하는 pydantic 출력 스키마

> `transcribe.py`는 여전히 로컬 파일 기반 프로토타입이다 (실시간 스트림 입력은 추후 전환 예정). 다만 출력 포맷은 아래 "입출력 데이터 포맷"에 정의된 확정 JSON 스키마를 그대로 따른다.

## 사용한 AI / 모델

| 구분 | 모델명 | 용도 | 비고 |
|---|---|---|---|
| STT | Whisper large-v3 (CTranslate2 변환판, faster-whisper 기본값) — [Systran/faster-whisper-large-v3](https://huggingface.co/Systran/faster-whisper-large-v3) | 음성 → 텍스트 변환 | `--model` 옵션으로 크기 변경 가능 |
| 의료 관련성 분류 | paraphrase-multilingual-MiniLM-L12-v2 (sentence-transformers) — [sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) | 발화 턴이 의료 관련 내용인지 분류 (실시간 음성 필터링) | `filtering.py`, CLAUDE.md의 "경량 분류기" 선택지 |
| 정보 구조화 | Qwen3-14B (Ollama `qwen3:14b`) — [Qwen/Qwen3-14B](https://huggingface.co/Qwen/Qwen3-14B) | 필터링된 텍스트 → SBAR 구조화 JSON | `--llm-model` 옵션으로 변경 가능 |

> CLAUDE.md의 "핵심 AI 활용 원칙" 표 기준으로, 이 기능이 AI 처리 영역인지 규칙 기반 영역인지 명시:
> - [x] AI 처리
> - [ ] 규칙 기반

## 개발 환경 / 언어

- 언어: Python 3.11 (`requirements.txt` 상단 주석 참고)
- 주요 라이브러리·프레임워크: faster-whisper, sentence-transformers(의료 관련성 분류), Ollama, tkinter, pydantic
- 실행 환경: 로컬 (GPU 있으면 CUDA 12.x 가속, 없으면 CPU. macOS는 CTranslate2가 Metal/MPS 미지원으로 항상 CPU 동작)

## 실시간 음성 필터링

STT 결과를 발화 턴(문장) 단위로 분리한 뒤, 각 턴이 의료 관련 내용인지 분류해서 잡담·인사말·통화
연결 발화를 요약 대상에서 제외하고, 의료 관련 문장만 LLM에 전달해 SBAR 형태로 구조화한다.
CLAUDE.md의 "통화 내용 필터링·구조화 (AI: sLLM + KM-BERT)" 항목을 구현한 것이다.

**분류 방식** (`filtering.py`)
- 라벨링된 학습 데이터가 없어 KM-BERT를 직접 파인튜닝하는 대신, 다국어 문장 임베딩 모델
  (`paraphrase-multilingual-MiniLM-L12-v2`)로 "의료 관련" 예시 문장들의 중심 벡터를 만들고,
  각 발화 턴과의 코사인 유사도가 threshold(기본 0.4) 이상이면 의료 관련으로 분류한다.
- CLAUDE.md가 "경량 분류기 또는 KM-BERT" 중 하나를 허용하므로, 이는 그중 경량 분류기 선택지에
  해당한다. 나중에 라벨 데이터가 쌓이면 `MedicalRelevanceFilter`를 KM-BERT 분류 헤드로 교체해도
  호출부(`transcribe.py`)는 바뀌지 않는다.
- 검증 예시 (`파일 내 anchor 문장 vs 테스트 문장 코사인 유사도`): 의료 관련 문장은 0.57~0.76,
  잡담/인사말은 0.13~0.29로 나와 threshold 0.4로 명확히 구분됨을 확인함.

**원본 보존 원칙**
- 필터링에서 제외된 발화도 삭제하지 않는다. `transcript.raw_text`와 `transcript.turns`에는
  모든 발화가 그대로 남고, 제외된 턴에만 `excludedFromSummary: true`가 붙는다.
- `transcript.filtered_text`(요약 입력값)와 `summary.*`(SBAR 구조화 결과)에만 의료 관련
  발화가 반영된다.

**구조화** (`summarizer.py`)
- 필터링된 텍스트를 Ollama(`/api/generate`, `format: "json"`)에 전달해 `patient` / `mechanism`
  / `symptoms` / `treatment` / `severity_tag` / `required_department` 필드를 가진 JSON으로
  구조화한다. LLM 응답이 JSON 파싱에 실패하거나 Ollama가 꺼져 있으면 예외를 던지고 파이프라인은
  중단된다 (원본 텍스트 파일은 이미 저장된 상태라 데이터 손실은 없음).

**알려진 한계**
- 화자 분리(diarization)가 아직 없어 모든 턴의 `speaker`는 `"미분리"`로 고정되어 있다.
- threshold 기반 분류기라 애매한 경계 문장은 오분류할 수 있다. 실제 통화 녹음으로 threshold를
  재조정하거나 KM-BERT로 교체하는 게 다음 단계.
- 통신(WebSocket으로 dashboard에 실시간 전송)은 아직 미구현이다. 지금은 최종 JSON을 터미널에
  출력하고 `*_call_summary.json` 파일로도 저장해두는 것까지만 한다 — 통신 계층을 붙일 때
  이 JSON을 그대로 보내면 된다.
- Ollama가 설치되지 않은 환경(이 저장소를 만든 개발 환경 포함)에서는 `summarizer.py`의 실제
  LLM 호출을 라이브로 검증하지 못했다. 필터링~JSON 조립까지는 mock으로 dry-run 검증 완료.

## 입출력 데이터 포맷

**입력**
오디오 파일 (.wav 등) — 추후 실시간 스트림 입력으로 전환 예정

**출력** (`transcribe.py --summarize` 실행 시 터미널에 출력 + `*_call_summary.json` 저장.
feature/dashboard의 `CallSummaryMessage` 타입과 1:1로 대응하며, `turns`/`required_department`는
dashboard 쪽에서 원본 로그 화면 표시용으로 확장한 필드다 — `src/types/dashboard.ts` 참고)
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
|---|---|---|
| `transcript.raw_text` | string | STT 원본 전문. 필터링 전 전체 발화, 삭제하지 않고 보존 |
| `transcript.filtered_text` | string | 실시간 음성 필터링 처리 후 남은 텍스트. 요약의 실제 입력값 |
| `transcript.language` | string | 언어 코드 |
| `transcript.timestamp` | string (ISO 8601) | 통화 시작 시각 (사전 녹음 파일 처리 특성상 현재는 근사값) |
| `transcript.duration_sec` | number | 통화 길이(초) |
| `transcript.turns` | array | 발화 턴별 원본 로그. `speaker`/`timestamp`/`text`/`excludedFromSummary?` |
| `summary.patient` | string | 환자 인적사항 요약 |
| `summary.mechanism` | string | 사고 기전 |
| `summary.symptoms` | string[] | 증상 목록 |
| `summary.treatment` | string[] | 처치 목록 |
| `summary.severity_tag` | `"high"` \| `"medium"` \| `"low"` | 중증도 단계 |
| `summary.required_department` | string \| null | 필요 진료과 추정 (판단 근거 부족 시 생략) |
| `source` | `"ai"` | AI 처리 결과임을 나타내는 고정값 |
| `model_used.stt` / `model_used.llm` | string | 실제 사용된 모델명 |

바이탈 필드는 포함하지 않는다 (feature/vital 브랜치에서 별도 정의, 아직 미정).

**통신(전송) 상태**: feature/dashboard로의 WebSocket 실시간 전송은 아직 연동 전이다. 지금은 위
JSON을 터미널 표준 출력과 `*_call_summary.json` 파일로만 내보낸다 — 통신 계층은 이 JSON을
그대로 보내기만 하면 되도록 분리해뒀다.

## 실행 방법

```bash
conda create -n rookie python=3.11
conda activate rookie
pip install -r requirements.txt
```

`requirements.txt`는 직접 설치 대상(용도별 설명 포함)과 하위 의존성까지 모두 버전이
고정되어 있어, 위 명령 한 번으로 다른 팀원도 동일한 버전 조합을 그대로 재현할 수 있다.

**1. 유튜브 오디오 다운로드 (선택)**
```bash
python youtube_downloader.py
```
GUI 창에서 URL을 입력하고 다운로드하면 `data/` 폴더에 오디오 파일이 저장됩니다.

**2. 음성 → 텍스트 변환 + 실시간 음성 필터링 + SBAR 구조화(JSON)**
```bash
python transcribe.py data/파일명.wav --summarize
```
`--summarize`를 빼면 STT(텍스트 변환)까지만 하고 끝납니다. `--summarize`를 주면 발화 턴 분류 →
필터링 → LLM 구조화를 거쳐 최종 JSON을 터미널에 출력하고 `data/파일명_call_summary.json`으로도
저장합니다.

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--model` | `large-v3` | Whisper 모델 크기 (`tiny`, `base`, `small`, `medium`, `large-v3` 등) |
| `--language` | `ko` | 언어 코드 |
| `--device` | `auto` | 연산 장치 (`auto` / `cuda` / `cpu`) |
| `--compute-type` | `auto` | 연산 정밀도 (`float16`, `int8`, `float32` 등) |
| `--summarize` | (off) | 실시간 음성 필터링 + SBAR 구조화를 수행해 JSON 생성 |
| `--llm-model` | `qwen3:14b` | 구조화에 사용할 Ollama 모델 이름 |

`--summarize`를 쓰려면 먼저 Ollama 서버가 떠 있어야 합니다 (필터링 단계 자체는 Ollama 없이도
동작하지만, 이어지는 SBAR 구조화 단계에서 필요).
```bash
ollama serve
ollama pull qwen3:14b   # 처음 한 번만
```
분류기(`filtering.py`)가 처음 실행될 때는 `paraphrase-multilingual-MiniLM-L12-v2` 모델을
Hugging Face에서 자동 다운로드한다 (약 470MB, 최초 1회).

## 폴더 구조
```
voice/
├── .gitignore
├── README.md
├── requirements.txt
├── filtering.py
├── schema.py
├── summarizer.py
├── transcribe.py
└── youtube_downloader.py
```

## 알려진 제약사항 / TODO

- macOS(Apple Silicon 포함)에서는 CTranslate2가 Metal/MPS GPU 가속을 지원하지 않아 항상 CPU로 동작. `large-v3`는 느릴 수 있으니 `base`나 `small` 권장
- GPU 사용 시 NVIDIA CUDA 12.x 및 cuDNN 9 필요
- `data/` 폴더는 `.gitignore`에 포함되어 있어 오디오 원본과 변환 결과물은 저장소에 올라가지 않음
- 유튜브 콘텐츠 다운로드 시 저작권 및 유튜브 서비스 약관 준수 책임은 사용자에게 있음. 본인 소유이거나 다운로드가 허용된 콘텐츠에만 사용
- 실시간 음성 필터링/구조화 관련 제약사항은 위 "실시간 음성 필터링" 섹션의 "알려진 한계" 참고

## 추가사항