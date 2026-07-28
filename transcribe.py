import argparse
import sys
import time
import urllib.error
import urllib.request
import json
from pathlib import Path

from faster_whisper import WhisperModel

OLLAMA_URL = "http://localhost:11434/api/generate"
SUMMARIZE_PROMPT = (
    "다음은 음성 파일을 텍스트로 변환한 내용이다. 핵심 내용을 한국어로 간결하게 요약해줘.\n\n"
    "---\n{text}\n---"
)


def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def is_ollama_running() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434", timeout=2)
        return True
    except urllib.error.URLError:
        return False


def summarize(text: str, llm_model: str) -> str:
    payload = json.dumps(
        {
            "model": llm_model,
            "prompt": SUMMARIZE_PROMPT.format(text=text),
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result["response"].strip()


def transcribe(
    audio_path: Path,
    model_size: str,
    language: str,
    device: str,
    compute_type: str,
    do_summarize: bool,
    llm_model: str,
) -> None:
    print(f"모델 로딩 중... ({model_size}, device={device}, compute_type={compute_type})")
    load_start = time.perf_counter()
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    load_elapsed = time.perf_counter() - load_start
    print(f"모델 로딩 완료 ({load_elapsed:.2f}초)")

    print(f"변환 중: {audio_path.name}")
    transcribe_start = time.perf_counter()
    segments, info = model.transcribe(str(audio_path), language=language, vad_filter=True)

    lines = []
    for segment in segments:
        ts = f"[{format_timestamp(segment.start)} -> {format_timestamp(segment.end)}]"
        print(f"{ts} {segment.text.strip()}")
        lines.append(segment.text.strip())
    transcribe_elapsed = time.perf_counter() - transcribe_start

    full_text = " ".join(lines)
    out_path = audio_path.with_suffix(".txt")
    out_path.write_text(full_text, encoding="utf-8")
    print(f"\n텍스트 파일 저장: {out_path}")
    print(f"변환 소요 시간: {transcribe_elapsed:.2f}초 (모델 로딩 제외)")

    if not do_summarize:
        return

    if not is_ollama_running():
        print(
            "\nOllama 서버가 실행 중이 아닙니다. 'ollama serve'를 먼저 실행한 뒤 다시 시도하세요.",
            file=sys.stderr,
        )
        return

    print(f"\n요약 생성 중... ({llm_model})")
    summarize_start = time.perf_counter()
    try:
        summary = summarize(full_text, llm_model)
    except (urllib.error.URLError, KeyError) as e:
        print(f"요약 생성 실패: {e}", file=sys.stderr)
        return
    summarize_elapsed = time.perf_counter() - summarize_start

    summary_path = audio_path.with_name(audio_path.stem + "_summary.txt")
    summary_path.write_text(summary, encoding="utf-8")
    print(summary)
    print(f"\n요약 파일 저장: {summary_path}")
    print(f"요약 소요 시간: {summarize_elapsed:.2f}초")


def main() -> None:
    parser = argparse.ArgumentParser(description="로컬 음성 파일을 텍스트로 변환하고, 선택적으로 요약합니다.")
    parser.add_argument("audio", type=Path, help="변환할 오디오 파일 경로")
    parser.add_argument("--model", default="large-v3", help="Whisper 모델 크기 (기본: large-v3)")
    parser.add_argument("--language", default="ko", help="언어 코드 (기본: ko)")
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cuda", "cpu"],
        help="연산 장치 (기본: auto - GPU가 있으면 자동으로 사용, 없으면 CPU. Mac에서는 항상 cpu로 동작)",
    )
    parser.add_argument(
        "--compute-type",
        default="auto",
        help="연산 정밀도 (기본: auto - 장치에 맞는 값을 자동 선택. 예: float16, int8, float32)",
    )
    parser.add_argument("--summarize", action="store_true", help="변환된 텍스트를 로컬 LLM(Ollama)으로 요약")
    parser.add_argument("--llm-model", default="qwen3:14b", help="요약에 사용할 Ollama 모델 (기본: qwen3:14b)")
    args = parser.parse_args()

    if not args.audio.exists():
        print(f"파일을 찾을 수 없습니다: {args.audio}", file=sys.stderr)
        sys.exit(1)

    transcribe(
        args.audio,
        args.model,
        args.language,
        args.device,
        args.compute_type,
        args.summarize,
        args.llm_model,
    )


if __name__ == "__main__":
    main()
