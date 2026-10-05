"""Core ML MF_BERT가 PyTorch 원본과 같은 summary를 내는지 대조한다(P0 통과 기준: 17필드 완전 일치).

    python dashboard/iphone/convert/check_mf_bert.py                    # 기본 문장들
    python dashboard/iphone/convert/check_mf_bert.py voice/data/**/*.txt   # 실제 통화 텍스트(voice 담당자 보유 검증 통화 포함)

기록: 헤드별 로짓 최대 절대오차. 통과 조건: decode() 결과 JSON 완전 일치.
Core ML은 CPU_AND_GPU로 돌린다(Neural Engine은 fp32를 못 돌려 fp16으로 떨어진다 — 아이폰 앱도 같은 설정).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import coremltools as ct
import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "voice"))

from mf_bert_split import Heads, run_split  # noqa: E402
from MF_BERT import MfBertExtractor  # noqa: E402
from MF_BERT.chunking import chunk_text  # noqa: E402
from MF_BERT.decode import decode  # noqa: E402

MODELS = HERE.parent / "Models"
DEFAULT_TEXTS = [
    "구급대원입니다. 62세 남성 30분 전부터 흉통 호소, 혈압 150에 90 맥박 110 산소포화도 96%, ECG 시행했습니다.",
    "교통사고 운전자 50대 여성, 의식 V, 좌측 다리 골절 의심 부목 고정했고 혈압 백에 육십입니다.",
    "생후 8개월 여아 열 39도 8부, 경련 5분, 산소 투여 중입니다.",
]


class CoreMLEncoder:
    def __init__(self) -> None:
        self.m = ct.models.MLModel(str(MODELS / "MFBertEncoder.mlpackage"), compute_units=ct.ComputeUnit.CPU_AND_GPU)

    def __call__(self, input_ids: torch.Tensor) -> torch.Tensor:
        return torch.from_numpy(self.m.predict({"input_ids": input_ids.numpy().astype(np.int32)})["hidden"])


class CoreMLHeads:
    def __init__(self, names: list[str]) -> None:
        self.m = ct.models.MLModel(str(MODELS / "MFBertHeads.mlpackage"), compute_units=ct.ComputeUnit.CPU_AND_GPU)
        self.names = names

    def __call__(self, hidden: torch.Tensor) -> tuple[torch.Tensor, ...]:
        out = self.m.predict({"hidden": hidden.numpy().astype(np.float32)})
        return tuple(torch.from_numpy(out[n]) for n in self.names)


def main() -> None:
    texts = [Path(p).read_text(encoding="utf-8") for p in sys.argv[1:]] or DEFAULT_TEXTS
    ext = MfBertExtractor(device="cpu")
    model, tok = ext.model.eval(), ext.tokenizer
    enc, heads = CoreMLEncoder(), CoreMLHeads(Heads(model).head_names())
    failed = 0
    for i, text in enumerate(texts):
        offsets = chunk_text(text, tok)["offsets"]
        reference, _ = ext.extract(text)  # 서버와 똑같은 경로(PyTorch, 패딩 배치)
        coreml = run_split(model, tok, text, encoder=enc, heads=heads)
        pytorch = run_split(model, tok, text)
        worst = max((coreml[k] - pytorch[k]).abs().max().item() for k in coreml)
        got = decode(text, coreml, offsets)
        same = json.dumps(got, ensure_ascii=False, sort_keys=True) == json.dumps(reference, ensure_ascii=False, sort_keys=True)
        failed += not same
        print(f"[{i}] 토큰 {len(offsets)}개 · 로짓 최대 오차 {worst:.2e} · summary {'일치' if same else '불일치 ✗'}")
        if not same:
            print("  PyTorch:", json.dumps(reference, ensure_ascii=False))
            print("  CoreML :", json.dumps(got, ensure_ascii=False))
    print(f"\n{len(texts) - failed}/{len(texts)} 일치")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
