"""voice/MF_BERT/labels.py -> GoldenLinkCore 리소스 labels.json.

Swift에 보기 목록을 손으로 옮기면 한 글자만 틀려도 결과가 달라진다. 원본에서 그대로 뽑아 쓴다.
labels.py가 바뀌면(모델 재학습) 이 스크립트를 다시 돌린다.

    python dashboard/iphone/convert/export_labels.py      # 저장소 루트에서
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "voice"))

from MF_BERT import labels as L  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "GoldenLinkCore/Sources/GoldenLinkCore/Resources/labels.json"


def main() -> None:
    data = {
        "undecided": L.UNDECIDED,
        "majors": list(L.MAJORS),
        "minors": list(L.MINORS),
        "single": {h.name: list(h.classes) for h in L.SINGLE_CHOICE_HEADS},
        "multi": {name: list(options) for name, options in L.MULTI_LABEL_HEADS.items()},
        "span_types": list(L.SPAN_TYPES),
        "span_tags": list(L.SPAN_TAGS),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {OUT}")


if __name__ == "__main__":
    main()
