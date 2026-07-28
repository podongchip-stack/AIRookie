# feature/voice — 유튜브/음성 파일 STT 변환 및 로컬 LLM 요약 파이프라인

## 담당자

- 이름: 이승주
- 역할: 리드 개발자
<!-- -->
- 이름: 곽호영
- 역할: 리드 개발자

## 이 브랜치가 하는 일

유튜브 오디오 다운로드 → 음성 파일을 텍스트로 변환 → 로컬 LLM으로 요약까지 이어지는 파이프라인입니다.

- **`youtube_downloader.py`** — 유튜브 URL을 입력하면 오디오만 추출해 `data/` 폴더에 저장하는 간단한 GUI 도구 (tkinter)
- **`transcribe.py`** — 로컬 오디오 파일을 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)로 텍스트 변환하고, 옵션으로 [Ollama](https://ollama.com)에 붙어 있는 로컬 LLM으로 요약까지 수행하는 CLI 도구

> 현재 `transcribe.py`는 STT 처리 속도 검증을 위한 프로토타입이며, 아래 확정된 JSON 출력 포맷에 맞춘 구현은 추가 작업 예정이다.

## 사용한 AI / 모델

| 구분 | 모델명 | 용도 | 비고 |
|---|---|---|---|
| STT | Whisper large-v3 (CTranslate2 변환판, faster-whisper 기본값) — [Systran/faster-whisper-large-v3](https://huggingface.co/Systran/faster-whisper-large-v3) | 음성 → 텍스트 변환 | `--model` 옵션으로 크기 변경 가능 |
| 정보 구조화 | Qwen3-14B (Ollama `qwen3:14b`) — [Qwen/Qwen3-14B](https://huggingface.co/Qwen/Qwen3-14B) | 텍스트 요약 | `--llm-model` 옵션으로 변경 가능 |

> CLAUDE.md의 "핵심 AI 활용 원칙" 표 기준으로, 이 기능이 AI 처리 영역인지 규칙 기반 영역인지 명시:
> - [x] AI 처리
> - [ ] 규칙 기반

## 개발 환경 / 언어

- 언어: Python 3.11 (`requirements.txt` 상단 주석 참고)
- 주요 라이브러리·프레임워크: faster-whisper, Ollama, tkinter, torch/transformers(문장 분류·SBAR 구조화용), pydantic
- 실행 환경: 로컬 (GPU 있으면 CUDA 12.x 가속, 없으면 CPU. macOS는 CTranslate2가 Metal/MPS 미지원으로 항상 CPU 동작)

## 입출력 데이터 포맷

**입력**
오디오 파일 (.wav 등) — 추후 실시간 스트림 입력으로 전환 예정

**출력**
```json
{
  "transcript": {
    "raw_text": "구급대원: 환자 50대 남성, 교통사고 흉부 충격입니다... A병원: 네 잠시만요...",
    "filtered_text": "환자 50대 남성, 교통사고 흉부 충격. 의식 저하, 호흡 곤란.",
    "language": "ko",
    "timestamp": "2026-07-28T14:32:31Z",
    "duration_sec": 42.3
  },
  "summary": {
    "patient": "50대 남성",
    "mechanism": "교통사고 · 흉부 충격",
    "symptoms": ["의식 저하", "호흡 곤란"],
    "treatment": ["산소 공급", "지혈 완료"],
    "severity_tag": "high"
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
| `transcript.timestamp` | string (ISO 8601) | 통화 시작 시각 |
| `transcript.duration_sec` | number | 통화 길이(초) |
| `summary.patient` | string | 환자 인적사항 요약 |
| `summary.mechanism` | string | 사고 기전 |
| `summary.symptoms` | string[] | 증상 목록 |
| `summary.treatment` | string[] | 처치 목록 |
| `summary.severity_tag` | `"high"` \| `"medium"` \| `"low"` | 중증도 단계 |
| `source` | `"ai"` | AI 처리 결과임을 나타내는 고정값 |
| `model_used.stt` / `model_used.llm` | string | 실제 사용된 모델명 |

바이탈 필드는 포함하지 않는다 (feature/vital 브랜치에서 별도 정의, 아직 미정).

## 실행 방법

```bash
conda create -n rookie python=3.11
conda activate rookie
pip install -r requirements.txt
```

`requirements.txt`는 용도별 설명이 달린 직접 의존성 목록이다. 정확히 같은 버전 조합으로
재현하려면 하위 의존성까지 고정된 `requirements-lock.txt`를 대신 설치한다.

```bash
pip install -r requirements-lock.txt
```

**1. 유튜브 오디오 다운로드 (선택)**
```bash
python youtube_downloader.py
```
GUI 창에서 URL을 입력하고 다운로드하면 `data/` 폴더에 오디오 파일이 저장됩니다.

**2. 음성 → 텍스트 변환 + 요약**
```bash
python transcribe.py data/파일명.wav --summarize
```
요약 없이 텍스트 변환만 하려면 `--summarize` 옵션을 빼면 됩니다.

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--model` | `large-v3` | Whisper 모델 크기 (`tiny`, `base`, `small`, `medium`, `large-v3` 등) |
| `--language` | `ko` | 언어 코드 |
| `--device` | `auto` | 연산 장치 (`auto` / `cuda` / `cpu`) |
| `--compute-type` | `auto` | 연산 정밀도 (`float16`, `int8`, `float32` 등) |
| `--summarize` | (off) | 변환된 텍스트를 로컬 LLM으로 요약 |
| `--llm-model` | `qwen3:14b` | 요약에 사용할 Ollama 모델 이름 |

요약 기능을 쓰려면 먼저 Ollama 서버가 떠 있어야 합니다.
```bash
ollama serve
ollama pull qwen3:14b   # 처음 한 번만
```

## 폴더 구조
```
voice/
├── .gitignore
├── README.md
├── requirements.txt
├── requirements-lock.txt
├── transcribe.py
└── youtube_downloader.py
```

## 알려진 제약사항 / TODO

- macOS(Apple Silicon 포함)에서는 CTranslate2가 Metal/MPS GPU 가속을 지원하지 않아 항상 CPU로 동작. `large-v3`는 느릴 수 있으니 `base`나 `small` 권장
- GPU 사용 시 NVIDIA CUDA 12.x 및 cuDNN 9 필요
- `data/` 폴더는 `.gitignore`에 포함되어 있어 오디오 원본과 변환 결과물은 저장소에 올라가지 않음
- 유튜브 콘텐츠 다운로드 시 저작권 및 유튜브 서비스 약관 준수 책임은 사용자에게 있음. 본인 소유이거나 다운로드가 허용된 콘텐츠에만 사용

## 추가사항