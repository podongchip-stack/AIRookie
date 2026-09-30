"""feature/voice의 v2 스키마(MF_BERT 17필드) → hub가 쓰는 요약 필드로 변환한다 (2026-10-01, 규칙 기반).

voice는 2026-09-29에 구조화 모델을 HMM에서 MF_BERT로 바꾸면서 summary를 v2 스키마로 바꿨다
(`ktas_level`, `chief_complaint`, `incidents`, `injuries`, `vitals` …). hub의 매칭·표시는 예전 필드
(`mechanism`·`severity_tag`·`symptoms`·`treatment`·`patient`·`required_department`)를 쓰므로 여기서 한
번 옮긴다. 예전 형식도 그대로 받는다(schema.VoiceSummary가 v2일 때만 이 함수를 부른다).

필요 진료과(required_department)는 예전 voice/hmm/department_mapping.json을 그대로 옮긴 표로 도출한다.
MF_BERT의 `disease_category`·`incidents[].type`·`injuries[].region` 어휘가 그 표의 입력과 같다.
⚠ 표는 **팀 확인 전 초안**이다(원본 _source 참고). 특히 뇌혈관질환(뇌경색=신경과 / 뇌출혈=신경외과)과
소화기질환(수술=외과 / 내시경=내과)은 기본값을 하나로 정해 둔 것이라 확정이 필요하다.

자체 검사: python voice_v2.py
"""
from __future__ import annotations

# ── 필요 진료과 대응표 (voice/hmm/department_mapping.json, 팀 확인 전 초안) ──────────
CAUSE_DEPARTMENT: dict[str, str | None] = {
    "심장질환": "내과", "뇌혈관질환": "신경과", "대동맥질환": "심장혈관흉부외과", "소화기질환": "외과",
    "산과·부인과": "산부인과", "신장질환": "내과", "정신과적 응급": "정신건강의학과", "호흡기질환": "내과",
    "신경계질환": "신경과", "대사·내분비": "내과", "감염·발열": "내과", "기타 질병": None,
    "화상": "성형외과", "중독": "내과", "연기흡입": "내과", "화학물질": None, "동물/곤충": None,
    "온열손상": None, "한랭손상": None, "성폭행": "산부인과", "호흡위험": None, "상해": None, "기타 손상": None,
}
BODY_PART_DEPARTMENT: dict[str, str] = {
    "머리": "신경외과", "얼굴": "성형외과", "목": "신경외과", "가슴": "심장혈관흉부외과", "배": "외과",
    "등·허리": "정형외과", "골반": "정형외과", "팔": "정형외과", "다리": "정형외과", "다발성": "외과",
}
#: 외상이면 다친 부위를 원인보다 먼저 본다(예: 교통사고 + 다리 골절 → 정형외과).
BODY_PART_OVERRIDES_CAUSE_FOR = frozenset({"교통사고", "낙상", "추락", "그 밖의 둔상", "관통상", "기계", "농기계", "상해", "기타 손상"})

#: KTAS 1~2 = 소생·긴급, 3 = 응급, 4~5 = 준응급·비응급. hub의 3단계 중증도로 줄인다.
KTAS_TO_SEVERITY = {1: "high", 2: "high", 3: "medium", 4: "low", 5: "low"}

AVPU_LABEL = {"A": "명료(A)", "V": "음성 반응(V)", "P": "통증 반응(P)", "U": "무반응(U)"}


def is_v2(summary: dict) -> bool:
    """v2 원본인지. 이미 변환된 요약(상태 복구 등)에도 ktas_level 키가 있으므로 mechanism 유무로 가른다."""
    return isinstance(summary, dict) and "ktas_level" in summary and "mechanism" not in summary


def _primary_incident(summary: dict) -> dict | None:
    incidents = summary.get("incidents") or []
    return next((i for i in incidents if i.get("primary")), incidents[0] if incidents else None)


def required_department(summary: dict) -> str | None:
    """원인·부위 → 심평원 전문과목(대응표). 대응이 없으면 None — hub는 임베딩 매칭으로 넘어간다."""
    primary = _primary_incident(summary)
    cause = primary.get("type") if primary else None
    regions = [i.get("region") for i in summary.get("injuries") or [] if i.get("region")]
    if regions and (cause is None or cause in BODY_PART_OVERRIDES_CAUSE_FOR):
        region = regions[0] if len(set(regions)) == 1 else "다발성"
        return BODY_PART_DEPARTMENT.get(region)
    if cause == "질병":
        cause = summary.get("disease_category")
    return CAUSE_DEPARTMENT.get(cause) if cause else None


def _patient(summary: dict) -> str:
    age = summary.get("age") or {}
    if age.get("years") is not None:
        age_text = f"{age['years']}세"
    elif age.get("months") is not None:
        age_text = f"{age['months']}개월"
    else:
        age_text = age.get("band") or ""
    return " ".join(p for p in (age_text, summary.get("sex") or "") if p) or "정보 없음"


def _mechanism(summary: dict) -> str:
    """예상 병명·기전 한 줄. hub가 진료과·질환군 임베딩 매칭의 입력으로 쓴다."""
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
    parts += [
        " ".join(p for p in (i.get("side"), i.get("region"), i.get("type")) if p)
        for i in summary.get("injuries") or []
    ]
    seen: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    return " · ".join(seen) or (summary.get("chief_complaint") or {}).get("major") or "미상"


def normalize(summary: dict) -> dict:
    """v2 summary → hub VoiceSummary 필드(예전 6필드 + 표시용 추가 필드)."""
    ktas = summary.get("ktas_level")
    consciousness = summary.get("consciousness") or []
    avpu = consciousness[-1].get("avpu") if consciousness else None
    onset = summary.get("onset") or {}
    return {
        "patient": _patient(summary),
        "mechanism": _mechanism(summary),
        "symptoms": [s["standard_name"] for s in summary.get("symptoms") or [] if s.get("status") == "확인"],
        "treatment": [
            (f"{t['category']}({t['detail']})" if t.get("detail") else t["category"])
            + ("" if t.get("status") in (None, "시행") else f" {t['status']}")
            for t in summary.get("treatments") or []
        ],
        "severity_tag": KTAS_TO_SEVERITY.get(ktas, "medium"),
        "required_department": required_department(summary),
        "ktas_level": ktas,
        "vitals": [
            {k: v for k, v in vital.items() if k != "evidence"} for vital in summary.get("vitals") or []
        ],
        "consciousness": AVPU_LABEL.get(avpu, avpu) if avpu else None,
        "onset": onset.get("text"),
        "chief_complaint": " / ".join(
            p for p in ((summary.get("chief_complaint") or {}).get(k) for k in ("major", "minor")) if p
        ) or None,
    }


def _selftest() -> None:
    cardiac = {  # CLAUDE.md 1번 포맷 예시
        "ktas_level": 2, "chief_complaint": {"major": "I 심혈관계", "minor": "흉통(심장성)"},
        "suspected_diagnosis": [{"text": "경색 의심"}],
        "vitals": [{"sequence": 1, "sbp": 150, "dbp": 90, "hr": 110, "rr": None, "bt": None, "spo2": 96,
                    "glucose": None, "evidence": ["혈압 150에 90"]}],
        "consciousness": [{"sequence": 1, "avpu": "A"}], "symptoms": [{"standard_name": "흉통", "status": "확인"},
                                                                     {"standard_name": "두통", "status": "부정"}],
        "onset": {"text": "30분 전부터", "minutes_ago": 30}, "incidents": [{"type": "질병", "detail": None, "primary": True}],
        "disease_category": "심장질환", "injuries": [], "treatments": [{"category": "ECG", "status": "시행", "detail": None}],
        "age": {"years": 62, "months": None, "band": None}, "sex": "남성",
    }
    out = normalize(cardiac)
    assert out["severity_tag"] == "high" and out["required_department"] == "내과"
    assert out["patient"] == "62세 남성" and out["symptoms"] == ["흉통"] and out["treatment"] == ["ECG"]
    assert out["mechanism"] == "심장질환 · 흉통(심장성) · 경색 의심", out["mechanism"]
    assert out["vitals"][0]["sbp"] == 150 and "evidence" not in out["vitals"][0] and out["consciousness"] == "명료(A)"

    trauma = {"ktas_level": 3, "incidents": [{"type": "교통사고", "detail": "보행자", "primary": True}],
              "injuries": [{"region": "다리", "type": "골절", "side": "좌"}], "age": {"band": "70대"}, "sex": "여성"}
    out = normalize(trauma)
    assert out["required_department"] == "정형외과" and out["severity_tag"] == "medium"
    assert out["mechanism"] == "교통사고(보행자) · 좌 다리 골절" and out["patient"] == "70대 여성"
    multi = {**trauma, "injuries": [{"region": "머리"}, {"region": "배"}]}
    assert required_department(multi) == "외과", "여러 부위면 다발성 → 외과"
    assert required_department({"ktas_level": 5, "incidents": [{"type": "기타 손상", "primary": True}]}) is None
    assert normalize({"ktas_level": 4})["mechanism"] == "미상", "비어 있어도 깨지지 않는다"
    assert not is_v2(normalize(cardiac)), "변환된 요약을 다시 v2로 보면 안 된다(상태 복구)"
    print("voice_v2 자체 검사 통과")


if __name__ == "__main__":
    _selftest()
