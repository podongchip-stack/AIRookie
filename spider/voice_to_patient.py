"""voice v2 통화 요약(MF_BERT 17필드) → 거미줄 환자 입력 {k, cond, text}.

spider는 hub와 연결되지 않은 실험 폴더라 hub 모듈을 import 하지 않는다. 규칙은 hub/disease_group.py(키워드)와
hub/voice_v2.py(예상 병명 조립)를 참고해 여기 필요한 4개 질환군만 다시 적었다 — 한쪽을 고치면 다른 쪽도 맞출 것.
map.html의 JS(`voiceToPatient`)와 같은 규칙이다.

규칙 기반(source: "rule"). 질환군 판정 우선순위: 뇌졸중 → 심근경색 → 중증외상 → 일반.
  - 뇌졸중: 뇌졸중·뇌경색·뇌출혈·편마비·구음장애·거미막하/지주막하·두개내 출혈·경막하/외 출혈 (예상 병명 문장에서)
  - 심근경색: 심근경색·급성 관상·STEMI·흉통(심장성)·경색  (뇌경색은 위에서 먼저 잡힌다)
  - 중증외상: 주 사고가 질병이 아닌 외상 기전이고 KTAS 1·2  (외상이라도 경증이면 일반)
실행하면 자체 검사(CLAUDE.md·voice_v2 예시 3건)를 돌린다. API 호출 0회.
"""
from __future__ import annotations

import json
import re
import sys

STROKE = re.compile(r"뇌졸중|뇌\s*경색|뇌출혈|편마비|구음\s*장애|거미막하|지주막하|두개내\s*출혈|경막[하외]\s*(출혈|혈종)")
STEMI = re.compile(r"심근\s*경색|급성\s*관상|STEMI|흉통\(심장성\)|경색")
MAX_INJURIES = 3


def _primary_incident(summary: dict) -> dict | None:
    incs = summary.get("incidents") or []
    return next((i for i in incs if i.get("primary")), incs[0] if incs else None)


def expected_text(summary: dict) -> str:
    """hub/voice_v2._mechanism과 같은 조립: 사고 기전 또는 질병 분류 + 주 호소 + 의심 진단 + 손상."""
    parts: list[str] = []
    primary = _primary_incident(summary)
    if primary and primary.get("type") and primary["type"] != "질병":
        parts.append(f"{primary['type']}({primary['detail']})" if primary.get("detail") else primary["type"])
    elif summary.get("disease_category") and summary["disease_category"] != "기타 질병":
        parts.append(summary["disease_category"])
    minor = (summary.get("chief_complaint") or {}).get("minor")
    if minor:
        parts.append(minor)
    parts += [d["text"] for d in summary.get("suspected_diagnosis") or [] if d.get("text")]
    parts += [" ".join(p for p in (i.get("side"), i.get("region"), i.get("type")) if p)
              for i in (summary.get("injuries") or [])[:MAX_INJURIES]]
    seen: list[str] = []
    for p in (" ".join(str(p).split()) for p in parts):
        if p and p not in seen:
            seen.append(p)
    return " · ".join(seen) or (summary.get("chief_complaint") or {}).get("major") or "미상"


def is_trauma(summary: dict) -> bool:
    primary = _primary_incident(summary)
    return bool(primary and primary.get("type") and primary["type"] != "질병")


def to_patient(summary: dict) -> dict:
    """{'k': KTAS 1~5, 'cond': 'stemi'|'stroke'|'trauma'|'general', 'text': 예상 병명 한 줄, 'source': 'rule'}"""
    if isinstance(summary, dict) and "summary" in summary and isinstance(summary["summary"], dict):
        summary = summary["summary"]  # voice→hub 메시지 전체를 받은 경우
    k = summary.get("ktas_level")
    k = int(k) if k in (1, 2, 3, 4, 5, "1", "2", "3", "4", "5") else 3
    text = expected_text(summary)
    if STROKE.search(text):
        cond = "stroke"
    elif STEMI.search(text):
        cond = "stemi"
    elif is_trauma(summary) and k <= 2:
        cond = "trauma"
    else:
        cond = "general"
    return {"k": k, "cond": cond, "text": text, "source": "rule"}


def _selftest() -> None:
    cardiac = {"ktas_level": 2, "chief_complaint": {"major": "I 심혈관계", "minor": "흉통(심장성)"},
               "suspected_diagnosis": [{"text": "경색 의심"}], "incidents": [{"type": "질병", "primary": True}],
               "disease_category": "심장질환", "injuries": []}
    trauma = {"ktas_level": 1, "incidents": [{"type": "교통사고", "detail": "보행자", "primary": True}],
              "injuries": [{"region": "흉부", "type": "다발성 손상"}], "chief_complaint": {"major": "외상"}}
    mild_fall = {"ktas_level": 4, "incidents": [{"type": "낙상", "primary": True}],
                 "injuries": [{"region": "손목", "type": "골절 의심"}]}
    stroke = {"ktas_level": 2, "disease_category": "뇌혈관질환", "chief_complaint": {"major": "N 신경계", "minor": "편마비"},
              "suspected_diagnosis": [{"text": "뇌경색 의심"}], "incidents": [{"type": "질병", "primary": True}]}
    assert to_patient(cardiac) == {"k": 2, "cond": "stemi", "text": "심장질환 · 흉통(심장성) · 경색 의심", "source": "rule"}
    assert to_patient(trauma)["cond"] == "trauma" and to_patient(trauma)["k"] == 1
    assert to_patient(mild_fall)["cond"] == "general" and to_patient(mild_fall)["k"] == 4
    assert to_patient(stroke)["cond"] == "stroke"  # '경색'이 있어도 뇌경색은 뇌졸중
    assert to_patient({"caseId": "x", "summary": cardiac})["cond"] == "stemi"
    assert to_patient({})["k"] == 3 and to_patient({})["cond"] == "general"
    print("selftest ok")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            print(json.dumps(to_patient(json.load(f)), ensure_ascii=False))
    else:
        _selftest()
