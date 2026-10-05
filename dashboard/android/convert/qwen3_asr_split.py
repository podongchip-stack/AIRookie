"""Qwen3-ASR(베이스 + LoRA 합친 모델)를 ONNX 두 그래프로 나누는 래퍼 + 안드로이드 앱과 같은 순서로 도는 Python 기준 구현.

    AudioEncoder : chunks (C, 1, 128, 100), valid_index (T,), attn_bias (T, T)  -> audio_embeds (T, 1024)
                   오디오 타워(합성곱 3층 + 트랜스포머 18층) + 멀티모달 프로젝터
    Decoder      : input_ids (1, S), audio_embeds (A, 1024), past_key/past_value (28, 1, 8, P, 128)
                   -> logits (1, V)  마지막 위치만, present_key/present_value (28, 1, 8, P+S, 128)
                   언어 모델(Qwen3 28층) + lm_head. 오디오 자리(audio_token_id)는 audio_embeds로 바꿔 넣는다

transformers의 forward를 그대로 따라 쓰되, 추적이 안 되는 부분(nonzero로 고르는 유효 위치, 창별로 쪼개는 어텐션,
DynamicCache)만 입력으로 바꿨다 — 유효 위치는 valid_index로, 창(800프레임 = 104토큰) 나누기는 블록 대각 attn_bias로,
KV 캐시는 텐서로. 계산식은 같다(eager_attention_forward: softmax는 fp32). 같은지는 check_qwen3_asr.py가
transformers generate()와 문장 단위로 대조한다.

멜 스펙트로그램·프롬프트 조립·그리디 생성·토큰 풀기는 그래프 밖(앱의 Kotlin)이다. 여기의 mel_features / build_prompt /
greedy / decode_tokens가 앱이 그대로 옮길 기준이다.
"""

from __future__ import annotations

import math

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

SAMPLE_RATE = 16000
N_FFT = 400
HOP = 160
N_MELS = 128
MIN_SAMPLES = 8000          # 0.5초보다 짧으면 0으로 채운다
CHUNK_FRAMES = 100          # n_window * 2
TOKENS_PER_CHUNK = 13       # 100프레임 -> 합성곱 3층(stride 2) 뒤 13
WINDOW_TOKENS = 13 * 8      # n_window_infer 800프레임 = 8조각 = 104토큰 안에서만 서로 본다


# ── 멜 스펙트로그램(Qwen3ASRFeatureExtractor와 같은 계산, numpy) ──

def mel_features(audio: np.ndarray, mel_filters: np.ndarray) -> tuple[np.ndarray, int]:
    """16kHz float32 -> (log-mel (128, F), 유효 프레임 수). F는 100의 배수.

    서버(voice/asr.py)는 processor.apply_chat_template로 특징을 만든다 — 이때 특징 추출기는 padding="longest"(한 건이면
    오디오 길이 그대로, 30초로 채우지 않음)다. 그래서: 0.5초 미만은 0으로 채우고, torch.stft(center=True, reflect —
    실제 오디오 끝에서 반사, hann periodic, 마지막 프레임 버림) -> 멜 -> log10(1e-10 하한) -> (이 오디오의) 최댓값-8 하한
    -> (x+4)/4, 유효 프레임 = 샘플수 // 160, 100프레임 배수까지 0으로 채움. 특징 추출기 기본값(30초 채움)과 다르다.
    """
    audio = audio.astype(np.float32)
    if len(audio) < MIN_SAMPLES:
        audio = np.pad(audio, (0, MIN_SAMPLES - len(audio)))
    n = len(audio)
    frames = n // HOP  # stft 프레임 n//HOP + 1개 중 마지막을 버림 = 유효 프레임(마스크)과 같다
    used = math.ceil(frames / CHUNK_FRAMES) * CHUNK_FRAMES
    x = np.pad(audio, (N_FFT // 2, N_FFT // 2), mode="reflect")
    window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(frames)[:, None]
    spec = np.fft.rfft(x[idx] * window, axis=1)
    power = (spec.real ** 2 + spec.imag ** 2).astype(np.float32)          # (frames, 201)
    mel = mel_filters.T.astype(np.float32) @ power.T                      # (128, frames)
    log_spec = np.log10(np.maximum(mel, 1e-10))
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    log_spec = (log_spec + 4.0) / 4.0
    log_spec = np.pad(log_spec, ((0, 0), (0, used - frames)))  # 100프레임 배수까지 0(특징 추출기와 같다)
    return log_spec.astype(np.float32), frames


def audio_token_count(valid_frames: int) -> int:
    rem = valid_frames % CHUNK_FRAMES
    feat = (rem - 1) // 2 + 1
    per = (feat - 1) // 2 + 1
    return (per - 1) // 2 + 1 + (valid_frames // CHUNK_FRAMES) * TOKENS_PER_CHUNK


def _post_cnn(length: int) -> int:
    for _ in range(3):
        length = (length - 1) // 2 + 1 if length > 0 else 0
    return length


def encoder_inputs(features: np.ndarray, valid_frames: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(128, F) -> chunks (C, 1, 128, 100), valid_index (T,), attn_bias (T, T)."""
    c = features.shape[1] // CHUNK_FRAMES
    chunks = features.reshape(N_MELS, c, CHUNK_FRAMES).transpose(1, 0, 2)[:, None]
    index = []
    for i in range(c):
        frames_in_chunk = min(max(valid_frames - i * CHUNK_FRAMES, 0), CHUNK_FRAMES)
        index += [i * TOKENS_PER_CHUNK + j for j in range(_post_cnn(frames_in_chunk))]
    t = len(index)
    window = np.arange(t) // WINDOW_TOKENS
    bias = np.where(window[:, None] == window[None, :], 0.0, -np.inf).astype(np.float32)
    return np.ascontiguousarray(chunks, dtype=np.float32), np.array(index, dtype=np.int64), bias


# ── 그래프 ──

class AudioEncoder(nn.Module):
    def __init__(self, model) -> None:
        super().__init__()
        self.tower = model.model.audio_tower
        self.proj = model.model.multi_modal_projector

    def forward(self, chunks: torch.Tensor, valid_index: torch.Tensor, attn_bias: torch.Tensor) -> torch.Tensor:
        t = self.tower
        x = F.gelu(t.conv2d1(chunks))
        x = F.gelu(t.conv2d2(x))
        x = F.gelu(t.conv2d3(x))
        c, ch, fb, ts = x.shape
        x = t.conv_out(x.permute(0, 3, 1, 2).reshape(c, ts, ch * fb))
        x = x + t.positional_embedding.positional_embedding[:ts].to(x.dtype)
        h = x.reshape(-1, x.shape[-1]).index_select(0, valid_index)
        for layer in t.layers:
            a = layer.self_attn
            r = h
            h = layer.self_attn_layer_norm(h)
            n = h.shape[0]
            q = a.q_proj(h).reshape(n, a.num_heads, -1).transpose(0, 1)
            k = a.k_proj(h).reshape(n, a.num_heads, -1).transpose(0, 1)
            v = a.v_proj(h).reshape(n, a.num_heads, -1).transpose(0, 1)
            w = torch.matmul(q, k.transpose(1, 2)) * a.scaling + attn_bias
            w = torch.softmax(w, dim=-1, dtype=torch.float32).to(q.dtype)
            h = a.out_proj(torch.matmul(w, v).transpose(0, 1).reshape(n, -1))
            h = r + h
            r = h
            h = layer.fc2(layer.activation_fn(layer.fc1(layer.final_layer_norm(h))))
            h = r + h
        return self.proj(t.ln_post(h))


def _rotate_half(x: torch.Tensor) -> torch.Tensor:
    x1, x2 = x[..., : x.shape[-1] // 2], x[..., x.shape[-1] // 2 :]
    return torch.cat((-x2, x1), dim=-1)


class Decoder(nn.Module):
    def __init__(self, model) -> None:
        super().__init__()
        lm = model.model.language_model
        self.embed = lm.embed_tokens
        self.layers = lm.layers
        self.norm = lm.norm
        self.lm_head = model.lm_head
        self.register_buffer("inv_freq", lm.rotary_emb.inv_freq.clone().float(), persistent=False)
        self.scaling = float(getattr(lm.rotary_emb, "attention_scaling", 1.0))
        cfg = lm.config
        self.heads, self.kv_heads, self.head_dim = cfg.num_attention_heads, cfg.num_key_value_heads, cfg.head_dim
        self.audio_token_id = model.config.audio_token_id

    def forward(self, input_ids, audio_embeds, past_key, past_value):
        s = input_ids.shape[1]
        p = past_key.shape[3]
        x = self.embed(input_ids)                                            # (1, S, H)
        is_audio = input_ids == self.audio_token_id
        pick = (torch.cumsum(is_audio.to(torch.long), dim=1) - 1).clamp(min=0)[0]
        x = torch.where(is_audio.unsqueeze(-1), audio_embeds.index_select(0, pick).unsqueeze(0).to(x.dtype), x)

        pos = (torch.arange(s, device=x.device) + p).float()
        freqs = pos[:, None] * self.inv_freq[None, :]
        emb = torch.cat((freqs, freqs), dim=-1)
        cos, sin = (emb.cos() * self.scaling)[None, None], (emb.sin() * self.scaling)[None, None]
        q_pos = torch.arange(s, device=x.device)[:, None] + p
        k_pos = torch.arange(p + s, device=x.device)[None, :]
        mask = torch.where(k_pos <= q_pos, 0.0, float("-inf"))[None, None]

        keys, values = [], []
        rep = self.heads // self.kv_heads
        for i, layer in enumerate(self.layers):
            at = layer.self_attn
            r = x
            h = layer.input_layernorm(x)
            q = at.q_norm(at.q_proj(h).view(1, s, self.heads, self.head_dim)).transpose(1, 2)
            k = at.k_norm(at.k_proj(h).view(1, s, self.kv_heads, self.head_dim)).transpose(1, 2)
            v = at.v_proj(h).view(1, s, self.kv_heads, self.head_dim).transpose(1, 2)
            q = q * cos + _rotate_half(q) * sin
            k = k * cos + _rotate_half(k) * sin
            k = torch.cat((past_key[i], k), dim=2)
            v = torch.cat((past_value[i], v), dim=2)
            keys.append(k)
            values.append(v)
            kk = torch.repeat_interleave(k, rep, dim=1)
            vv = torch.repeat_interleave(v, rep, dim=1)
            w = torch.matmul(q, kk.transpose(2, 3)) * at.scaling + mask
            w = torch.softmax(w, dim=-1, dtype=torch.float32).to(q.dtype)
            o = torch.matmul(w, vv).transpose(1, 2).reshape(1, s, -1)
            x = r + at.o_proj(o)
            r = x
            x = r + layer.mlp(layer.post_attention_layernorm(x))
        # lm_head는 embed_tokens와 묶인 가중치(tie_word_embeddings) — 같은 표를 써서 그래프에 한 번만 담는다
        logits = torch.matmul(self.norm(x[:, -1:]), self.embed.weight.t())[:, 0]
        return logits, torch.stack(keys), torch.stack(values)


# ── 그리디 생성(앱이 옮길 기준) ──

def greedy(run_encoder, run_decoder, prompt_ids: list[int], audio_embeds: np.ndarray, eos_ids: set[int],
           max_new_tokens: int, layers: int, kv_heads: int, head_dim: int) -> list[int]:
    """generate(do_sample=False)와 같다: 프롬프트 한 번에 넣고, 이후 한 토큰씩. eos가 나오면 멈춤(eos는 결과에 안 넣음)."""
    past_k = np.zeros((layers, 1, kv_heads, 0, head_dim), dtype=np.float32)
    past_v = past_k.copy()
    ids = np.array([prompt_ids], dtype=np.int64)
    out: list[int] = []
    for _ in range(max_new_tokens):
        logits, past_k, past_v = run_decoder(ids, audio_embeds, past_k, past_v)
        token = int(np.argmax(logits[0]))
        if token in eos_ids:
            break
        out.append(token)
        ids = np.array([[token]], dtype=np.int64)
    return out
