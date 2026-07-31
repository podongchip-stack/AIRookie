"""feature/info가 feature/hub로 보내는 병원 정보 스키마.

feature/hub 저장소의 `schema.py`에 있는 `HospitalInfo`와 필드명·타입이 1:1로
대응한다. hub가 실제로 파싱하는 형태가 계약이므로, 이 파일을 고칠 때는 반드시
hub의 `schema.py`를 먼저 확인할 것.

이 파일의 목적은 "잘못된 데이터가 만들어지는 순간 바로 실패시키는 것"이다.
형식이 틀린 JSON을 hub에 보내면 통합 시점에야 터지는데, 그때는 원인을 찾기가
훨씬 어렵다.

기본 필드 / 확장 필드
--------------------
- 기본 필드: hub가 지금 읽고 있는 필드. 절대 이름을 바꾸면 안 된다.
- 확장 필드(`bedsByType`, `capabilities`): 팀 합의로 추가된 필드. 전부 선택
  사항이라 hub가 아직 읽지 않아도 아무것도 깨지지 않는다. hub의 `HospitalInfo`는
  모르는 필드를 무시하기 때문(pydantic 기본 동작).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"


# --- 표준 역량 코드 어휘 -----------------------------------------------------
#
# 시연 시나리오 3종에 실제로 필요한 코드만 담았다. 어휘를 크게 잡으면 #1(voice)
# 담당자가 전부 외워야 해서 합의가 늦어진다. 확장은 대회 이후에 한다.

#: 병상 종류. `bedsByType`의 키로 쓴다.
BED_CODES: frozenset[str] = frozenset(
    {
        "ER_ADULT",  # 응급실 일반병상(성인)
        "ER_PEDIATRIC",  # 소아 응급실 병상
        "ER_NEGATIVE",  # 음압 격리병상
        "ICU",  # 일반 중환자실
        "CCU",  # 심장 중환자실
        "OR",  # 가용 수술방
    }
)

#: 시술·장비 역량. `capabilities` 목록의 원소로 쓴다.
CAPABILITY_CODES: frozenset[str] = frozenset(
    {
        "PROC_PCI_EMERGENCY",  # 응급 관상동맥중재술(심근경색 재관류)
        "PROC_IV_THROMBOLYSIS",  # 정맥 혈전용해술(뇌경색 tPA)
        "PROC_EVT_THROMBECTOMY",  # 동맥내 혈전제거술
        "PROC_CRANIOTOMY",  # 개두술(뇌출혈 수술)
        "PROC_CESAREAN_EMERGENCY",  # 응급 제왕절개
        "EQP_CT_24H",  # CT 24시간 가동
        "EQP_ANGIO_SUITE",  # 혈관조영실(앤지오)
    }
)

#: 사람이 읽을 라벨. 시연 영상 자막과 검증 출력에 쓴다.
LABELS_KO: dict[str, str] = {
    "ER_ADULT": "응급실 일반병상(성인)",
    "ER_PEDIATRIC": "소아 응급실 병상",
    "ER_NEGATIVE": "음압 격리병상",
    "ICU": "일반 중환자실",
    "CCU": "심장 중환자실",
    "OR": "가용 수술방",
    "PROC_PCI_EMERGENCY": "응급 관상동맥중재술",
    "PROC_IV_THROMBOLYSIS": "정맥 혈전용해술(tPA)",
    "PROC_EVT_THROMBECTOMY": "동맥내 혈전제거술",
    "PROC_CRANIOTOMY": "개두술",
    "PROC_CESAREAN_EMERGENCY": "응급 제왕절개",
    "EQP_CT_24H": "CT 24시간 가동",
    "EQP_ANGIO_SUITE": "혈관조영실",
}


def label_ko(code: str) -> str:
    """코드의 한글 라벨. 없으면 코드를 그대로 돌려준다."""
    return LABELS_KO.get(code, code)


# --- 모델 -------------------------------------------------------------------


class Strict(BaseModel):
    """정의되지 않은 필드를 거부한다.

    hub의 모델은 모르는 필드를 조용히 무시하지만, 우리 쪽은 반대로 막는다.
    `availableBedCount`를 `availableBedcount`로 잘못 쓰면 hub에서는 "그런
    필드 없음"으로 무시되고 기본값이 들어가는데, 여기서 막으면 만드는 순간
    바로 알 수 있다.
    """

    model_config = ConfigDict(extra="forbid")


class GpsPoint(Strict):
    """병원 위치. hub의 거리 계산에 그대로 쓰인다.

    범위를 대한민국으로 제한해 위도·경도를 바꿔 넣는 실수를 잡는다. 국내 좌표는
    위도 33~39, 경도 124~132라 서로 바꿔 넣으면 반드시 범위를 벗어난다.
    """

    lat: float = Field(ge=33.0, le=39.5, description="위도(WGS84)")
    lng: float = Field(ge=124.0, le=132.0, description="경도(WGS84). lon이 아니라 lng")


class Specialty(Strict):
    """진료과 1개. hub가 임베딩으로 예상 병명과 대조하는 대상."""

    department: str = Field(min_length=1, description="진료과명. 예: '흉부외과'")
    doctorCount: int = Field(ge=0, description="해당 진료과의 수술 가능 의사 수")
    recentProcedureTags: list[str] = Field(
        default_factory=list,
        description="최근 수술 이력 기반 전문 분야 태그. hub의 임베딩 매칭이 참고한다",
    )


class HospitalInfo(Strict):
    """병원 1곳의 정보. feature/hub로 보내는 단위."""

    # --- 기본 필드 (hub가 지금 읽는 것. 이름 변경 금지) ---
    hospitalId: str = Field(min_length=1, description="E-Gen 기관코드(hpid)를 그대로 쓴다")
    name: str = Field(min_length=1)
    gps: GpsPoint
    availableBedCount: int = Field(
        ge=0,
        description="실시간 가용 응급실 병상 수. E-Gen의 -1(미입력)은 매퍼에서 걸러야 한다",
    )
    nightDutyAvailable: bool = Field(description="야간 당직 전문의 존재 여부")
    specialties: list[Specialty] = Field(default_factory=list)
    source: Literal["rule"] = "rule"
    updatedAt: str = Field(description="ISO 8601 문자열. 예: '2026-07-30T09:55:00Z'")

    # --- 확장 필드 (팀 합의로 추가. 전부 선택 사항) ---
    bedsByType: Optional[dict[str, int]] = Field(
        default=None,
        description="병상 종류별 가용 수. 성인/소아 분기의 핵심. 미상인 종류는 키를 넣지 않는다",
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description="수행 가능한 시술·장비 코드 목록. hub의 하드필터 대조 대상",
    )

    @field_validator("updatedAt")
    @classmethod
    def _iso8601(cls, value: str) -> str:
        """ISO 8601로 읽히는지 확인한다.

        hub는 이 값을 그냥 문자열로 받지만, 형식이 깨져 있으면 나중에 시각 비교나
        보고서 작성 때 문제가 된다. 만드는 쪽에서 막는 편이 싸다.
        """
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(
                f"updatedAt이 ISO 8601 형식이 아니다: {value!r} (예: '2026-07-30T09:55:00Z')"
            ) from None
        return value

    @field_validator("bedsByType")
    @classmethod
    def _known_bed_codes(cls, value: Optional[dict[str, int]]) -> Optional[dict[str, int]]:
        """어휘에 없는 병상 코드와 음수 병상 수를 막는다."""
        if value is None:
            return None
        unknown = sorted(set(value) - BED_CODES)
        if unknown:
            raise ValueError(f"어휘에 없는 병상 코드: {unknown} (가능한 값: {sorted(BED_CODES)})")
        negative = sorted(code for code, count in value.items() if count < 0)
        if negative:
            raise ValueError(
                f"병상 수가 음수인 항목: {negative}. "
                "E-Gen의 -1(미입력)은 키를 넣지 않는 방식으로 처리한다"
            )
        return value

    @field_validator("capabilities")
    @classmethod
    def _known_capability_codes(cls, value: list[str]) -> list[str]:
        """어휘에 없는 역량 코드를 막는다.

        voice가 보내는 '필요역량'과 여기서 올리는 '보유역량'이 같은 어휘여야
        hub가 대조할 수 있다. 한쪽이 임의 코드를 쓰면 그 항목은 조용히 매칭에서
        빠진다 — 에러가 안 나기 때문에 더 위험하다.
        """
        unknown = sorted(set(value) - CAPABILITY_CODES)
        if unknown:
            raise ValueError(
                f"어휘에 없는 역량 코드: {unknown} (가능한 값: {sorted(CAPABILITY_CODES)})"
            )
        return value

    def to_hub_json(self) -> str:
        """hub로 보낼 JSON 문자열.

        값이 없는 선택 필드는 아예 빼서 내보낸다. `"bedsByType": null`을 보내도
        hub는 무시하지만, 사람이 결과 파일을 열어볼 때 지저분해진다.
        """
        return self.model_dump_json(exclude_none=True, indent=2)
