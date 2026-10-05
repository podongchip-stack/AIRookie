"""MF_BERT(best.pt) -> ONNX 두 모델(fp32). 정밀도를 바꾸지 않는다 — 양자화·fp16 변환 없음.

아이폰(dashboard/iphone/convert/convert_mf_bert.py)과 같은 분할을 쓴다(mf_bert_split.Encoder/Heads). 앱은 onnxruntime-android
CPU로 돌린다. 가중치는 voice와 같은 Hub 저장소·커밋(voice/weights.py — podongchip/MF_BERT@f1d3e1d…)에서 받는다.

    conda activate goldenlink-android     # README "1. PC Python 환경"
    python dashboard/android/convert/convert_mf_bert.py
    python dashboard/android/convert/check_mf_bert.py      # 반드시 대조까지

출력: dashboard/android/Models/  (git에 올리지 않는다 — .gitignore)
    mf_bert_encoder.onnx + .data    input_ids (1, L) int64, L <= 512   -> hidden (N, L, 1024)
    mf_bert_heads.onnx + .data      hidden (N, T, 1024) float32        -> 헤드 이름별 로짓 + spans (1, T, 11)
    mf_bert_tokenizer.json          MF_BERT tokenizer/tokenizer.json 그대로
    mf_bert_meta.json               헤드 이름 순서·층 수·Hub 커밋(앱이 화면·요약에 표시)
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "dashboard" / "iphone" / "convert"))
sys.path.insert(0, str(ROOT / "voice"))

from mf_bert_split import Encoder, Heads  # noqa: E402
from onnx_files import save_one_file  # noqa: E402
from MF_BERT import MODEL_NAME, MfBertExtractor  # noqa: E402
from weights import MF_BERT_REPO_ID, MF_BERT_REVISION, resolve_mf_bert_dir  # noqa: E402

OUT = HERE.parent / "Models"
OPSET = 17


def main() -> None:
    OUT.mkdir(exist_ok=True)
    run_dir = resolve_mf_bert_dir()
    ext = MfBertExtractor(device="cpu", run_dir=run_dir)  # fp32
    model = ext.model.eval()
    model.encoder.set_attn_implementation("eager")  # sdpa 마스크 생성은 추적이 깨지기 쉽다(결과는 같다)
    n, hidden = model.layer_count, model.encoder.config.hidden_size

    tmp = Path(tempfile.mkdtemp(prefix="mf_onnx_", dir=OUT))
    with torch.no_grad():
        torch.onnx.export(
            Encoder(model).eval(), (torch.ones(1, 64, dtype=torch.long) * 5,), str(tmp / "mf_bert_encoder.onnx"),
            input_names=["input_ids"], output_names=["hidden"],
            dynamic_axes={"input_ids": {1: "L"}, "hidden": {1: "L"}},
            opset_version=OPSET, dynamo=False, external_data=True,
        )

        heads = Heads(model).eval()
        names = heads.head_names()
        torch.onnx.export(
            heads, (torch.randn(n, 64, hidden),), str(tmp / "mf_bert_heads.onnx"),
            input_names=["hidden"], output_names=names,
            dynamic_axes={"hidden": {1: "T"}, "spans": {1: "T"}},
            opset_version=OPSET, dynamo=False, external_data=True,
        )
    for name in ("mf_bert_encoder.onnx", "mf_bert_heads.onnx"):
        save_one_file(tmp / name, OUT / name)  # 그래프와 가중치(.data)를 나눈다
        print(f"저장: {name} (+ {name}.data)")
    shutil.rmtree(tmp)

    shutil.copy(run_dir / "tokenizer" / "tokenizer.json", OUT / "mf_bert_tokenizer.json")
    (OUT / "mf_bert_meta.json").write_text(json.dumps({
        "model": MODEL_NAME, "repo": MF_BERT_REPO_ID, "revision": MF_BERT_REVISION,
        "layers": n, "hidden": hidden, "heads": names, "precision": "fp32",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장: mf_bert_tokenizer.json, mf_bert_meta.json")


if __name__ == "__main__":
    main()
