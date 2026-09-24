"""규칙 조립기 — 필드별 예측에서 6개 출력 필드를 만든다. HANDMADE-MODEL src/handmade_model/assemble.py에서 가져왔다.

AI가 아니라 규칙이다. 학습 정답을 만들 때도 같은 규칙을 썼으므로, 여기를 바꾸면 모델이 배운 것과
실제 출력이 어긋난다.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import labels as L

_DEPARTMENT_MAPPING_PATH = Path(__file__).resolve().parent / "department_mapping.json"


def load_department_mapping() -> dict:
    return json.loads(_DEPARTMENT_MAPPING_PATH.read_text(encoding="utf-8"))


def assemble_mechanism(
    cause: str | None, cause_type: str | None, body_part: str | None, representative_symptom: str | None
) -> str:
    """판단 보류(cause가 None)면 빈 문자열. 외상/비외상성 손상이면 부위를, 질병이면 대표
    증상을 뒤 칸으로 붙인다. 뒤 칸이 없으면 원인만 낸다.
    """
    if not cause:
        return ""
    if cause_type in (L.TRAUMA, L.NON_TRAUMATIC_INJURY):
        return f"{cause} · {body_part}" if body_part else cause
    if cause_type == L.DISEASE:
        return f"{cause} · {representative_symptom}" if representative_symptom else cause
    return cause


def assemble_patient(age_band: str | None, sex: str | None) -> str:
    """아는 것만 쓴다."""
    parts = [p for p in (age_band, sex) if p]
    return " ".join(parts)


def assemble_symptoms(mentions: list[dict]) -> list[str]:
    """증상 언급 중 present=True인 것만, 원문 등장 순서로, standard_name 기준 중복 제거."""
    seen: set[str] = set()
    out: list[str] = []
    for m in sorted((m for m in mentions if m.get("present")), key=lambda m: m["start"]):
        name = m["standard_name"]
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def assemble_required_department(
    cause: str | None, cause_type: str | None, body_part: str | None, mapping: dict | None = None
) -> str | None:
    """원인·부위 → 심평원 전문과목 대응표(department_mapping.json)로 도출한다 (모델이 아니라 규칙).

    응급의학과는 모든 환자가 거쳐 정보가 없으므로 대응표에 넣지 않았다 — 대응이 없으면 None.
    """
    if not cause:
        return None
    mapping = mapping or load_department_mapping()
    if cause in mapping["body_part_overrides_cause_for"] and body_part:
        dept = mapping["body_part_department"].get(body_part)
        if dept:
            return dept
    return mapping["cause_department"].get(cause)


def assemble_output(
    cause: str | None,
    cause_type: str | None,
    body_part: str | None,
    representative_symptom: str | None,
    age_band: str | None,
    sex: str | None,
    severity_tag: str,
    treatment: list[str],
    symptom_mentions: list[dict],
    mapping: dict | None = None,
) -> dict:
    """6개 필드 전부를 조립한다 — schema.py Summary와 같은 모양."""
    return {
        "patient": assemble_patient(age_band, sex),
        "mechanism": assemble_mechanism(cause, cause_type, body_part, representative_symptom),
        "symptoms": assemble_symptoms(symptom_mentions),
        "treatment": list(treatment),
        "severity_tag": severity_tag,
        "required_department": assemble_required_department(cause, cause_type, body_part, mapping),
    }
