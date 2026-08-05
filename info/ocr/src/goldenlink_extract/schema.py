"""추출 결과의 출력 형식.

`DocumentFields` 는 **서류 1장에서 실제로 읽어낸 것만** 담는다. 병원 1곳의
완성된 정보가 아니다 — 서류에는 좌표도 실시간 병상 수도 없으므로 완성될 수가 없다.

    서류 이미지 ─[goldenlink_ocr]→ 텍스트 ─[goldenlink_extract]→ DocumentFields
                                                                   ↑ 이 파일

있는 것만 넣는다
----------------
모든 필드가 선택 사항이다. 서류에 없으면 키 자체를 넣지 않는다.

`None`(키 없음)과 `0`/`false`/`[]`를 절대 섞지 않는다. 이건 저장소 전체의 규약이다
(`Hospital_inform/README.md`의 "결측 처리 규약"). 서류 맥락에서는 이렇게 갈린다.

| 값 | 뜻 |
|---|---|
| 키 없음 | 서류에서 확인하지 못했다 |
| `[]` | 서류를 읽었고, 해당 항목이 없다고 확인했다 |
| `0` | 서류에 "0"이라고 적혀 있다 |

이 셋이 뭉개지면 나중에 합칠 때 "모르는 값"이 "없는 값"을 덮어쓴다.

서류라서 특별한 것
------------------
공개 API와 달리 서류는 **정적**이다. 그래서 API에는 없는 두 필드를 둔다.

- `documentType` — 무슨 서류인가. 당직표에서 나온 당직 정보와 진단서에서 스쳐
  지나간 당직 언급은 신뢰도가 다르다
- `effectiveDate` — 언제 기준 정보인가. 이게 없으면 3년 전 당직표를 오늘 것으로
  쓰게 된다. 서류 기반 정보에서 가장 위험한 실패다
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .vocabulary import CAPABILITY_CODES, DOCUMENT_TYPES

#: 이 출력 형식의 버전. 나중에 합치는 쪽이 이 값을 보고 읽는 방법을 고른다
SCHEMA_VERSION = "0.1"


class Strict(BaseModel):
    """정의되지 않은 필드를 거부한다.

    오타를 만드는 순간 실패시키는 것이 목적이다. `doctorCount`를 `doctorcount`로
    쓰면 조용히 무시되는 대신 여기서 바로 터진다.
    """

    model_config = ConfigDict(extra="forbid")


class Evidence(Strict):
    """값 하나가 원문 어디에서 나왔는가.

    두 가지 일을 한다.

    1. **환각 판정의 입력** — `sourceText`가 OCR 원문에 실제로 있는지 대조한다.
       LLM은 형식이 완벽한 거짓말을 만들 수 있어서, 형식 검사만으로는 못 잡는다.
    2. **사후 추적** — 값이 이상할 때 원본 이미지의 어느 부분을 다시 볼지 알려준다.

    근거 대조에 실패해 값이 버려진 경우에도 `grounded=False`로 남긴다. 무엇을 왜
    버렸는지 사람이 볼 수 있어야 한다 (지우지 않는다).
    """

    field: str = Field(min_length=1, description="어느 값인가. 예: 'specialties[0].doctorCount'")
    value: str = Field(description="추출된 값의 문자열 표현")
    sourceText: str = Field(description="LLM이 근거로 제시한 원문 조각")
    grounded: bool = Field(description="근거가 OCR 원문에 실제로 존재하는가")
    groundReason: Optional[str] = Field(default=None, description="grounded=False일 때 그 이유")
    regionIndex: Optional[int] = Field(
        default=None, description="OCR 결과의 몇 번째 영역에서 나왔는가"
    )


class Specialty(Strict):
    """진료과 1개.

    `doctorCount=None`은 "서류에 인원이 안 적혀 있다", `0`은 "0명이라고 적혀
    있다"는 뜻이다. 이 둘을 섞으면 정보가 사라진다.
    """

    department: str = Field(min_length=1, description="진료과명. 서류 표기 그대로")
    doctorCount: Optional[int] = Field(
        default=None, ge=0, description="의사 수. None이면 서류에 없음"
    )
    procedureTags: list[str] = Field(
        default_factory=list, description="함께 적힌 시술·전문분야 표현. 원문 그대로"
    )
    onDuty: Optional[bool] = Field(
        default=None, description="당직 편성에 이름이 올라 있는가. None이면 알 수 없음"
    )


class DocumentFields(Strict):
    """서류 1장에서 읽어낸 병원 정보."""

    # --- 어느 병원, 무슨 서류인가 ---
    hospitalName: Optional[str] = Field(default=None, description="서류에 적힌 기관명")
    hospitalId: Optional[str] = Field(
        default=None, description="기관코드(hpid). 서류에 인쇄된 경우에만"
    )
    documentType: Optional[str] = Field(
        default=None, description="서류 종류. vocabulary.DOCUMENT_TYPES 중 하나"
    )
    effectiveDate: Optional[str] = Field(
        default=None, description="이 서류가 언제 기준인가. 'YYYY-MM' 또는 'YYYY-MM-DD'"
    )

    # --- 서류에서 뽑은 값 ---
    nightDutyAvailable: Optional[bool] = Field(
        default=None, description="야간 당직 전문의 존재 여부"
    )
    specialties: Optional[list[Specialty]] = Field(
        default=None, description="진료과 목록. None이면 못 읽음, []면 없다고 확인됨"
    )
    capabilities: Optional[list[str]] = Field(
        default=None, description="표준 역량 코드. vocabulary.CAPABILITY_CODES 어휘만"
    )
    equipment: Optional[list[str]] = Field(
        default=None,
        description="서류에 적힌 장비명 원문. 표준 코드로 못 바꾼 것도 버리지 않고 여기 남긴다",
    )

    # --- 메타 ---
    evidence: list[Evidence] = Field(
        default_factory=list, description="값별 원문 근거. 버려진 값도 남긴다"
    )
    needsReview: bool = Field(default=False, description="사람 확인이 필요한가")
    reviewReasons: list[str] = Field(default_factory=list, description="확인이 필요한 이유")

    documentId: str = Field(min_length=1, description="원본 서류 식별자. 보통 파일명")
    extractedAt: str = Field(description="추출 시각. ISO 8601")
    schemaVersion: str = SCHEMA_VERSION
    #: 이 결과가 AI 산출물임을 명시한다 (CLAUDE.md 핵심 AI 활용 원칙).
    #: 근거 대조·어휘 검증은 규칙 기반이지만, 값을 찾아낸 주체는 LLM이다
    source: Literal["ai"] = "ai"
    modelUsed: dict[str, str] = Field(
        default_factory=dict, description="실제 사용한 모델. 예: {'llm': 'qwen3:14b'}"
    )

    @field_validator("capabilities")
    @classmethod
    def _known_capability_codes(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        """어휘 밖 역량 코드를 막는다.

        LLM 호출은 JSON Schema의 `enum`으로 이미 제약돼 있어 여기까지 잘못된 코드가
        오기 어렵다. 그래도 검사를 두는 이유는, 프롬프트나 스키마를 나중에 고쳐
        제약이 풀렸을 때 **조용히 통과시키지 않기** 위해서다. 잘못된 코드는 에러가
        안 나고 매칭에서만 조용히 빠지므로 더 위험하다.
        """
        if value is None:
            return None
        unknown = sorted(set(value) - CAPABILITY_CODES)
        if unknown:
            raise ValueError(
                f"어휘에 없는 역량 코드: {unknown} (가능한 값: {sorted(CAPABILITY_CODES)})"
            )
        return sorted(set(value))

    @field_validator("documentType")
    @classmethod
    def _known_document_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if value not in DOCUMENT_TYPES:
            raise ValueError(
                f"어휘에 없는 서류 종류: {value!r} (가능한 값: {sorted(DOCUMENT_TYPES)})"
            )
        return value

    @field_validator("effectiveDate")
    @classmethod
    def _parseable_date(cls, value: Optional[str]) -> Optional[str]:
        """'YYYY-MM' 또는 'YYYY-MM-DD'로 읽히는지 확인한다.

        형식이 깨진 날짜는 "언제 기준인지 모르는 것"과 같다. 그럴 바에는 값을
        만들지 않는 편이 낫다 — 있는데 못 읽는 값이 제일 나쁘다.
        """
        if value is None:
            return None
        for pattern in ("%Y-%m-%d", "%Y-%m"):
            try:
                datetime.strptime(value, pattern)
                return value
            except ValueError:
                continue
        raise ValueError(f"날짜 형식이 아니다: {value!r} (예: '2026-08' 또는 '2026-08-01')")

    @field_validator("extractedAt")
    @classmethod
    def _iso8601(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"extractedAt이 ISO 8601이 아니다: {value!r}") from None
        return value

    def to_json(self) -> str:
        """파일로 쓸 JSON. 값이 없는 필드는 빼서 내보낸다.

        `"capabilities": null`을 남기면 "확인했는데 없음"과 헷갈린다. 키가 없는
        것이 "확인하지 못함"의 표현이다.
        """
        return self.model_dump_json(exclude_none=True, indent=2)

    def filled_fields(self) -> list[str]:
        """실제로 값이 채워진 필드 이름. 로그와 요약 출력에 쓴다."""
        names = (
            "hospitalId", "documentType", "effectiveDate",
            "nightDutyAvailable", "specialties", "capabilities", "equipment",
        )
        return [name for name in names if getattr(self, name) is not None]
