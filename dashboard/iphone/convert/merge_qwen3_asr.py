"""Qwen3-ASR-0.6B-hf + LoRA 어댑터 -> 하나로 합친 bf16 가중치를 speech-swift(MLX Swift) 키 형식으로 저장한다.
양자화하지 않는다 — 원본과 같은 bf16. 앱의 speech-swift는 patches/의 float 디코더 패치를 적용한 포크를 쓴다.

    conda activate goldenlink-ios
    python dashboard/iphone/convert/merge_qwen3_asr.py                  # 합치기 + 저장
    python dashboard/iphone/convert/merge_qwen3_asr.py a.wav b.wav      # + 합친 모델 = 베이스+어댑터 문장 대조, 정답 저장

출력: dashboard/iphone/Models/Qwen3ASR-119ko-bf16/
    model.safetensors  vocab.json  merges.txt  tokenizer_config.json  config.json
    asr_reference.json (wav를 줬을 때) — 서버와 같은 경로(voice/asr.py, 발화 5초 분할)로 낸 문장. 아이폰 결과와 대조용

키 변환(transformers -hf 형식 -> speech-swift가 읽는 원본 Qwen3-ASR 형식):
    model.audio_tower.*                 -> audio_tower.*   (conv2d 가중치는 MLX 배치 O,H,W,I로 전치)
    model.multi_modal_projector.linear_1 -> audio_tower.proj1
    model.multi_modal_projector.linear_2 -> audio_tower.proj2
    model.language_model.*              -> model.*         (lm_head는 embed_tokens와 묶여 있어 따로 없다)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from peft import PeftModel
from safetensors.torch import save_file
from transformers import AutoProcessor, Qwen3ASRForConditionalGeneration

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "voice"))

from asr import BASE_MODEL_ID, MAX_NEW_TOKENS, load_audio, split_chunks  # noqa: E402
from weights import resolve_asr_adapter_dir  # noqa: E402

OUT = HERE.parent / "Models" / "Qwen3ASR-119ko-bf16"


def remap(state: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    out = {}
    for k, v in state.items():
        if k.startswith("model.audio_tower."):
            nk = "audio_tower." + k[len("model.audio_tower."):]
            if ".conv2d" in nk and nk.endswith(".weight"):
                v = v.permute(0, 2, 3, 1)  # PyTorch (O, I, H, W) -> MLX (O, H, W, I)
        elif k.startswith("model.multi_modal_projector.linear_1."):
            nk = "audio_tower.proj1." + k.rsplit(".", 1)[1]
        elif k.startswith("model.multi_modal_projector.linear_2."):
            nk = "audio_tower.proj2." + k.rsplit(".", 1)[1]
        elif k.startswith("model.language_model."):
            nk = "model." + k[len("model.language_model."):]
        elif k == "lm_head.weight":
            continue  # 묶인 가중치(tie_word_embeddings)
        else:
            raise KeyError(f"모르는 키: {k}")
        out[nk] = v.contiguous()
    return out


def write_tokenizer(base_dir: Path) -> None:
    tok = json.loads((base_dir / "tokenizer.json").read_text(encoding="utf-8"))
    (OUT / "vocab.json").write_text(json.dumps(tok["model"]["vocab"], ensure_ascii=False), encoding="utf-8")
    merges = [m if isinstance(m, str) else " ".join(m) for m in tok["model"]["merges"]]
    (OUT / "merges.txt").write_text("#version: 0.2\n" + "\n".join(merges) + "\n", encoding="utf-8")
    added = {str(t["id"]): {"content": t["content"], "special": t["special"]} for t in tok["added_tokens"]}
    (OUT / "tokenizer_config.json").write_text(json.dumps({"added_tokens_decoder": added}, ensure_ascii=False), encoding="utf-8")
    (OUT / "config.json").write_text((base_dir / "config.json").read_text(encoding="utf-8"), encoding="utf-8")


@torch.no_grad()
def transcribe(model, processor, audio) -> list[str]:
    """voice/asr.py AsrModel.transcribe_audio()와 같은 프롬프트·5초 분할·그리디 생성"""
    texts = []
    for start, end in split_chunks(audio, 5.0):
        conv = [
            {"role": "user", "content": [{"type": "audio", "audio": audio[start:end]}]},
            {"role": "assistant", "content": [{"type": "text", "text": "language Korean<asr_text>"}]},
        ]
        inputs = processor.apply_chat_template([conv], tokenize=True, return_dict=True, continue_final_message=True)
        inputs = inputs.to(model.device, model.dtype)
        ids = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS)
        text = processor.decode(ids[:, inputs["input_ids"].shape[1]:], return_format="transcription_only")[0].strip()
        if text:
            texts.append(text)
    return texts


def main() -> None:
    wavs = [Path(p) for p in sys.argv[1:]]
    OUT.mkdir(parents=True, exist_ok=True)
    base_dir = Path(snapshot_download(BASE_MODEL_ID))
    processor = AutoProcessor.from_pretrained(BASE_MODEL_ID)
    base = Qwen3ASRForConditionalGeneration.from_pretrained(BASE_MODEL_ID, dtype=torch.bfloat16)
    peft = PeftModel.from_pretrained(base, str(resolve_asr_adapter_dir())).eval()

    before = {w.name: transcribe(peft, processor, load_audio(w)) for w in wavs}
    merged = peft.merge_and_unload().eval()
    after = {w.name: transcribe(merged, processor, load_audio(w)) for w in wavs}
    for name in before:
        mark = "같음" if before[name] == after[name] else "다름 ✗"
        print(f"{name}: 베이스+어댑터 vs 합친 모델 {mark}")
        if before[name] != after[name]:
            print("  전:", before[name], "\n  후:", after[name])

    state = remap({k: v.to(torch.bfloat16) for k, v in merged.state_dict().items()})
    save_file(state, str(OUT / "model.safetensors"), metadata={"format": "mlx"})
    write_tokenizer(base_dir)
    if wavs:
        (OUT / "asr_reference.json").write_text(json.dumps(before, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {OUT} (텐서 {len(state)}개, bf16)")


if __name__ == "__main__":
    main()
