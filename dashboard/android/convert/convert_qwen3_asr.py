"""Qwen3-ASR-0.6B-hf + LoRA 어댑터 -> 하나로 합친 fp32 ONNX 두 그래프. 양자화·fp16 변환 없음.

가중치는 voice와 같은 저장소에서 받는다(voice/asr.py BASE_MODEL_ID, voice/weights.py 어댑터). 어댑터는 fp32로 합친다.

    conda activate goldenlink-android
    python dashboard/android/convert/convert_qwen3_asr.py
    python dashboard/android/convert/check_qwen3_asr.py data/voice_data/origin_data/*.wav    # 반드시 대조까지

출력: dashboard/android/Models/  (git에 올리지 않는다)
    asr_audio_encoder.onnx (+ .data)  chunks (C,1,128,100) float32, valid_index (T,) int64, attn_bias (T,T) float32 -> audio_embeds (T,1024)
    asr_decoder.onnx (+ .data)        input_ids (1,S) int64, audio_embeds (A,1024), past_key/past_value (28,1,8,P,128)
                                      -> logits (1,V), present_key/present_value (28,1,8,P+S,128)
    asr_mel_filters.bin               (201, 128) float32 little-endian — 특징 추출기의 멜 필터 그대로
    asr_tokens.json                   프롬프트 앞·뒤 토큰 id, 오디오 토큰 id, eos, 바이트 BPE 어휘(id -> 문자열), 특수 토큰
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


import torch
from peft import PeftModel
from transformers import AutoProcessor, Qwen3ASRForConditionalGeneration

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "voice"))

from asr import BASE_MODEL_ID, MAX_NEW_TOKENS, MODEL_NAME  # noqa: E402
from onnx_files import save_one_file  # noqa: E402
from qwen3_asr_split import AudioEncoder, Decoder  # noqa: E402
from weights import ASR_ADAPTER_REPO_ID, resolve_asr_adapter_dir  # noqa: E402

OUT = HERE.parent / "Models"
OPSET = 17
PROMPT_TEXT = "language Korean<asr_text>"


def load_merged():
    """베이스 + 어댑터를 fp32로 합친 모델(eval)."""
    base = Qwen3ASRForConditionalGeneration.from_pretrained(BASE_MODEL_ID, dtype=torch.float32)
    peft = PeftModel.from_pretrained(base, str(resolve_asr_adapter_dir()))
    return peft.merge_and_unload().eval()


def prompt_parts(processor) -> tuple[list[int], list[int]]:
    """프롬프트 = 앞 + [오디오 토큰] * N + 뒤. 길이가 다른 두 오디오로 앞·뒤가 같은지 확인한다."""
    import numpy as np

    audio_id = processor.audio_token_id
    parts = None
    for seconds in (1.0, 4.3):
        conv = [
            {"role": "user", "content": [{"type": "audio", "audio": np.zeros(int(seconds * 16000), dtype=np.float32)}]},
            {"role": "assistant", "content": [{"type": "text", "text": PROMPT_TEXT}]},
        ]
        ids = processor.apply_chat_template([conv], tokenize=True, return_dict=True, continue_final_message=True)["input_ids"][0].tolist()
        first = ids.index(audio_id)
        last = len(ids) - 1 - ids[::-1].index(audio_id)
        here = (ids[:first], ids[last + 1:])
        assert parts is None or parts == here, "프롬프트 앞·뒤가 오디오 길이에 따라 바뀐다"
        parts = here
    return parts


def main() -> None:
    OUT.mkdir(exist_ok=True)
    processor = AutoProcessor.from_pretrained(BASE_MODEL_ID)
    model = load_merged()
    cfg = model.config.text_config
    layers, kv, hd, hidden = cfg.num_hidden_layers, cfg.num_key_value_heads, cfg.head_dim, cfg.hidden_size

    tmp = Path(tempfile.mkdtemp(prefix="asr_onnx_", dir=OUT))
    with torch.no_grad():
        enc = AudioEncoder(model).eval()
        t = 39
        torch.onnx.export(
            enc, (torch.randn(3, 1, 128, 100), torch.arange(t), torch.zeros(t, t)), str(tmp / "asr_audio_encoder.onnx"),
            input_names=["chunks", "valid_index", "attn_bias"], output_names=["audio_embeds"],
            dynamic_axes={"chunks": {0: "C"}, "valid_index": {0: "T"}, "attn_bias": {0: "T", 1: "T"}, "audio_embeds": {0: "T"}},
            opset_version=OPSET, dynamo=False, external_data=True,
        )

        dec = Decoder(model).eval()
        ids = torch.tensor([[1, 2, model.config.audio_token_id, model.config.audio_token_id, 3]])
        past = torch.zeros(layers, 1, kv, 4, hd)
        torch.onnx.export(
            dec, (ids, torch.randn(2, hidden), past, past.clone()), str(tmp / "asr_decoder.onnx"),
            input_names=["input_ids", "audio_embeds", "past_key", "past_value"],
            output_names=["logits", "present_key", "present_value"],
            dynamic_axes={"input_ids": {1: "S"}, "audio_embeds": {0: "A"}, "past_key": {3: "P"}, "past_value": {3: "P"},
                          "present_key": {3: "PS"}, "present_value": {3: "PS"}},
            opset_version=OPSET, dynamo=False, external_data=True,
            do_constant_folding=False,  # 접으면 lm_head용 전치 사본(622MB)이 따로 생긴다
        )
    for name in ("asr_audio_encoder.onnx", "asr_decoder.onnx"):
        save_one_file(tmp / name, OUT / name)
        print(f"저장: {name} (+ {name}.data)")
    shutil.rmtree(tmp)

    processor.feature_extractor.mel_filters.astype("<f4").tofile(OUT / "asr_mel_filters.bin")
    before, after = prompt_parts(processor)
    tok = processor.tokenizer
    vocab = tok.get_vocab()
    special = sorted({t.content for t in tok.added_tokens_decoder.values() if t.special})
    (OUT / "asr_tokens.json").write_text(json.dumps({
        "model": MODEL_NAME, "base": BASE_MODEL_ID, "adapter": ASR_ADAPTER_REPO_ID, "precision": "fp32",
        "prompt_before": before, "prompt_after": after, "audio_token_id": processor.audio_token_id,
        "eos_token_ids": list(model.generation_config.eos_token_id), "max_new_tokens": MAX_NEW_TOKENS,
        "layers": layers, "kv_heads": kv, "head_dim": hd, "hidden": hidden,
        "vocab": {str(i): t for t, i in vocab.items()}, "special_tokens": special,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"저장: asr_mel_filters.bin, asr_tokens.json (프롬프트 앞 {len(before)} + 오디오 N + 뒤 {len(after)})")


if __name__ == "__main__":
    main()
