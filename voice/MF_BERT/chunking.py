"""통화 텍스트 -> 512토큰 조각 + 조각을 다시 한 줄로 이어 붙일 정보.

긴 텍스트는 stride만큼 겹치게 여러 조각으로 나눈다. 겹친 토큰은 두 조각 중 가장자리에서 먼 쪽 하나만 남긴다
(겹친 구간의 가운데를 경계로 앞은 앞 조각, 뒤는 뒤 조각). 남긴 토큰을 순서대로 이어 붙이면 원문 토큰 줄이 복원된다.
첫 조각의 [CLS]와 마지막 조각의 [SEP]도 남겨서, 조각이 하나뿐인 통화는 HMM v2 입력과 똑같아진다.
"""

from __future__ import annotations

import torch

CHUNK_TOKENS = 512
STRIDE = 128


def chunk_text(text: str, tokenizer, chunk_tokens: int = CHUNK_TOKENS, stride: int = STRIDE) -> dict:
    """
    반환
        chunks:  조각별 토큰 id 목록 (각각 [CLS] ... [SEP])
        keep:    조각별 남길 토큰 위치(조각 안 인덱스) 목록
        offsets: 남긴 토큰들의 원문 글자 구간 [(start, end)] — 특수 토큰은 (0, 0)
    """
    body = chunk_tokens - 2
    if not 0 <= stride < body:
        raise ValueError(f"stride must be in [0, {body})")
    enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    ids, offsets = enc["input_ids"], [tuple(pair) for pair in enc["offset_mapping"]]
    n = len(ids)

    starts = [0]
    while starts[-1] + body < n:
        starts.append(starts[-1] + body - stride)
    ends = [min(start + body, n) for start in starts]
    # 조각 i가 맡는 원문 토큰 구간 [owned[i], owned[i + 1])
    owned = [0] + [(starts[i + 1] + ends[i]) // 2 for i in range(len(starts) - 1)] + [n]

    chunks, keep = [], []
    kept_offsets = [(0, 0)]
    for i, (start, end) in enumerate(zip(starts, ends)):
        chunks.append([tokenizer.cls_token_id] + ids[start:end] + [tokenizer.sep_token_id])
        positions = [j - start + 1 for j in range(owned[i], owned[i + 1])]
        if i == 0:
            positions = [0] + positions
        if i == len(starts) - 1:
            positions = positions + [end - start + 1]
        keep.append(positions)
        kept_offsets.extend(offsets[owned[i] : owned[i + 1]])
    kept_offsets.append((0, 0))
    return {"chunks": chunks, "keep": keep, "offsets": kept_offsets}


def collate(items: list[dict], pad_token_id: int) -> dict[str, torch.Tensor]:
    """chunk_text() 결과 여러 개 -> 모델 입력 텐서. 조각 수와 조각 길이는 배치 안 최댓값에 맞춰 채운다.

        input_ids, attention_mask, keep_mask: (B, C, L)
        chunk_mask: (B, C)   실제 조각이면 True
        token_mask: (B, T)   복원한 토큰 줄에서 실제 토큰이면 True (T = 배치 안 최대 토큰 수)
    """
    batch = len(items)
    max_chunks = max(len(item["chunks"]) for item in items)
    max_len = max(len(chunk) for item in items for chunk in item["chunks"])
    max_tokens = max(len(item["offsets"]) for item in items)

    input_ids = torch.full((batch, max_chunks, max_len), pad_token_id, dtype=torch.long)
    attention_mask = torch.zeros((batch, max_chunks, max_len), dtype=torch.long)
    keep_mask = torch.zeros((batch, max_chunks, max_len), dtype=torch.bool)
    chunk_mask = torch.zeros((batch, max_chunks), dtype=torch.bool)
    token_mask = torch.zeros((batch, max_tokens), dtype=torch.bool)
    for b, item in enumerate(items):
        for c, (chunk, positions) in enumerate(zip(item["chunks"], item["keep"])):
            input_ids[b, c, : len(chunk)] = torch.tensor(chunk)
            attention_mask[b, c, : len(chunk)] = 1
            keep_mask[b, c, positions] = True
            chunk_mask[b, c] = True
        token_mask[b, : len(item["offsets"])] = True
    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "chunk_mask": chunk_mask,
        "keep_mask": keep_mask,
        "token_mask": token_mask,
    }
