# voiceSummation

유튜브 오디오 다운로드 → 음성 파일을 텍스트로 변환 → 로컬 LLM으로 요약까지 이어지는 파이프라인입니다.

- **`youtube_downloader.py`** — 유튜브 URL을 입력하면 오디오만 추출해 `data/` 폴더에 저장하는 간단한 GUI 도구 (tkinter)
- **`transcribe.py`** — 로컬 오디오 파일을 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)로 텍스트 변환하고, 옵션으로 [Ollama](https://ollama.com)에 붙어 있는 로컬 LLM으로 요약까지 수행하는 CLI 도구

## 사용 모델

| 용도 | 모델 | Hugging Face |
|---|---|---|
| 음성 → 텍스트 변환 (STT) | Whisper large-v3 (CTranslate2 변환판, faster-whisper 기본값) | [Systran/faster-whisper-large-v3](https://huggingface.co/Systran/faster-whisper-large-v3) |
| 텍스트 요약 (LLM, Ollama `qwen3:14b`) | Qwen3-14B | [Qwen/Qwen3-14B](https://huggingface.co/Qwen/Qwen3-14B) |

`--model`, `--llm-model` 옵션으로 다른 크기/모델로 바꿀 수 있습니다.

## 요구사항

- Python 3.10 이상
- (요약 기능을 쓰려면) [Ollama](https://ollama.com) 설치 및 원하는 모델 pull
- (선택) NVIDIA GPU + CUDA 12.x — 없으면 자동으로 CPU로 동작합니다

## 설치

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## 사용법

### 1. 유튜브 오디오 다운로드 (선택)

```bash
python youtube_downloader.py
```

GUI 창에서 URL을 입력하고 다운로드하면 `data/` 폴더에 오디오 파일이 저장됩니다.

### 2. 음성 → 텍스트 변환 + 요약

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

실행 결과로 원본 오디오와 같은 위치에 `파일명.txt`(변환된 텍스트)와 `파일명_summary.txt`(요약, `--summarize` 사용 시)가 생성됩니다.

## GPU / CPU / Mac 참고사항

- `--device auto`(기본값)는 CUDA GPU가 있으면 자동으로 사용하고, 없으면 CPU로 동작합니다.
- macOS(Apple Silicon 포함)에서는 faster-whisper의 백엔드인 CTranslate2가 Metal/MPS GPU 가속을 지원하지 않아 항상 CPU로 동작합니다. `large-v3`는 느릴 수 있으니 `base`나 `small` 같은 작은 모델을 권장합니다.
- GPU를 사용하려면 NVIDIA CUDA 12.x 및 cuDNN 9가 설치되어 있어야 합니다.

## 주의사항

- `data/` 폴더는 `.gitignore`에 포함되어 있어 오디오 원본과 변환 결과물은 저장소에 올라가지 않습니다.
- 유튜브 콘텐츠 다운로드 시 저작권 및 유튜브 서비스 약관을 준수할 책임은 사용자에게 있습니다. 본인 소유이거나 다운로드가 허용된 콘텐츠에만 사용하세요.
