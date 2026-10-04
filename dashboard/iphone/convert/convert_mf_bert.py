"""MF_BERT(best.pt) -> Core ML 두 모델(fp32). 정밀도를 바꾸지 않는다 — compute_precision=FLOAT32(기본값 fp16이면 성능이 바뀐다).

    conda activate goldenlink-ios     # README "1. 맥 Python 환경" 참고 (voice 환경 + coremltools)
    python dashboard/iphone/convert/convert_mf_bert.py
    python dashboard/iphone/convert/check_mf_bert.py      # 반드시 대조까지

출력: dashboard/iphone/Models/  (git에 올리지 않는다 — .gitignore)
    MFBertEncoder.mlpackage   input_ids (1, L) int32, L 2~512   -> hidden (N, L, 1024)
    MFBertHeads.mlpackage     hidden (N, T, 1024) float32, T 2~16384 -> 헤드 이름별 로짓 + spans (1, T, 11)
    tokenizer.json            MF_BERT tokenizer/ 그대로 (Swift WordPieceTokenizer가 읽는다)
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import coremltools as ct
import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "voice"))

from mf_bert_split import Encoder, Heads  # noqa: E402
from MF_BERT import MfBertExtractor  # noqa: E402
from weights import resolve_mf_bert_dir  # noqa: E402

OUT = HERE.parent / "Models"
MAX_TOKENS = 16384  # 복원한 토큰 줄 최대 길이(통화 10분 이상 여유)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    run_dir = resolve_mf_bert_dir()
    ext = MfBertExtractor(device="cpu", run_dir=run_dir)  # fp32
    model = ext.model.eval()
    model.encoder.set_attn_implementation("eager")  # sdpa 마스크 생성은 추적이 깨지기 쉽다(결과는 같다)
    n, hidden = model.layer_count, model.encoder.config.hidden_size

    encoder = Encoder(model).eval()
    traced = torch.jit.trace(encoder, (torch.ones(1, 512, dtype=torch.long) * 5,))
    enc = ct.convert(
        traced,
        inputs=[ct.TensorType("input_ids", shape=(1, ct.RangeDim(2, 512, default=512)), dtype=np.int32)],
        outputs=[ct.TensorType("hidden", dtype=np.float32)],
        compute_precision=ct.precision.FLOAT32,
        minimum_deployment_target=ct.target.iOS18,
    )
    enc.short_description = f"MF_BERT 인코더(KLUE RoBERTa-large) — 마지막 {n}층 은닉 상태, fp32"
    enc.save(str(OUT / "MFBertEncoder.mlpackage"))
    print("저장: MFBertEncoder.mlpackage")

    heads = Heads(model).eval()
    names = heads.head_names()
    traced = torch.jit.trace(heads, (torch.randn(n, 64, hidden),))
    hd = ct.convert(
        traced,
        inputs=[ct.TensorType("hidden", shape=(n, ct.RangeDim(2, MAX_TOKENS, default=64), hidden), dtype=np.float32)],
        outputs=[ct.TensorType(name, dtype=np.float32) for name in names],
        compute_precision=ct.precision.FLOAT32,
        minimum_deployment_target=ct.target.iOS18,
    )
    hd.short_description = "MF_BERT 헤드 — 문장 헤드 로짓(이름별) + 구간 태거 spans, fp32"
    hd.save(str(OUT / "MFBertHeads.mlpackage"))
    print(f"저장: MFBertHeads.mlpackage (출력 {len(names)}개: {', '.join(names)})")

    shutil.copy(run_dir / "tokenizer" / "tokenizer.json", OUT / "tokenizer.json")
    print("저장: tokenizer.json")


if __name__ == "__main__":
    main()
