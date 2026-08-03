"""LLM 없이 도는 구현 — 개발·테스트용.

GPU도 Ollama도 없는 장비에서 추출 로직 전체를 돌려볼 수 있게 한다.

⚠️ **프로덕션용이 아니다.** 여기 있는 것은 정규식 몇 개일 뿐이고, 서류 양식이
조금만 달라도 아무것도 못 찾는다. 실제 추출은 `ollama.py`가 한다.

그런데도 "고정 응답"이 아니라 원문을 실제로 훑게 만든 이유가 있다. 고정 응답을
돌려주면 `grounding.py`의 근거 대조가 항상 실패하거나 항상 성공해서, 정작 검증하고
싶은 로직이 검증되지 않는다. 원문에서 실제로 문자열을 떼어 오면 근거 대조·값 대조·
영역 추적이 모두 진짜로 동작한다.

`hallucinate=True`로 쓰면 일부러 원문에 없는 값을 섞는다. 환각 필터가 실제로 값을
걸러내는지 확인하는 용도다.
"""

from __future__ import annotations

import re

from .. import grounding, prompts

#: 원문에서 찾아볼 진료과 이름. 긴 이름을 앞에 둬야 "흉부외과"를 "외과"로
#: 잘못 잡지 않는다
_DEPARTMENTS = (
    "소아청소년과",
    "응급의학과",
    "순환기내과",
    "흉부외과",
    "신경외과",
    "정형외과",
    "일반외과",
    "산부인과",
    "신경과",
    "외과",
    "내과",
)

#: 역량 코드별 원문 표현. `grounding.py`의 것을 그대로 쓴다 — 표를 두 벌 두면
#: 한쪽만 고쳤을 때 stub은 찾는데 검증은 거르는(또는 그 반대) 상태가 된다
_CAPABILITY_KEYWORDS = grounding.CAPABILITY_EVIDENCE_TERMS

_NIGHT_DUTY_YES = ("당직", "야간", "24시간")
_NIGHT_DUTY_NO = ("야간 진료 없음", "야간진료 없음", "주간만")

_DOCUMENT_TYPE_HINTS = (
    ("DUTY_ROSTER", ("당직표", "당직 편성", "당직편성")),
    ("BED_STATUS", ("병상 현황", "병상현황", "병상 운영")),
    ("EQUIPMENT_STATUS", ("장비 현황", "장비현황", "시설 현황")),
    ("MEDICAL_CERTIFICATE", ("진단서", "소견서", "진료의뢰서")),
    ("DEPARTMENT_GUIDE", ("진료과", "의료진 안내", "진료안내")),
)


def _line_containing(text: str, needle: str) -> str:
    """`needle`이 들어 있는 줄을 통째로 돌려준다. 근거로 쓰기 위해서다."""
    for line in text.splitlines():
        if needle in line:
            return line.strip()
    return ""


class StubLlmClient:
    """정규식으로 흉내내는 추출기. `LlmClient` Protocol을 만족한다."""

    def __init__(self, hallucinate: bool = False) -> None:
        #: True면 원문에 없는 값을 일부러 섞는다. 환각 필터 검증용
        self._hallucinate = hallucinate

    def describe(self) -> str:
        return "stub-hallucinate" if self._hallucinate else "stub"

    def preload(self) -> None:
        """올릴 모델이 없다. 아무것도 하지 않는다."""

    def complete_json(self, *, system: str, prompt: str, json_schema: dict) -> dict:
        text = _document_text_from(prompt)
        properties = json_schema.get("properties", {})

        if "hospitalName" in properties:
            return self._document(text)
        if "nightDuty" in properties:
            return self._night_duty(text)
        if "specialties" in properties:
            return self._specialties(text)
        if "capabilities" in properties:
            return self._capabilities(text)
        raise ValueError(f"stub이 모르는 스키마다: {sorted(properties)}")

    # --- 그룹별 흉내 --------------------------------------------------------

    def _document(self, text: str) -> dict:
        match = re.search(r"^.*(병원|의료원|센터).*$", text, re.MULTILINE)
        name_line = match.group(0).strip() if match else ""
        hpid = re.search(r"\b([A-Z]\d{7})\b", text)

        document_type = "OTHER"
        for code, hints in _DOCUMENT_TYPE_HINTS:
            if any(hint in text for hint in hints):
                document_type = code
                break

        # "2026년 8월" / "2026-08-01" / "2026.08.01"
        date = ""
        date_evidence = ""
        ymd = re.search(r"(20\d{2})[.\-년]\s*(\d{1,2})[.\-월]\s*(\d{1,2})", text)
        ym = re.search(r"(20\d{2})[.\-년]\s*(\d{1,2})\s*월", text)
        if ymd:
            date = f"{ymd.group(1)}-{int(ymd.group(2)):02d}-{int(ymd.group(3)):02d}"
            date_evidence = _line_containing(text, ymd.group(0))
        elif ym:
            date = f"{ym.group(1)}-{int(ym.group(2)):02d}"
            date_evidence = _line_containing(text, ym.group(0))

        return {
            "hospitalName": name_line[:40],
            "hospitalNameEvidence": name_line,
            "hospitalId": hpid.group(1) if hpid else "",
            "hospitalIdEvidence": _line_containing(text, hpid.group(1)) if hpid else "",
            "documentType": document_type,
            "effectiveDate": date,
            "effectiveDateEvidence": date_evidence,
        }

    def _night_duty(self, text: str) -> dict:
        for keyword in _NIGHT_DUTY_NO:
            if keyword in text:
                return {"nightDuty": "N", "evidence": _line_containing(text, keyword)}
        for keyword in _NIGHT_DUTY_YES:
            if keyword in text:
                return {"nightDuty": "Y", "evidence": _line_containing(text, keyword)}
        return {"nightDuty": "UNKNOWN", "evidence": ""}

    def _specialties(self, text: str) -> dict:
        found: list[dict] = []
        taken: list[str] = []
        for department in _DEPARTMENTS:
            if department not in text:
                continue
            # 이미 잡은 과의 부분 문자열이면 건너뛴다 ("외과"가 "흉부외과"에 걸리는 경우)
            if any(department in longer for longer in taken):
                continue
            taken.append(department)
            line = _line_containing(text, department)
            count = re.search(r"(\d+)\s*명", line)
            found.append({
                "department": department,
                "doctorCount": int(count.group(1)) if count else -1,
                "procedureTags": [],
                "onDuty": "Y" if "당직" in line else "UNKNOWN",
                "evidence": line,
            })

        if self._hallucinate:
            # 원문에 없는 과와 근거를 섞는다. grounding이 이걸 걸러내야 한다
            found.append({
                "department": "지어낸과",
                "doctorCount": 99,
                "procedureTags": ["존재하지 않는 시술"],
                "onDuty": "Y",
                "evidence": "이 문장은 원문에 존재하지 않는다",
            })
        return {"specialties": found}

    def _capabilities(self, text: str) -> dict:
        capabilities = []
        equipment = []
        for code, keywords in _CAPABILITY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    line = _line_containing(text, keyword)
                    capabilities.append({"code": code, "evidence": line})
                    equipment.append({"name": keyword, "evidence": line})
                    break

        if self._hallucinate:
            # 근거는 원문에 실재하지만 그 역량과는 무관한 경우.
            # 근거 대조만으로는 못 잡고 capability_supported_by()가 잡아야 한다
            first_line = text.splitlines()[0].strip() if text.splitlines() else ""
            capabilities.append({"code": "PROC_CRANIOTOMY", "evidence": first_line})

        return {"capabilities": capabilities, "equipment": equipment}


def _document_text_from(prompt: str) -> str:
    """프롬프트에서 원문 부분만 떼어낸다.

    실제 LLM은 프롬프트 전체를 보지만 stub은 지시문을 읽을 수 없으므로 원문만
    필요하다. 구분선은 `prompts.py`가 정의한 것을 그대로 쓴다.
    """
    start = prompt.find(prompts.DOCUMENT_START)
    end = prompt.rfind(prompts.DOCUMENT_END)
    if start == -1 or end == -1:
        return prompt
    return prompt[start + len(prompts.DOCUMENT_START) : end].strip()
