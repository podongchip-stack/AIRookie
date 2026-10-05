"""ONNX MF_BERT가 서버(PyTorch 원본)와 같은 summary를 내는지 대조한다(통과 기준: 17필드 완전 일치).

    python dashboard/android/convert/check_mf_bert.py                       # 기본 문장들
    python dashboard/android/convert/check_mf_bert.py voice/data/**/*.txt   # 실제 통화 텍스트
    python dashboard/android/convert/check_mf_bert.py --fixtures            # + 앱(Kotlin) 끝단 테스트용 정답 저장

기록: 헤드별 로짓 최대 절대오차. 통과 조건: decode() 결과 JSON이 서버 경로(MfBertExtractor.extract)와 완전 일치.
onnxruntime CPU로 돈다 — 안드로이드 앱(onnxruntime-android CPU)과 같은 실행기.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "dashboard" / "iphone" / "convert"))
sys.path.insert(0, str(ROOT / "voice"))

from mf_bert_split import Heads, run_split  # noqa: E402
from MF_BERT import MfBertExtractor  # noqa: E402
from MF_BERT.chunking import chunk_text  # noqa: E402
from MF_BERT.decode import decode  # noqa: E402

MODELS = HERE.parent / "Models"
# 아이폰 대조(dashboard/iphone/convert/check_mf_bert.py)와 같은 기본 문장 + 긴 통화·빈 통화
DEFAULT_TEXTS = [
    "구급대원입니다. 62세 남성 30분 전부터 흉통 호소, 혈압 150에 90 맥박 110 산소포화도 96%, ECG 시행했습니다.",
    "교통사고 운전자 50대 여성, 의식 V, 좌측 다리 골절 의심 부목 고정했고 혈압 백에 육십입니다.",
    "생후 8개월 여아 열 39도 8부, 경련 5분, 산소 투여 중입니다.",
]
EXTRA_TEXTS = [
    "\n".join(["구급대원: 62세 남성 흉통 30분 전부터, 혈압 150에 90, 산소포화도 96%, 아스피린 복용 중입니다."] * 40),  # 512토큰 넘는 긴 통화
    "",
]


class OnnxEncoder:
    def __init__(self) -> None:
        self.s = ort.InferenceSession(str(MODELS / "mf_bert_encoder.onnx"), providers=["CPUExecutionProvider"])

    def __call__(self, input_ids: torch.Tensor) -> torch.Tensor:
        return torch.from_numpy(self.s.run(["hidden"], {"input_ids": input_ids.numpy().astype(np.int64)})[0])


class OnnxHeads:
    def __init__(self, names: list[str]) -> None:
        self.s = ort.InferenceSession(str(MODELS / "mf_bert_heads.onnx"), providers=["CPUExecutionProvider"])
        self.names = names

    def __call__(self, hidden: torch.Tensor) -> tuple[torch.Tensor, ...]:
        out = self.s.run(self.names, {"hidden": hidden.numpy().astype(np.float32)})
        return tuple(torch.from_numpy(o) for o in out)


def main() -> None:
    save = "--fixtures" in sys.argv
    paths = [p for p in sys.argv[1:] if p != "--fixtures"]
    texts = [Path(p).read_text(encoding="utf-8") for p in paths] or DEFAULT_TEXTS + EXTRA_TEXTS
    ext = MfBertExtractor(device="cpu")
    model, tok = ext.model.eval(), ext.tokenizer
    enc, heads = OnnxEncoder(), OnnxHeads(Heads(model).head_names())
    failed = 0
    reference_out = []
    for i, text in enumerate(texts):
        offsets = chunk_text(text, tok)["offsets"]
        reference, _ = ext.extract(text)  # 서버와 똑같은 경로(PyTorch, 패딩 배치)
        onnx = run_split(model, tok, text, encoder=enc, heads=heads)
        pytorch = run_split(model, tok, text)
        worst = max((onnx[k] - pytorch[k]).abs().max().item() for k in onnx)
        got = decode(text, onnx, offsets)
        same = json.dumps(got, ensure_ascii=False, sort_keys=True) == json.dumps(reference, ensure_ascii=False, sort_keys=True)
        failed += not same
        reference_out.append({"text": text, "summary": reference})
        print(f"[{i}] 토큰 {len(offsets)}개 · 로짓 최대 오차 {worst:.2e} · summary {'일치' if same else '불일치 ✗'}")
        if not same:
            print("  PyTorch:", json.dumps(reference, ensure_ascii=False))
            print("  ONNX   :", json.dumps(got, ensure_ascii=False))
    print(f"\n{len(texts) - failed}/{len(texts)} 일치")
    if save:  # 앱(Kotlin) 끝단 테스트(OnDeviceE2ETest)가 쓰는 서버 정답
        out = HERE.parent / "fixtures" / "mf_bert_reference.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(reference_out, ensure_ascii=False), encoding="utf-8")
        print(f"저장: {out}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
