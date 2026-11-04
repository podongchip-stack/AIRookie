"""활력징후 질문의 구간 점수 -> 수치 (규칙). 원본 MF_BERT_vitals/vitals.py의 decode·read_value다(정답 만들기 코드는 뺐다).

모델은 환자마다 활력징후 8개를 묻고, 통화 토큰 위에서 수치가 적힌 구간의 시작·끝 토큰을 고른다.
구간 말고 두 가지 답이 더 있다: 없음(말하지 않았거나 수치 없는 표현), 0(무호흡·맥박 없음처럼 0인데 숫자 글자가 없음).

토큰 줄 위치: [CLS]가 0, 본문 토큰이 1..n, [SEP]가 n+1이다(chunking.py가 복원하는 줄과 같다). 토큰 폭이 W면
없음 슬롯은 W, 0 슬롯은 W+1 자리다. 수치 범위 검사(예: 혈압 300 초과 거르기)는 하지 않는다.
"""

from __future__ import annotations

from functools import partial

import numpy as np

from .ko_number import candidate_spans, parse_number, parse_temperature

#: 시작 토큰에서 끝 토큰을 찾는 범위 (정답 구간의 최대 토큰 수보다 넉넉하게)
MAX_SPAN_TOKENS = 8


def read_value(field: str, text: str) -> float | int | None:
    """고른 구간의 글자 -> 수치. 토큰이 조사까지 묶여 구간이 걸쳤으면('백삼십에', '구십팔이') 숫자로 읽히는 가장 긴 부분을 쓴다.
    문법에 맞게 읽히는 것(strict)을 먼저 찾고, 없으면 느슨하게 읽는다. 못 읽으면 None."""
    parse = parse_temperature if field == "temp" else parse_number
    for parser in (partial(parse, strict=True), parse):
        value = parser(text)
        if value is not None:
            return value
        cands = candidate_spans(text, parser=parser)
        if cands:
            return max(cands, key=lambda c: c[1] - c[0])[2]
    return None


def decode(field: str, start_logits, end_logits, text: str, offsets: np.ndarray, width: int) -> float | int | None:
    """질문 하나의 시작·끝 점수 (W+2,) -> 수치. 시작을 먼저 고르고, 슬롯이 아니면 그 뒤 MAX_SPAN_TOKENS 안에서 끝을 고른다.
    없음이거나 구간을 숫자로 못 읽으면 None, 0 슬롯이면 0."""
    n = len(offsets)
    valid = list(range(1, n + 1)) + [width, width + 1]
    start = max(valid, key=lambda i: float(start_logits[i]))
    if start == width:
        return None
    if start == width + 1:
        return 0
    end = max(range(start, min(start + MAX_SPAN_TOKENS, n + 1)), key=lambda i: float(end_logits[i]))
    return read_value(field, text[int(offsets[start - 1, 0]):int(offsets[end - 1, 1])])
