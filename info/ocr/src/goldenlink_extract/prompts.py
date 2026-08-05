"""필드 그룹 정의 — 무엇을 어떤 형식으로 물어볼 것인가.

왜 한 번에 다 뽑지 않는가
-------------------------
서류 한 장을 주고 "필드 전부 뽑아줘"라고 하면 세 가지가 나빠진다.

1. 출력이 길어질수록 뒷부분에서 환각이 는다. 앞에서 만든 문맥에 스스로 끌려간다.
2. 한 항목이 틀려도 전체를 다시 부를 수밖에 없다. 그룹별이면 실패한 것만 재시도한다.
3. 어느 단계가 틀렸는지 분리가 안 돼 프롬프트를 고칠 근거가 안 남는다.

그래서 아래 4개 그룹으로 쪼개 각각 따로 호출한다. 문서 1장당 LLM 호출 4회다.
장비와 역량은 서류의 같은 구역에서 나오므로 한 번에 묻는다.

미상을 어떻게 표현하는가
------------------------
JSON Schema에서 nullable(`["string", "null"]`)을 쓰지 않고 **센티널 값**을 쓴다.
Ollama의 구조화 출력은 스키마를 문법(grammar)으로 바꿔 디코딩을 제약하는데,
union 타입 처리는 구현에 따라 편차가 있다. 형식이 흔들리면 파싱이 아니라 **디코딩**
단계에서 깨지므로 재시도로도 못 고친다. 확실한 단일 타입만 쓰고 파이썬에서 None으로
바꾸는 편이 안전하다.

    문자열  ""                  -> 미상
    정수    -1                  -> 미상 (config.MISSING_SENTINEL, E-Gen 규약과 동일)
    3상태   "Y"/"N"/"UNKNOWN"   -> True / False / None

역량 코드와 서류 종류만은 `enum`으로 제약한다. 이건 union이 아니라 값 목록이라
문법 변환이 확실하고, 어휘 밖 값이 **물리적으로 생성될 수 없게** 만드는 가장
강한 수단이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .vocabulary import (
    CAPABILITY_CODES,
    DOCUMENT_TYPE_LABELS_KO,
    DOCUMENT_TYPES,
    label_ko,
)

#: 모든 그룹에 공통으로 붙는 지시. 환각 억제가 유일한 목적이다.
SYSTEM_PROMPT = """당신은 한국 병원이 발급한 서류에서 정해진 항목만 뽑아내는 추출기다.

절대 규칙:
1. 원문에 적혀 있지 않은 것은 절대 만들어내지 않는다. 모르면 미상 값을 쓴다.
2. 추론하지 않는다. "응급의료센터니까 CT가 있을 것" 같은 판단은 금지다.
   원문에 그렇게 적혀 있을 때만 값을 넣는다.
3. evidence 에는 근거가 된 원문을 **그대로 복사**한다. 요약·의역·교정 금지다.
   원문에 오탈자가 있으면 오탈자까지 그대로 옮긴다.
   - 이 지시문에 적힌 코드나 한글 설명("CT 24시간 가동" 등)을 근거로 쓰지 마라.
     근거는 반드시 아래 서류 원문에서 가져온다.
   - "문서에 명시됨", "~로 추론됨" 같은 네 설명은 근거가 아니다.
   - 원문에서 **이어져 있는 한 부분**만 옮긴다. 떨어진 줄을 이어붙이지 마라.
4. 값을 넣을지 말지 애매하면 넣지 않는다. 빠뜨리는 것보다 지어내는 것이 훨씬 나쁘다.

원문은 OCR 결과라 글자가 깨지거나 띄어쓰기가 어긋나 있을 수 있다.
읽히지 않는 부분은 무리해서 복원하지 말고 미상으로 둔다."""


@dataclass(frozen=True)
class FieldGroup:
    """LLM 호출 1회 단위."""

    key: str
    label: str
    #: Ollama의 `format` 파라미터로 그대로 넘어가는 JSON Schema
    schema: dict
    #: 사용자 프롬프트에서 원문 앞에 붙는 지시문
    instruction: str


def _capability_catalog() -> str:
    """역량 코드 목록을 프롬프트에 넣을 형태로 만든다.

    코드만 주면 모델이 뜻을 짐작해야 한다. 한글 라벨을 함께 줘야 서류의 한국어
    표현과 이어붙일 수 있다. 라벨은 `vocabulary.py`의 것을 그대로 쓴다 —
    어휘가 한 군데에서만 정의되도록.
    """
    return "\n".join(f"- {code}: {label_ko(code)}" for code in sorted(CAPABILITY_CODES))


def _document_type_catalog() -> str:
    return "\n".join(
        f"- {code}: {DOCUMENT_TYPE_LABELS_KO[code]}" for code in sorted(DOCUMENT_TYPES)
    )


DOCUMENT = FieldGroup(
    key="document",
    label="서류 기본정보",
    schema={
        "type": "object",
        # 값마다 근거를 따로 받는다. 기관명은 머리글에, 기준일자는 표 위에 적히는
        # 식으로 서류의 서로 다른 곳에서 나오기 때문이다. 근거 하나를 공유하면
        # 어느 한쪽은 반드시 대조에 실패한다
        "properties": {
            "hospitalName": {"type": "string"},
            "hospitalNameEvidence": {"type": "string"},
            "hospitalId": {"type": "string"},
            "hospitalIdEvidence": {"type": "string"},
            "documentType": {"type": "string", "enum": sorted(DOCUMENT_TYPES)},
            "effectiveDate": {"type": "string"},
            "effectiveDateEvidence": {"type": "string"},
        },
        "required": [
            "hospitalName", "hospitalNameEvidence",
            "hospitalId", "hospitalIdEvidence",
            "documentType",
            "effectiveDate", "effectiveDateEvidence",
        ],
    },
    instruction=f"""이 서류가 어느 병원의 무슨 서류이고 언제 기준인지 찾아라.

- hospitalName: 기관명. 예) "○○대학교병원". 없으면 빈 문자열
- hospitalNameEvidence: 기관명이 적힌 원문 줄을 그대로 복사

- hospitalId: 기관코드(hpid). 영문 1자 + 숫자 7자리 형태다.
  서류에 인쇄된 경우가 드물다. 없으면 빈 문자열. 추측 금지.
- hospitalIdEvidence: 기관코드가 적힌 원문 줄. 없으면 빈 문자열

- documentType: 아래 중 하나
{_document_type_catalog()}

- effectiveDate: 이 서류가 언제 기준인지. "2026-08" 또는 "2026-08-01" 형식.
  발급일·작성일·"○○년 ○월 당직표" 같은 표기에서 찾는다. 없으면 빈 문자열.
  **오늘 날짜를 넣지 마라.** 서류에 적힌 날짜만 쓴다.
- effectiveDateEvidence: 그 날짜가 적힌 원문 줄을 그대로 복사.
  기관명이 적힌 줄이 아니라 **날짜가 있는 줄**이어야 한다

각 evidence는 해당 값이 실제로 있는 줄이어야 한다. 서로 다른 줄이어도 된다.

주의: 진료의뢰서·소견서에는 보내는 병원과 받는 병원이 함께 적힐 수 있다.
이 서류를 **발급한** 쪽(직인·발급기관)을 골라라.""",
)


NIGHT_DUTY = FieldGroup(
    key="night_duty",
    label="야간 당직",
    schema={
        "type": "object",
        "properties": {
            "nightDuty": {"type": "string", "enum": ["Y", "N", "UNKNOWN"]},
            "evidence": {"type": "string"},
        },
        "required": ["nightDuty", "evidence"],
    },
    instruction="""이 서류에 야간 당직 전문의에 대한 내용이 있는지 확인하라.

- nightDuty:
  - "Y"  : 야간/당직 근무하는 전문의가 있다고 적혀 있다
           (당직표, "24시간 전문의 상주", "야간 당직: ○○○" 등)
  - "N"  : 야간에 없다고 명시돼 있다 ("야간 진료 없음", "주간만 운영" 등)
  - "UNKNOWN" : 당직에 대한 언급이 아예 없다
- evidence: 판단 근거가 된 원문을 그대로 복사. UNKNOWN이면 빈 문자열

주의: 병원 전화번호나 응급실 존재만으로 "Y"를 넣지 마라.
당직·야간·24시간 근무가 글로 적혀 있어야 한다.""",
)


SPECIALTIES = FieldGroup(
    key="specialties",
    label="진료과·인력",
    schema={
        "type": "object",
        "properties": {
            "specialties": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "department": {"type": "string"},
                        "doctorCount": {"type": "integer"},
                        "procedureTags": {"type": "array", "items": {"type": "string"}},
                        "onDuty": {"type": "string", "enum": ["Y", "N", "UNKNOWN"]},
                        "evidence": {"type": "string"},
                    },
                    "required": [
                        "department", "doctorCount", "procedureTags", "onDuty", "evidence",
                    ],
                },
            }
        },
        "required": ["specialties"],
    },
    instruction="""이 서류에 적힌 진료과와 그 과의 의사 인원을 모두 찾아라.

각 항목마다:
- department: 진료과명을 원문 표기 그대로. 예) "흉부외과", "순환기내과"
- doctorCount: 그 과의 의사 수. **서류에 숫자가 적혀 있을 때만** 넣어라.
  적혀 있지 않으면 -1 을 넣는다. 이름이 나열돼 있으면 세어서 넣어도 된다.
- procedureTags: 그 과와 함께 적힌 시술·전문분야 표현을 원문 그대로. 없으면 빈 배열
- onDuty: 이 과가 당직 편성에 올라 있으면 "Y", 당직 아님이 명시돼 있으면 "N",
  당직 얘기가 없으면 "UNKNOWN"
- evidence: 이 항목의 근거가 된 원문 줄을 그대로 복사

진료과 언급이 전혀 없으면 빈 배열을 반환하라.
같은 과가 여러 번 나오면 하나로 합쳐라.""",
)


CAPABILITIES = FieldGroup(
    key="capabilities",
    label="시술·장비",
    schema={
        "type": "object",
        "properties": {
            "capabilities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "enum": sorted(CAPABILITY_CODES)},
                        "evidence": {"type": "string"},
                    },
                    "required": ["code", "evidence"],
                },
            },
            "equipment": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["name", "evidence"],
                },
            },
        },
        "required": ["capabilities", "equipment"],
    },
    instruction=f"""이 서류에 적힌 시술·장비를 두 가지로 나눠 답하라.

【1】 capabilities — 아래 표준 목록에 해당하는 것만

{_capability_catalog()}

- code: 위 목록의 코드를 그대로
- evidence: 그렇게 판단한 근거가 된 원문을 그대로 복사

엄격히 지킬 것:
- 목록에 없는 역량은 여기 넣지 마라. 아래 【2】로 보내라.
- 진료과가 있다는 것만으로 그 과의 시술이 가능하다고 넣지 마라.
  "신경외과가 있다" != "개두술이 가능하다". 시술·장비가 직접 언급돼야 한다.
- 해당하는 것이 하나도 없으면 빈 배열. 빈 배열은 정상적인 답이다.

【2】 equipment — 서류에 적힌 장비·시설 이름을 원문 그대로

- name: 원문 표기 그대로. 예) "MRI 3.0T", "고압산소치료실", "인공심폐기"
- evidence: 그 이름이 적힌 원문 줄을 그대로 복사

표준 목록에 없다고 버리지 않는다. 지금은 코드로 못 바꾸더라도 나중에 어휘가
넓어질 때 근거가 된다. 【1】에 이미 넣은 것도 원문 표기가 있으면 여기 함께 적어라.""",
)


#: 실행 순서대로. 순서 자체에 의미는 없지만 로그를 읽을 때 일정한 편이 낫다
FIELD_GROUPS: tuple[FieldGroup, ...] = (DOCUMENT, NIGHT_DUTY, SPECIALTIES, CAPABILITIES)

#: 원문 구분선. stub 구현이 프롬프트에서 원문만 떼어낼 때도 쓴다
DOCUMENT_START = "--- 서류 원문 시작 ---"
DOCUMENT_END = "--- 서류 원문 끝 ---"


def build_user_prompt(group: FieldGroup, document_text: str) -> str:
    """그룹 지시문 + 원문으로 사용자 프롬프트를 만든다.

    원문을 뒤에 두는 이유: 지시문이 앞에 있어야 프롬프트 캐시가 그룹 단위로
    재사용되고, 긴 원문에 지시가 묻히지 않는다.
    """
    return f"""{group.instruction}

{DOCUMENT_START}
{document_text}
{DOCUMENT_END}"""
