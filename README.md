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
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
pip install -r requirements.txt
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
├── transcribe.py
└── youtube_downloader.py
```

## 알려진 제약사항 / TODO

- macOS(Apple Silicon 포함)에서는 CTranslate2가 Metal/MPS GPU 가속을 지원하지 않아 항상 CPU로 동작. `large-v3`는 느릴 수 있으니 `base`나 `small` 권장
- GPU 사용 시 NVIDIA CUDA 12.x 및 cuDNN 9 필요
- `data/` 폴더는 `.gitignore`에 포함되어 있어 오디오 원본과 변환 결과물은 저장소에 올라가지 않음
- 유튜브 콘텐츠 다운로드 시 저작권 및 유튜브 서비스 약관 준수 책임은 사용자에게 있음. 본인 소유이거나 다운로드가 허용된 콘텐츠에만 사용

## 추가사항