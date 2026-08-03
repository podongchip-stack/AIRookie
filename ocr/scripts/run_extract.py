"""서류에서 병원 정보 필드를 뽑아 `ocr/output/`에 JSON으로 쓴다.

실행:
    # 이미지부터 (OCR + LLM 동시 상주) — GPU 필요
    python scripts/run_extract.py --image 당직표.png 진료과안내.png

    # 저장해둔 OCR 결과에서 (GPU 불필요)
    python scripts/run_extract.py --ocr-json 당직표.json

    # LLM 없이 로직만 (Ollama·GPU 불필요)
    python scripts/run_extract.py --ocr-json 당직표.json --llm stub

    # 환각 필터가 실제로 거르는지 확인
    python scripts/run_extract.py --ocr-json 당직표.json --llm stub-hallucinate

    # 복사해 온 어휘가 원본과 어긋났는지 확인
    python scripts/run_extract.py --check-vocabulary

결과는 `ocr/output/`에 `YYYYMMDD_HHMMSS_<문서명>.json`으로 쌓인다. 덮어쓰지 않고
계속 새로 생긴다 — 프롬프트나 모델을 바꿔가며 돌렸을 때 이전 결과와 비교할 수
있어야 하고, 의료 정보 추출 이력은 지우지 않는 편이 맞다.

동시 상주 모드
--------------
`--image`로 돌리면 OCR 모델(약 2.1GB)과 LLM(qwen3:14b Q4 약 10.5GB)이 VRAM에
동시에 올라간 채로 문서를 연달아 처리한다. RTX 5080(16GB) 기준 약 12.6GB 점유다.
문서마다 모델을 내렸다 올리는 비용이 없는 대신 여유가 3GB 남짓으로 줄어든다.

여유가 부족하면(다른 프로그램이 VRAM을 쓰거나 서류가 아주 클 때) 코드 수정 없이
환경변수만으로 순차 모드로 바꿀 수 있다.

    GOLDENLINK_LLM_KEEP_ALIVE=0     호출이 끝나면 LLM을 내린다
    GOLDENLINK_LLM_MODEL=qwen3:8b   더 작은 모델로

시작할 때 VRAM 점유를 출력하므로 실제 여유를 보고 판단하면 된다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from goldenlink_extract import ExtractConfig, FieldExtractor  # noqa: E402
from goldenlink_extract.config import KST  # noqa: E402
from goldenlink_extract.llm import LlmError, OllamaClient, StubLlmClient  # noqa: E402
from goldenlink_extract.vocabulary import UPSTREAM_SCHEMA, diff_with_upstream  # noqa: E402

OUTPUT_DIR = PROJECT_ROOT / "output"

#: 파일명에 쓸 수 없는 문자. 서류 이름에 괄호나 공백이 섞여 있는 경우가 많다
_UNSAFE_FILENAME = re.compile(r"[^\w가-힣.-]+")


def _safe_stem(name: str) -> str:
    return _UNSAFE_FILENAME.sub("_", name).strip("_") or "document"


def _output_path(out_dir: Path, document_id: str, stamp: datetime) -> Path:
    """`YYYYMMDD_HHMMSS_<문서명>.json` 경로를 만든다.

    날짜시간을 앞에 두면 파일 목록이 저절로 시간순으로 정렬된다. 문서명을 뒤에
    붙이는 이유는 한 번에 여러 장을 돌렸을 때 이름만 보고 무엇인지 알기 위해서다.
    같은 초에 같은 문서를 두 번 처리하면 뒤에 번호를 붙여 **기존 파일을 덮지 않는다.**
    """
    base = f"{stamp.strftime('%Y%m%d_%H%M%S')}_{_safe_stem(document_id)}"
    path = out_dir / f"{base}.json"
    serial = 2
    while path.exists():
        path = out_dir / f"{base}_{serial}.json"
        serial += 1
    return path


def _report_vram(client) -> None:
    """지금 VRAM을 무엇이 얼마나 쓰고 있는지 출력한다.

    동시 상주가 실제로 되고 있는지, 여유가 얼마나 남았는지 눈으로 확인하는
    용도다. 숫자를 보고 순차 모드로 바꿀지 판단하면 된다.
    """
    lines = []

    for model in getattr(client, "loaded_models", list)():
        vram = model.get("size_vram", 0) / 1024**3
        lines.append(f"  LLM  {model.get('name', '?'):<28} {vram:5.1f} GB")

    try:  # torch는 OCR을 쓸 때만 설치돼 있다. 없으면 이 부분만 건너뛴다
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            lines.append(
                f"  GPU  {torch.cuda.get_device_name(0):<28} "
                f"{(total - free) / 1024**3:5.1f} / {total / 1024**3:.1f} GB 사용 "
                f"(여유 {free / 1024**3:.1f} GB)"
            )
    except ImportError:
        pass

    if lines:
        print("[VRAM]")
        print("\n".join(lines), flush=True)


def _check_vocabulary() -> int:
    """복사해 온 어휘가 원본과 어긋났는지 확인한다."""
    problems = diff_with_upstream(REPO_ROOT / UPSTREAM_SCHEMA)
    if not problems:
        print(f"어휘가 원본({UPSTREAM_SCHEMA})과 일치한다.")
        return 0
    print(f"어휘가 원본({UPSTREAM_SCHEMA})과 어긋났다:", file=sys.stderr)
    for problem in problems:
        print(f"  · {problem}", file=sys.stderr)
    return 1


def _load_ocr_results(args: argparse.Namespace) -> list[tuple[str, dict]]:
    """(문서 식별자, OCR 결과) 목록을 만든다.

    `--ocr-json`은 GPU 없이 돌고 `--image`는 OCR부터 직접 한다. 어느 쪽이든
    추출기가 받는 형태는 같다 — 추출기는 이미지가 있었는지도 모른다.
    """
    if args.ocr_json:
        return [
            (Path(path).stem, json.loads(Path(path).read_text(encoding="utf-8")))
            for path in args.ocr_json
        ]

    # 이미지 모드: OCR 모델을 올린다. 여기서만 torch가 필요하다
    try:
        from goldenlink_ocr import DocumentOCR
    except ImportError as error:
        raise SystemExit(
            f"OCR 모듈을 불러오지 못했다: {error}\n"
            f"  ocr/requirements.txt 의존성이 설치된 환경에서 실행해야 한다.\n"
            f"  GPU가 없는 장비라면 --ocr-json 으로 저장된 OCR 결과를 넣어라."
        ) from None

    print(f"[1/3] OCR 모델 로드 중… (문서 {len(args.image)}장)", flush=True)
    ocr = DocumentOCR()

    results = []
    for path in args.image:
        print(f"      OCR: {Path(path).name}", flush=True)
        results.append((Path(path).stem, ocr.read(path)))
    return results


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="서류 OCR 텍스트에서 병원 정보 필드를 뽑아 JSON으로 쓴다",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--image", nargs="+", help="서류 이미지 경로 (OCR부터, GPU 필요)")
    source.add_argument("--ocr-json", nargs="+", help="저장된 OCR 결과 JSON 경로")
    parser.add_argument(
        "--check-vocabulary", action="store_true",
        help="복사해 온 어휘가 원본과 일치하는지 확인하고 끝낸다",
    )
    parser.add_argument(
        "--llm", default="ollama", choices=["ollama", "stub", "stub-hallucinate"],
        help="추출에 쓸 구현 (기본: ollama)",
    )
    parser.add_argument("--model", help="모델 태그. 기본값은 config.py 참고 (예: qwen3:8b)")
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR, help="출력 폴더")
    parser.add_argument(
        "--keep-ungrounded", action="store_true",
        help="근거 없는 값도 결과에 남긴다 (기본은 버린다). 프롬프트 디버깅용",
    )
    args = parser.parse_args()

    if args.check_vocabulary:
        return _check_vocabulary()
    if not args.image and not args.ocr_json:
        parser.error("--image 또는 --ocr-json 중 하나는 있어야 한다")

    config = ExtractConfig.from_env()
    if args.model:
        config = config.with_llm(config.llm.with_model(args.model))
    if args.keep_ungrounded:
        config = ExtractConfig(
            llm=config.llm, drop_ungrounded=False, min_evidence_chars=config.min_evidence_chars
        )

    use_ollama = args.llm == "ollama"
    client = (
        OllamaClient(config.llm) if use_ollama
        else StubLlmClient(hallucinate=args.llm == "stub-hallucinate")
    )

    # OCR을 먼저 돌린다. 동시 상주 모드에서는 이 시점에 OCR 모델이 VRAM에 올라가고,
    # 바로 아래에서 LLM이 그 위에 얹힌다
    try:
        ocr_results = _load_ocr_results(args)
    except (OSError, json.JSONDecodeError) as error:
        print(f"입력을 읽지 못했다: {error}", file=sys.stderr)
        return 1

    if use_ollama:
        print(f"[2/3] LLM 로드 중… ({config.llm.model}, "
              f"keep_alive={config.llm.keep_alive})", flush=True)
        try:
            client.preload()
        except LlmError as error:
            print(f"LLM을 준비하지 못했다:\n{error}", file=sys.stderr)
            return 1

    _report_vram(client)

    print(f"[3/3] 필드 추출 — 문서 {len(ocr_results)}건", flush=True)
    extractor = FieldExtractor(client, config)
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(KST)

    flagged = 0
    for document_id, ocr_result in ocr_results:
        fields = extractor.extract(ocr_result, document_id)
        path = _output_path(args.out, document_id, stamp)
        path.write_text(fields.to_json() + "\n", encoding="utf-8")

        grounded = sum(1 for e in fields.evidence if e.grounded)
        print(
            f"  {document_id} — {fields.hospitalName or '기관명 미상'}"
            f" / 필드 {fields.filled_fields()}"
            f" / 근거 {grounded}/{len(fields.evidence)} 통과"
            f" / {'검토필요' if fields.needsReview else '정상'}"
            f" -> {path.name}",
            flush=True,
        )
        if fields.needsReview:
            flagged += 1
            for reason in fields.reviewReasons:
                print(f"      · {reason}", flush=True)

    print(f"\n{len(ocr_results)}개 파일을 {args.out}에 썼다. (검토 필요 {flagged}건)")
    return 0 if ocr_results else 1


if __name__ == "__main__":
    raise SystemExit(main())
