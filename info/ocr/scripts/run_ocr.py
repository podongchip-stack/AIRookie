"""문서 1장 이상을 OCR 해서 결과를 출력한다.

실행:
    python scripts/run_ocr.py <이미지경로> [...]
    python scripts/run_ocr.py <이미지경로> --json   # 구조화 결과 전체
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldenlink_ocr import DocumentOCR


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv

    if not args:
        print(__doc__, flush=True)
        sys.exit(1)

    ocr = DocumentOCR()
    print(f"레이아웃 providers: {ocr.detector.providers} / "
          f"attn: {ocr.recognizer.attn_implementation}\n", flush=True)

    for path in args:
        t0 = time.perf_counter()
        result = ocr.read(path)
        elapsed = time.perf_counter() - t0

        if as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            continue

        flagged = [r for r in result["regions"] if r["needs_review"]]
        print(f"=== {Path(path).name} — 영역 {len(result['regions'])}개, "
              f"{elapsed:.1f}초, {len(result['text'])}자", flush=True)
        if flagged:
            print(f"검토 필요 {len(flagged)}건:", flush=True)
            for r in flagged:
                print(f"  [{r['cls']}] {', '.join(r['review_reasons'])}", flush=True)
        print(result["text"], flush=True)
        print(flush=True)


if __name__ == "__main__":
    main()
