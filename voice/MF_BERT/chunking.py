"""통화 텍스트 -> 512토큰 조각 + 조각을 다시 한 줄로 이어 붙일 정보. 원본은 MF_BERT_vitals/chunking.py의 chunk_text다.

긴 텍스트는 stride만큼 겹치게 여러 조각으로 나눈다. 겹친 토큰은 두 조각 중 가장자리에서 먼 쪽 하나만 남긴다
(겹친 구간의 가운데를 경계로 앞은 앞 조각, 뒤는 뒤 조각). 남긴 토큰을 순서대로 이어 붙이면 원문 토큰 줄이 복원된다.
첫 조각의 [CLS]와 마지막 조각의 [SEP]도 남긴다. 활력징후 구간(vitals.py)을 원문 글자로 되돌리려고 토큰마다
원문 글자 위치(offsets)도 돌려준다.
"""

from __future__ import annotations

import numpy as np

CHUNK_TOKENS = 512
STRIDE = 128


def chunk_text(text: str, tokenizer, chunk_tokens: int = CHUNK_TOKENS, stride: int = STRIDE) -> dict:
    """
    반환
        chunks:  조각별 토큰 id 목록 (각각 [CLS] ... [SEP])
        keep:    조각별 남길 토큰 위치(조각 안 인덱스) 목록
        length:  남긴 토큰 수 ([CLS]·[SEP] 포함)
        offsets: 본문 토큰마다 원문 글자 (시작, 끝) (n, 2) int32. [CLS]·[SEP]는 없다
    """
    body = chunk_tokens - 2
    if not 0 <= stride < body:
        raise ValueError(f"stride must be in [0, {body})")
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    ids = encoded["input_ids"]
    n = len(ids)

    starts = [0]
    while starts[-1] + body < n:
        starts.append(starts[-1] + body - stride)
    ends = [min(start + body, n) for start in starts]
    # 조각 i가 맡는 원문 토큰 구간 [owned[i], owned[i + 1])
    owned = [0] + [(starts[i + 1] + ends[i]) // 2 for i in range(len(starts) - 1)] + [n]

    chunks, keep = [], []
    for i, (start, end) in enumerate(zip(starts, ends)):
        chunks.append([tokenizer.cls_token_id] + ids[start:end] + [tokenizer.sep_token_id])
        positions = [j - start + 1 for j in range(owned[i], owned[i + 1])]
        if i == 0:
            positions = [0] + positions
        if i == len(starts) - 1:
            positions = positions + [end - start + 1]
        keep.append(positions)
    return {"chunks": chunks, "keep": keep, "length": n + 2,
            "offsets": np.asarray(encoded["offset_mapping"], dtype=np.int32).reshape(-1, 2)}
