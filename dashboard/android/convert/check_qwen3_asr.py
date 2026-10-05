"""ONNX Qwen3-ASR가 서버(voice/asr.py AsrModel, CPU fp32)와 같은 문장을 내는지 대조한다(통과 기준: 구간마다 문장 완전 일치).

    python dashboard/android/convert/check_qwen3_asr.py data/voice_data/origin_data/*.wav
    python dashboard/android/convert/check_qwen3_asr.py --torch a.wav     # ONNX 대신 PyTorch 래퍼로(변환 전 래퍼 검사)
    python dashboard/android/convert/check_qwen3_asr.py --limit 20 ...    # 구간 수 제한
    python dashboard/android/convert/check_qwen3_asr.py --fixtures ...    # 앱 테스트용 정답(멜·프롬프트·토큰·문장)도 저장

서버 경로: 파일 -> 16kHz -> 5초 안팎 조용한 지점 분할(split_chunks) -> 구간마다 PeftModel.generate(그리디).
이쪽: 같은 분할 -> numpy 멜(qwen3_asr_split.mel_features, 앱이 옮길 계산) -> ONNX 인코더 -> 프롬프트 조립 -> ONNX 디코더
그리디 -> 바이트 BPE 풀기 -> 반복 정리·<asr_text> 뒤 추출(transformers 함수 그대로). 앱의 Kotlin은 이 경로를 옮긴다.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "voice"))

from asr import SAMPLE_RATE, AsrModel, load_audio, split_chunks  # noqa: E402
from qwen3_asr_split import audio_token_count, encoder_inputs, greedy, mel_features  # noqa: E402
from transformers.models.qwen3_asr.processing_qwen3_asr import _parse_single_output  # noqa: E402

MODELS = HERE.parent / "Models"


def bytes_to_unicode() -> dict[int, str]:
    """GPT-2 바이트 BPE 표(바이트 -> 글자). Qwen 토크나이저도 같다."""
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, map(chr, cs)))


class TokenDecoder:
    """id 목록 -> 문자열(특수 토큰 제외). 앱의 Kotlin이 옮길 계산."""

    def __init__(self, tokens: dict) -> None:
        self.vocab = {int(i): t for i, t in tokens["vocab"].items()}
        self.special = set(tokens["special_tokens"])
        self.byte_of = {c: b for b, c in bytes_to_unicode().items()}

    def __call__(self, ids: list[int]) -> str:
        data = bytearray()
        for i in ids:
            piece = self.vocab[i]
            if piece in self.special:
                continue
            data.extend(self.byte_of[c] for c in piece)
        return data.decode("utf-8", errors="replace")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wavs", nargs="+")
    ap.add_argument("--torch", action="store_true", help="ONNX 대신 PyTorch 래퍼")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--fixtures", action="store_true")
    args = ap.parse_args()

    tokens = json.loads((MODELS / "asr_tokens.json").read_text(encoding="utf-8"))
    mel_filters = np.fromfile(MODELS / "asr_mel_filters.bin", dtype="<f4").reshape(201, 128)
    decode_ids = TokenDecoder(tokens)

    # 1단계: 서버 경로로 정답(구간별 문장)을 만들어 캐시에 둔다(이어받기 가능) — 서버 모델과 ONNX를 동시에 올리면
    # fp32 두 벌(약 8GB)이라 16GB PC에서 스왑이 나 수십 배 느려진다. 정답을 다 만든 뒤 서버 모델을 내리고 2단계를 돈다.
    pieces = []
    for wav in args.wavs:
        audio = load_audio(Path(wav))
        for start, end in split_chunks(audio, 5.0):
            if args.limit and len(pieces) >= args.limit:
                break
            pieces.append((Path(wav).name, start, audio[start:end]))
    cache_file = HERE.parent / "fixtures" / "asr_server_cache.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.is_file() else {}
    todo = [p for p in pieces if f"{p[0]}@{p[1]}" not in cache]
    t_server = 0.0
    if todo:
        server = AsrModel(device="cpu")  # 서버 CPU 경로 그대로(fp32, PeftModel 합치지 않음)
        verify_tokenizer = server.processor.tokenizer
        for i, (name, start, piece) in enumerate(todo):
            t0 = time.perf_counter()
            cache[f"{name}@{start}"] = server._transcribe_chunk(piece)
            t_server += time.perf_counter() - t0
            if i % 10 == 9 or i == len(todo) - 1:
                cache_file.parent.mkdir(exist_ok=True)
                cache_file.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                print(f"  서버 정답 {i + 1}/{len(todo)}", flush=True)
        del server
        gc.collect()
    else:
        from transformers import AutoTokenizer
        from asr import BASE_MODEL_ID
        verify_tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_ID)

    if args.torch:
        import torch
        from convert_qwen3_asr import load_merged
        from qwen3_asr_split import AudioEncoder, Decoder

        merged = load_merged()
        enc_m, dec_m = AudioEncoder(merged).eval(), Decoder(merged).eval()

        def run_encoder(chunks, index, bias):
            with torch.no_grad():
                return enc_m(torch.from_numpy(chunks), torch.from_numpy(index), torch.from_numpy(bias)).numpy()

        def run_decoder(ids, audio, pk, pv):
            with torch.no_grad():
                out = dec_m(torch.from_numpy(ids), torch.from_numpy(audio), torch.from_numpy(pk), torch.from_numpy(pv))
            return tuple(o.numpy() for o in out)
    else:
        import onnxruntime as ort

        enc_s = ort.InferenceSession(str(MODELS / "asr_audio_encoder.onnx"), providers=["CPUExecutionProvider"])
        dec_s = ort.InferenceSession(str(MODELS / "asr_decoder.onnx"), providers=["CPUExecutionProvider"])

        def run_encoder(chunks, index, bias):
            return enc_s.run(None, {"chunks": chunks, "valid_index": index, "attn_bias": bias})[0]

        def run_decoder(ids, audio, pk, pv):
            return tuple(dec_s.run(None, {"input_ids": ids, "audio_embeds": audio, "past_key": pk, "past_value": pv}))

    # 2단계: 앱과 같은 경로(numpy 멜 -> 인코더 -> 그리디 -> 바이트 BPE -> 결과 정리)
    eos = set(tokens["eos_token_ids"])
    total = same = 0
    fixtures = []
    t_ours = 0.0
    for name, start, piece in pieces:
        reference = cache[f"{name}@{start}"]
        t1 = time.perf_counter()
        feats, valid = mel_features(piece, mel_filters)
        chunks, index, bias = encoder_inputs(feats, valid)
        embeds = run_encoder(chunks, index, bias)
        n = audio_token_count(valid)
        assert embeds.shape[0] == n, (embeds.shape, n)
        prompt = tokens["prompt_before"] + [tokens["audio_token_id"]] * n + tokens["prompt_after"]
        out_ids = greedy(run_encoder, run_decoder, prompt, embeds, eos, tokens["max_new_tokens"],
                         tokens["layers"], tokens["kv_heads"], tokens["head_dim"])
        raw = decode_ids(out_ids)
        assert raw == verify_tokenizer.decode(out_ids, skip_special_tokens=True), "바이트 BPE 풀기 불일치"
        ours = _parse_single_output(raw)["transcription"]
        t_ours += time.perf_counter() - t1
        total += 1
        ok = ours == reference
        same += ok
        print(f"[{total}] {name} {start / SAMPLE_RATE:6.1f}s  {'일치' if ok else '불일치 ✗'}  {reference}", flush=True)
        if not ok:
            print(f"      이쪽: {ours}", flush=True)
        if args.fixtures and len(fixtures) < 6:
            fixtures.append({"audio": piece.tolist(), "valid_frames": valid, "mel_head": feats[:, :8].tolist(),
                             "mel_sum": float(feats.sum()), "valid_index": index.tolist(), "prompt": prompt,
                             "ids": out_ids, "raw": raw, "text": ours})
            if len(fixtures) == 6 or total == len(pieces):
                (HERE.parent / "fixtures" / "asr_fixtures.json").write_text(json.dumps(fixtures, ensure_ascii=False), encoding="utf-8")
                print("저장: fixtures/asr_fixtures.json", flush=True)
    print(f"\n{same}/{total} 일치 · 구간당 이쪽 {t_ours / max(total, 1):.2f}초"
          + (f" / 서버 {t_server / len(todo):.2f}초" if todo else "") + " (PC CPU)")
    sys.exit(0 if same == total else 1)


if __name__ == "__main__":
    main()
