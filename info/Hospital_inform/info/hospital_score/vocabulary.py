"""중증질환 수용가능 신고(MKioskTy) 어휘 — 28항목 · 15그룹 · 연령축.

`hospital_score`가 다루는 대상은 병상이 아니라 **병원이 스스로 신고한 중증질환
수용가능 여부**다. 이 파일은 그 28개 항목이 무엇인지 한 곳에 고정한다.

왜 별도 파일인가
----------------
`egen/mapper.py`의 `MKIOSK_TO_CAPABILITY`는 28항목 중 **5개만** 표준 역량 어휘
(`schema.py`의 `CAPABILITY_CODES` 7종)로 옮긴다. 어휘를 작게 유지해야 voice 담당자가
외울 수 있다는 원칙 때문이고, 그 판단 자체는 지금도 유효하다. 다만 그 결과로 나머지
23항목이 버려지는데, 이쪽 트랙에서는 **버려지는 23항목이 곧 재료**다. 그래서 mapper의
어휘를 건드리지 않고 여기서 원본 28항목을 따로 세운다.
(`hospital_score/`는 검증 전까지 폴더째 버릴 수 있어야 하므로, 기존 파일에 의존을
심지 않는다 — 이 파일은 저장소의 다른 모듈을 import 하지 않는다.)

출처
----
공공데이터포털 "국립중앙의료원_전국 응급의료기관 정보 조회 서비스" 활용가이드 V4
(NIA-IFT-OpenAPI활용가이드-01, HWP). 항목명은 그 문서에만 있고 웹 페이지에는 없다.

⚠️ 가이드에 MKioskTy 표가 **두 개** 있고 정의가 서로 다르다. 우리가 호출하는
`getSrsillDissAceptncPosblInfoInqire`의 표는 **소문자 `mkioskty*`** 쪽이다.
대문자 표는 다른 오퍼레이션 것이고 `MKioskTy1 = 뇌출혈수술`이라 정반대 매핑이 된다.
아래 항목명은 소문자 표에서 뽑은 것이며, 응답 XML의 실제 필드명은 `MKioskTy1`처럼
대문자로 온다(표기와 필드명이 다르다는 점에 주의).

실측 교차확인 (2026-08-12 전국 스냅샷, 병원 438곳)
--------------------------------------------------
- 값의 어휘는 `Y` / `불가능` / `정보미제공` 3종뿐이다. 명세에 있는 `N`은 쓰이지 않는다
- `MKioskTy{10,12,14,15,27}`에만 `...Msg` 동반 필드가 존재한다. 그리고 그 5개가
  연령축의 "영유아" 집합과 **정확히 일치**한다 — 연령축이 우리 임의 분류가 아니라
  E-Gen 자체 구조라는 독립 근거다 (Msg 내용도 "0세 이상", "최저체중:400g" 같은
  연령·체중 조건 자유텍스트다)
"""

from __future__ import annotations

from dataclasses import dataclass

#: 응답 XML의 필드명 접두어. 표기는 소문자(`mkioskty`)지만 실제 필드는 대문자로 온다
FIELD_PREFIX = "MKioskTy"

#: 수용가능 값의 실제 어휘. [확인됨 — 실측] 이 3종만 온다
ACCEPT_YES = "Y"
ACCEPT_NO = "불가능"
ACCEPT_UNKNOWN = "정보미제공"

#: 연령축 값
AGE_ADULT = "adult"
AGE_INFANT = "infant"
AGE_ANY = "any"


@dataclass(frozen=True)
class Item:
    """MKioskTy 항목 하나."""

    no: int
    group: str | None  # 대괄호 안의 상위 그룹. 28번(응급실)만 None
    label: str
    age: str

    @property
    def field(self) -> str:
        """응답 XML의 필드명 (예: `MKioskTy10`)."""
        return f"{FIELD_PREFIX}{self.no}"

    @property
    def msg_field(self) -> str | None:
        """연령·체중 조건이 담기는 동반 필드. 없는 항목은 None."""
        return f"{self.field}Msg" if self.no in MSG_ITEMS else None

    @property
    def full_label(self) -> str:
        return f"[{self.group}] {self.label}" if self.group else self.label


#: 동반 `Msg` 필드를 가진 항목. [확인됨 — 실측] 전부 영유아 항목이다
MSG_ITEMS: frozenset[int] = frozenset({10, 12, 14, 15, 27})

#: 28항목 전체. 대괄호가 곧 상위 그룹이라 우리가 임의로 묶지 않았다
ITEMS: tuple[Item, ...] = (
    Item(1, "재관류중재술", "심근경색", AGE_ANY),
    Item(2, "재관류중재술", "뇌경색", AGE_ANY),
    Item(3, "뇌출혈수술", "거미막하출혈", AGE_ANY),
    Item(4, "뇌출혈수술", "거미막하출혈 외", AGE_ANY),
    Item(5, "대동맥응급", "흉부", AGE_ANY),
    Item(6, "대동맥응급", "복부", AGE_ANY),
    Item(7, "담낭담관질환", "담낭질환", AGE_ANY),
    Item(8, "담낭담관질환", "담도포함질환", AGE_ANY),
    Item(9, "복부응급수술", "비외상", AGE_ANY),
    Item(10, "장중첩/폐색", "영유아", AGE_INFANT),
    Item(11, "응급내시경", "성인 위장관", AGE_ADULT),
    Item(12, "응급내시경", "영유아 위장관", AGE_INFANT),
    Item(13, "응급내시경", "성인 기관지", AGE_ADULT),
    Item(14, "응급내시경", "영유아 기관지", AGE_INFANT),
    Item(15, "저체중출생아", "집중치료", AGE_INFANT),
    Item(16, "산부인과응급", "분만", AGE_ANY),
    Item(17, "산부인과응급", "산과수술", AGE_ANY),
    Item(18, "산부인과응급", "부인과수술", AGE_ANY),
    Item(19, "중증화상", "전문치료", AGE_ANY),
    Item(20, "사지접합", "수족지접합", AGE_ANY),
    Item(21, "사지접합", "수족지접합 외", AGE_ANY),
    Item(22, "응급투석", "HD", AGE_ANY),
    Item(23, "응급투석", "CRRT", AGE_ANY),
    Item(24, "정신과적응급", "폐쇄병동입원", AGE_ANY),
    Item(25, "안과적수술", "응급", AGE_ANY),
    Item(26, "영상의학혈관중재", "성인", AGE_ADULT),
    Item(27, "영상의학혈관중재", "영유아", AGE_INFANT),
    # 28번만 대괄호가 없다. 중증질환이 아니라 "응급실 자체를 운영하는가"를 묻는 항목이라
    # 성격이 다르다 — 피드가 죽은 병원 중 이것만 `Y`인 곳들이 있다
    Item(28, None, "응급실(Emergency gate keeper)", AGE_ANY),
)

#: 번호로 찾는 색인
BY_NO: dict[int, Item] = {item.no: item for item in ITEMS}

#: 필드명으로 찾는 색인 (`MKioskTy10` -> Item)
BY_FIELD: dict[str, Item] = {item.field: item for item in ITEMS}

#: 상위 그룹 15종. 등장 순서를 유지한다 (번호 순 = 가이드 순)
GROUPS: tuple[str, ...] = tuple(
    dict.fromkeys(item.group for item in ITEMS if item.group is not None)
)

#: 28번(응급실 운영 여부). 중증질환 역량과 섞으면 안 되므로 따로 꺼내 쓴다
GATEKEEPER_NO = 28


def items_in_group(group: str) -> tuple[Item, ...]:
    return tuple(item for item in ITEMS if item.group == group)


def items_by_age(age: str) -> tuple[Item, ...]:
    return tuple(item for item in ITEMS if item.age == age)


def normalize_accept(raw: str | None) -> str | None:
    """응답 값을 3상태로 정규화한다.

    `Y`에 뒤쪽 공백이 붙어 오는 경우가 있어 항상 strip 한다. 아는 값이 아니면
    None을 돌려준다 — 조용히 미상으로 뭉개면 어휘가 늘어난 걸 눈치채지 못한다.
    """
    if raw is None:
        return None
    value = raw.strip()
    if value == ACCEPT_YES:
        return ACCEPT_YES
    if value == ACCEPT_NO:
        return ACCEPT_NO
    if value == ACCEPT_UNKNOWN:
        return ACCEPT_UNKNOWN
    return None


# 어휘가 조용히 깨지는 걸 막는 최소 검증. 이 파일은 손으로 옮겨 적은 표라
# 오타 하나가 전체 집계를 틀리게 만든다
assert len(ITEMS) == 28, "MKioskTy는 28항목이다"
assert [item.no for item in ITEMS] == list(range(1, 29)), "번호가 1~28 연속이어야 한다"
assert len(GROUPS) == 15, f"상위 그룹은 15종이어야 한다 (현재 {len(GROUPS)})"
assert {item.no for item in items_by_age(AGE_INFANT)} == MSG_ITEMS, (
    "영유아 항목과 Msg 동반 항목이 일치해야 한다 — 실측으로 확인된 성질이다"
)
