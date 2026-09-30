"""모델 출력(logits) -> v2 스키마 JSON. C:\Dev\HMM\model_v2 infer.py의 decode()에
metrics.masked_minor()·data.decode_spans()를 합쳐 가져왔다.

`call_type`, `ktas_evidence`, `notes`는 모델이 배우는 헤드가 아니다(라벨링 시 사람/다른 도구가 채운 메타 정보).
출력에서는 항상 null이고, 그 사실을 `meta.not_predicted`에 남긴다.

다중 선택 헤드는 로짓 > 0(=sigmoid 0.5)을 양성으로 본다. `chief_complaint`는 대분류에 속한 소분류만 남기고
고른다(masked_minor) — 매 헤드를 따로 argmax하면 서로 다른 대분류가 나올 수 있어서다.
"""

from __future__ import annotations

import torch

from . import labels as L
from .model import SPAN_HEAD
from .parse import parse_age, parse_onset, parse_vitals

#: 토큰 태그 중 손실·평가에서 빼는 자리(패딩 등). 추론 때도 이 값이면 구간이 아니다
IGNORE_INDEX = -100

_TAG_O = L.SPAN_TAGS.index("O")

_MINOR_MAJOR = torch.tensor([L.MAJORS.index(m.split("|")[0]) for m in L.MINORS] + [-1])  # 미언급은 -1


def masked_minor(minor_logits: torch.Tensor, major_logits: torch.Tensor) -> torch.Tensor:
    """예측 대분류에 속한 소분류(대분류가 미언급이면 미언급)만 남기고 1위를 고른다."""
    major = major_logits.argmax(-1).cpu()
    minor = minor_logits.float().cpu()
    undecided_major = L.CC_MAJOR.index(L.UNDECIDED)
    undecided_minor = L.CC_MINOR.index(L.UNDECIDED)
    out = []
    for i in range(minor.shape[0]):
        if major[i] == undecided_major:
            out.append(undecided_minor)
            continue
        allowed = _MINOR_MAJOR == major[i]
        out.append(int(minor[i].masked_fill(~allowed, float("-inf")).argmax()))
    return torch.tensor(out)


def decode_spans(tags: list[int], offsets: list[tuple[int, int]]) -> list[dict]:
    """토큰 태그 -> 글자 구간 [{start, end, type}]. 짝 없는 I-는 그 자리에서 새 구간을 연다."""
    spans: list[dict] = []
    current = None
    for tag, (start, end) in zip(tags, offsets):
        if start == end or tag in (IGNORE_INDEX, _TAG_O):
            current = None
            continue
        boundary, span_type = L.SPAN_TAGS[tag].split("-", 1)
        if boundary == "I" and current is not None and current["type"] == span_type:
            current["end"] = end
            continue
        current = {"start": start, "end": end, "type": span_type}
        spans.append(current)
    return spans


def _single(head: L.LabelSet, logits: torch.Tensor) -> str | None:
    label = head.classes[int(logits[0].argmax(-1))]
    return None if label == L.UNDECIDED else label


def _positives(name: str, logits: torch.Tensor) -> list[str]:
    options = L.MULTI_LABEL_HEADS[name]
    return [opt for opt, on in zip(options, (logits[0] > 0).tolist()) if on]


def decode(text: str, logits: dict[str, torch.Tensor], offsets: list[tuple[int, int]]) -> dict:
    logits = {k: v.float().cpu() for k, v in logits.items()}

    ktas_level = int(L.KTAS.classes[int(logits[L.KTAS.name][0].argmax(-1))])

    minor_idx = int(masked_minor(logits[L.CC_MINOR.name], logits[L.CC_MAJOR.name])[0])
    minor_label = L.CC_MINOR.classes[minor_idx]
    if minor_label == L.UNDECIDED:
        chief_complaint = {"major": None, "minor": None}
    else:
        major, minor = minor_label.split("|", 1)
        chief_complaint = {"major": major, "minor": minor}

    sex = _single(L.SEX, logits[L.SEX.name])
    avpu = _single(L.AVPU, logits[L.AVPU.name])
    med_status = L.MED_STATUS.classes[int(logits[L.MED_STATUS.name][0].argmax(-1))]

    primary_type = _single(L.PRIMARY_INCIDENT, logits[L.PRIMARY_INCIDENT.name])
    incident_types = set(_positives("incidents", logits["incidents"])) | ({primary_type} if primary_type else set())
    incident_detail = {}
    for item in _positives("incident_detail", logits["incident_detail"]):
        t, d = item.split("/", 1)
        incident_detail.setdefault(t, []).append(d)
    incidents = [
        {"type": t, "detail": (incident_detail.get(t) or [None])[0], "primary": t == primary_type}
        for t in sorted(incident_types, key=lambda t: t != primary_type)
    ]
    disease_category = _single(L.DISEASE, logits[L.DISEASE.name]) if "질병" in incident_types else None

    treat_detail = {}
    for item in _positives("treatment_detail", logits["treatment_detail"]):
        cat, d = item.split("/", 1)
        treat_detail.setdefault(cat, []).append(d)
    treatments = []
    for item in _positives("treatment", logits["treatment"]):
        cat, status = item.split("/", 1)
        treatments.append({"category": cat, "status": status, "detail": (treat_detail.get(cat) or [None])[0]})

    symptoms = []
    for item in _positives("symptoms", logits["symptoms"]):
        name, status = item.rsplit("/", 1)
        symptoms.append({"standard_name": name, "status": status})

    injury_side = {}
    for item in _positives("injury_side", logits["injury_side"]):
        region, side = item.split("/", 1)
        injury_side[region] = side
    injuries = []
    for item in _positives("injury", logits["injury"]):
        region, itype = item.split("/", 1)
        injuries.append({"region": region, "type": itype, "side": injury_side.get(region), "status": "확인"})

    tags = logits[SPAN_HEAD][0].argmax(-1).tolist()
    spans = decode_spans(tags, offsets)
    by_type: dict[str, list[str]] = {t: [] for t in L.SPAN_TYPES}
    for s in spans:
        by_type[s["type"]].append(text[s["start"] : s["end"]])

    vitals = []
    for span_text in by_type["VITALS"]:
        values = parse_vitals(span_text)
        if any(v is not None for v in values.values()):
            vitals.append({"sequence": len(vitals) + 1, **values, "evidence": [span_text]})

    age_text = " ".join(by_type["AGE"])
    age = {**parse_age(age_text), "evidence": by_type["AGE"]} if age_text else {"years": None, "months": None, "band": None, "evidence": []}

    onset_text = by_type["ONSET"][0] if by_type["ONSET"] else None
    onset = {"text": onset_text, "minutes_ago": parse_onset(onset_text) if onset_text else None}

    suspected_diagnosis = [{"text": t} for t in by_type["DX"]]
    medications = {"status": med_status, "items": [{"text": t} for t in by_type["MED"]]}

    return {
        "call_type": None,
        "ktas_level": ktas_level,
        "ktas_evidence": None,
        "chief_complaint": chief_complaint,
        "suspected_diagnosis": suspected_diagnosis,
        "vitals": vitals,
        "consciousness": [{"sequence": 1, "avpu": avpu}] if avpu else [],
        "symptoms": symptoms,
        "onset": onset,
        "incidents": incidents,
        "disease_category": disease_category,
        "injuries": injuries,
        "treatments": treatments,
        "age": age,
        "sex": sex,
        "medications": medications,
        "notes": None,
        "meta": {"not_predicted": ["call_type", "ktas_evidence", "notes"]},
    }
