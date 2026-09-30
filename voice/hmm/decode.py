"""모델 점수(logits) → 6개 출력 필드. HANDMADE-MODEL src/handmade_model/decode.py에서 가져왔다.

- 단일 선택(원인·중증도·나이대·성별): 점수 1위. "판단 보류"면 None
- 부위: 1위 원인이 외상/비외상성 손상일 때만 점수 1위를 쓴다 (학습에서도 그때만 가르쳤다)
- 처치: 시행 확률이 TREATMENT_THRESHOLD 이상인 보기
- 증상: BIO 전이 제약 Viterbi로 태그 열을 고름(constrained_viterbi) → B-에서 열고 같은 극성 I-로 늘려 글자 구간으로
  되돌림 → 표준명(symptom_names.py, 임시 규칙). 표준명을 못 찾으면 원문 구간 그대로 쓴다.
  CRF 층 없이 디코딩에서만 무효 전이를 막는다
- 대표 증상(질병일 때만): "있음" 증상 중 대표 증상 보기로 정리되는 것 가운데 원문에서 가장 먼저 나온 것
"""

from __future__ import annotations

import numpy as np
import torch

from . import assemble as A
from . import labels as L
from .model import DEFAULT_MAX_TOKENS, SYMPTOM_HEAD, TREATMENT_HEAD
from .symptom_names import standard_names

#: 처치 시행 판정 기준 확률. 학습 후 eval로 조정할 대상이다
TREATMENT_THRESHOLD = 0.5


_TAG_O = L.SYMPTOM_TAGS.index("O")


def _transition_scores() -> tuple[np.ndarray, np.ndarray]:
    """BIO 전이 제약 — 허용 0, 금지 −∞ (AllenNLP allowed_transitions의 BIO 규칙; Souza et al. 2019).

    I-x 앞에는 같은 극성의 B-x나 I-x만 올 수 있다. 시작·O·다른 극성 뒤의 I-는 금지하고 나머지는 전부 허용한다.
    반환: (이전 태그 × 다음 태그 행렬, 첫 토큰 점수)
    """
    size = len(L.SYMPTOM_TAGS)
    transitions = np.zeros((size, size))
    start = np.zeros(size)
    for to, to_name in enumerate(L.SYMPTOM_TAGS):
        if not to_name.startswith("I-"):
            continue
        start[to] = -np.inf
        for previous, previous_name in enumerate(L.SYMPTOM_TAGS):
            if previous_name == "O" or previous_name[2:] != to_name[2:]:
                transitions[previous, to] = -np.inf
    return transitions, start


_TRANSITIONS, _START = _transition_scores()


def constrained_viterbi(scores: torch.Tensor, offsets: list[tuple[int, int]]) -> list[int]:
    """토큰별 태그 점수 (토큰, 태그) → BIO 전이 규칙을 지키는 합계 최고 태그 열.

        ŷ = argmax_y Σ_t [ log softmax(e_t)_{y_t} + T[y_{t−1}, y_t] ]     T: 허용 0 · 금지 −∞

    특수 토큰(글자 범위가 빈 토큰)은 O로 고정한다. 토큰별 1위가 이미 규칙을 지키면 그 열이 곧 답이다.
    O는 어디서나 올 수 있어 규칙을 지키는 열이 항상 있다.
    """
    length = min(len(offsets), scores.shape[0])
    if length == 0:
        return []
    emissions = torch.log_softmax(scores[:length].detach().float().cpu(), dim=-1).numpy().astype(np.float64)
    special = np.array([start == end for start, end in offsets[:length]])
    emissions[special] = -np.inf
    emissions[special, _TAG_O] = 0.0

    columns = np.arange(emissions.shape[1])
    backpointers = np.zeros(emissions.shape, dtype=np.int64)
    best = _START + emissions[0]
    for t in range(1, length):
        candidates = best[:, None] + _TRANSITIONS
        backpointers[t] = candidates.argmax(axis=0)
        best = candidates[backpointers[t], columns] + emissions[t]
    tag = int(best.argmax())
    path = [tag]
    for t in range(length - 1, 0, -1):
        tag = int(backpointers[t, tag])
        path.append(tag)
    return path[::-1]


def decode_spans(tags: list[int], offsets: list[tuple[int, int]], text: str) -> list[dict]:
    """토큰 태그 → 증상 글자 구간. B-에서 구간을 열고 같은 극성의 I-로 늘리며, O·특수 토큰에서 닫는다.

    태그 열은 BIO 전이 규칙을 지켜야 한다 — 모델 점수는 constrained_viterbi(), 정답은 dataset.symptom_tags()가
    그렇게 만든다. 규칙을 어긴 열이 들어오면 ValueError.
    """
    spans: list[dict] = []
    current = None
    for position, (tag, (start, end)) in enumerate(zip(tags, offsets)):
        name = L.SYMPTOM_TAGS[tag]
        if start == end or name == "O":
            current = None
            continue
        boundary, polarity = name.split("-", 1)
        present = polarity == "증상있음"
        if boundary == "B":
            current = {"start": start, "end": end, "present": present}
            spans.append(current)
        elif current is not None and current["present"] == present:
            current["end"] = end
        else:
            raise ValueError(f"BIO 전이 규칙 위반: 토큰 {position}의 {name} 앞에 같은 극성의 구간이 열려 있지 않음")
    for span in spans:
        span["span_text"] = text[span["start"] : span["end"]]
    return spans


def symptom_mentions(spans: list[dict]) -> list[dict]:
    """assemble.assemble_symptoms()가 받는 모양으로 편다. 한 구간에 표준명이 여럿이면 원문 위치 순으로 각각 한 건."""
    mentions = []
    for span in spans:
        names = standard_names(span["span_text"])
        if not names:
            mentions.append({"start": span["start"], "present": span["present"], "standard_name": span["span_text"].strip()})
        for offset, name in names:
            mentions.append({"start": span["start"] + offset, "present": span["present"], "standard_name": name})
    return mentions


def representative_symptom(mentions: list[dict]) -> str | None:
    for mention in sorted(mentions, key=lambda m: m["start"]):
        if mention["present"] and mention["standard_name"] in L.REPRESENTATIVE_SYMPTOMS:
            return mention["standard_name"]
    return None


def _choice(label_set: L.LabelSet, scores: torch.Tensor) -> str | None:
    label = label_set.classes[int(scores.argmax())]
    return None if label == L.UNDECIDED else label


def decode_example(logits: dict[str, torch.Tensor], offsets: list[tuple[int, int]], text: str, mapping: dict) -> dict:
    """통화 한 건의 점수(배치 차원 없음) → {"final_output", "fields", "symptom_spans"}.

    fields는 조립 전 중간값(원인·부위·대표 증상 등)으로, 평가에서 필드별 정확도를 잴 때 쓴다.
    """
    cause = _choice(L.CAUSE, logits["cause"])
    cause_type = L.CAUSE_TYPE.get(cause) if cause else None
    body_part = _choice(L.BODY_PART, logits["body_part"]) if cause_type in (L.TRAUMA, L.NON_TRAUMATIC_INJURY) else None
    severity_tag = L.SEVERITY.classes[int(logits["severity"].argmax())]
    age_band = _choice(L.AGE_BAND, logits["age_band"])
    sex = _choice(L.SEX, logits["sex"])
    probabilities = torch.sigmoid(logits[TREATMENT_HEAD]).tolist()
    treatment = [name for name, p in zip(L.TREATMENTS, probabilities) if p >= TREATMENT_THRESHOLD]

    tags = constrained_viterbi(logits[SYMPTOM_HEAD], offsets)
    spans = decode_spans(tags, offsets, text)
    mentions = symptom_mentions(spans)
    rep_symptom = representative_symptom(mentions) if cause_type == L.DISEASE else None

    fields = {
        "cause": cause, "cause_type": cause_type, "body_part": body_part, "representative_symptom": rep_symptom,
        "age_band": age_band, "sex": sex, "severity_tag": severity_tag, "treatment": treatment,
    }
    final_output = A.assemble_output(
        cause, cause_type, body_part, rep_symptom, age_band, sex, severity_tag, treatment, mentions, mapping
    )
    return {"final_output": final_output, "fields": fields, "symptom_spans": spans}


def predict(model, tokenizer, texts: list[str], device: torch.device, max_tokens: int = DEFAULT_MAX_TOKENS, mapping: dict | None = None) -> list[dict]:
    """통화 텍스트 목록 → 건별 decode_example() 결과. 모델은 eval 모드로 넘길 것."""
    mapping = mapping or A.load_department_mapping()
    enc = tokenizer(texts, padding=True, truncation=True, max_length=max_tokens, return_offsets_mapping=True, return_tensors="pt")
    with torch.no_grad():
        logits = model(enc["input_ids"].to(device), enc["attention_mask"].to(device))
    results = []
    for i, text in enumerate(texts):
        length = int(enc["attention_mask"][i].sum())
        offsets = [tuple(pair) for pair in enc["offset_mapping"][i][:length].tolist()]
        example_logits = {name: (scores[i, :length] if name == SYMPTOM_HEAD else scores[i]).cpu() for name, scores in logits.items()}
        results.append(decode_example(example_logits, offsets, text, mapping))
    return results
