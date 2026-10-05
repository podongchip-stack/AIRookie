"""중증질환 수용가능(MKioskTy) 신고의 claim 추적 — 규칙 기반 신선도.

병상(hvec)과 달리 이 채널은 **모델을 쓰지 않는다.** Phase 0 실측
(`python -m reliability.probe_severe`, 스냅샷 47일)에서 값 변화 사건의 90%가
Y↔정보미제공 왕복이고 그 만료 수명의 60.1%가 정확히 9.0시간에 몰려 있음이
확인됐다 — 지배 성분이 병원의 행동이 아니라 "신고 후 약 9시간 자동 만료"라는
시스템 규칙이라, 모델로 포장하면 hvidate 기각(AIROOKIE-EGEN.md §8)과 같은
오류가 된다. 규칙으로 충분한 것은 규칙으로 한다(프로젝트 공통 원칙).
진짜 내용 변화(Y↔불가능)는 47일에 2,658건뿐이라 학습은 축적 후 재평가.

그래서 이 모듈이 제공하는 것은 예측이 아니라 **사실**이다: "이 질환군의
현재 신고(Y/불가능)가 언제부터 그 값이었는지"(관측 기준 탄생 시각). E-Gen
중증질환 응답에는 신고 시각 필드가 아예 없어서(실측 — hpid·dutyName·
MKioskTy*뿐), 이 값은 우리 스냅샷 추적만이 안다. hub는 이걸로 신고 나이와
9시간 규칙 기준 잔여 시간을 계산해 dashboard에 노출한다.

정보미제공을 값으로 추적하는 이유(3상태): Y(월) → 미제공(화~수) → Y(목)
흐름에서 미제공을 결측으로 버리면 목요일의 재신고가 월요일부터 이어진 Y로
보여 신고 나이가 과대평가된다 — 미제공 전이를 관측해야 재신고의 탄생
시각이 정확해진다. 단 밖으로 내보내는 것은 현재 값이 Y/불가능인 그룹뿐이다
(미제공인 그룹은 항목 자체를 넣지 않는다 — bedsByType의 "미상은 키를 넣지
않는다"와 같은 표현 방식).

⚠ 항목→그룹 대응은 hospital_score/vocabulary.py ITEMS에서 복사했다(이 폴더의
바깥 import 금지 원칙 — hub가 15그룹을 복사해 쓰는 것과 같은 패턴).
28번(응급실 gatekeeper)은 중증질환이 아니라 제외한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .features import SEGMENT_GAP_SEC

SEVERE_OP = "getSrsillDissAceptncPosblInfoInqire"

ACCEPT_YES = "Y"
ACCEPT_NO = "불가능"
ACCEPT_UNKNOWN = "정보미제공"

#: 신고의 통상 만료 규칙(시간). Phase 0 실측 — Y→미제공 만료 수명의 60.1%가
#: 정확히 9.0h 구간(재현: reliability/probe_severe.py + 만료 규칙성 분석).
EXPIRY_RULE_HOURS = 9.0

#: MKioskTy 항목 번호 → 상위 질환군 15종 (vocabulary.py ITEMS의 대괄호 그룹).
ITEM_TO_GROUP: dict[int, str] = {
    1: "재관류중재술", 2: "재관류중재술",
    3: "뇌출혈수술", 4: "뇌출혈수술",
    5: "대동맥응급", 6: "대동맥응급",
    7: "담낭담관질환", 8: "담낭담관질환",
    9: "복부응급수술",
    10: "장중첩/폐색",
    11: "응급내시경", 12: "응급내시경", 13: "응급내시경", 14: "응급내시경",
    15: "저체중출생아",
    16: "산부인과응급", 17: "산부인과응급", 18: "산부인과응급",
    19: "중증화상",
    20: "사지접합", 21: "사지접합",
    22: "응급투석", 23: "응급투석",
    24: "정신과적응급",
    25: "안과적수술",
    26: "영상의학혈관중재", 27: "영상의학혈관중재",
}


@dataclass
class DeclarationState:
    """(병원, 항목) 하나의 현재 신고 상태. 시각은 전부 aware UTC."""

    last_obs: datetime
    last_value: str  # Y / 불가능 / 정보미제공
    born: datetime  #: 현재 값이 이 값으로 바뀐 게 관측된 시각
    segment_start: datetime  #: 이 관측 연속 구간의 시작 (좌측검열 판정용)


@dataclass
class GroupDeclaration:
    """질환군 하나의 현재 신고 요약 (hub로 나가는 단위)."""

    value: str  # Y / 불가능
    born: datetime
    #: True면 추적 시작(세그먼트 첫 관측)부터 이 값이었다 — 실제 신고는 더
    #: 오래됐을 수 있어 나이가 하한이라는 뜻(좌측검열).
    age_is_min: bool


class SevereTracker:
    """병원×항목 신고 스트림을 3상태로 추적한다. 규칙은 병상 tracker와 동일:
    값 변화 = 새 버전, 관측 공백 1시간 초과 = 세그먼트 리셋, 과거 관측 무시."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, int], DeclarationState] = {}

    def observe_row(self, row: dict, ts: datetime) -> int:
        """중증질환 응답 한 병원 행을 반영한다. 반영한 항목 수를 돌려준다."""
        hpid = (row.get("hpid") or "").strip()
        if not hpid:
            return 0
        fed = 0
        for no in ITEM_TO_GROUP:
            raw = row.get(f"MKioskTy{no}")
            value = raw.strip() if isinstance(raw, str) else None
            if value not in (ACCEPT_YES, ACCEPT_NO, ACCEPT_UNKNOWN):
                continue  # 어휘 밖/필드 없음 — 관측으로 치지 않는다
            self._observe(hpid, no, ts, value)
            fed += 1
        return fed

    def _observe(self, hpid: str, no: int, ts: datetime, value: str) -> None:
        key = (hpid, no)
        state = self._states.get(key)
        if state is None or (ts - state.last_obs).total_seconds() > SEGMENT_GAP_SEC:
            self._states[key] = DeclarationState(
                last_obs=ts, last_value=value, born=ts, segment_start=ts
            )
            return
        if ts <= state.last_obs:
            return
        if value != state.last_value:
            state.born = ts
            state.last_value = value
        state.last_obs = ts

    def group_declarations(self) -> dict[str, dict[str, GroupDeclaration]]:
        """병원별 · 질환군별 현재 신고 요약.

        그룹 값은 hospital_score의 최상위 tier 선택과 정합되게 Y를 불가능보다
        우선한다(항목 중 하나라도 Y면 그룹은 declared_yes). 같은 값이 여럿이면
        가장 최근에 태어난 항목을 대표로 쓴다 — "가장 신선한 근거"의 나이.
        현재 값이 정보미제공뿐인 그룹은 아예 넣지 않는다.
        """
        # hpid -> group -> 후보 (value 우선순위, born)
        result: dict[str, dict[str, GroupDeclaration]] = {}
        for (hpid, no), state in self._states.items():
            if state.last_value == ACCEPT_UNKNOWN:
                continue
            group = ITEM_TO_GROUP[no]
            candidate = GroupDeclaration(
                value=state.last_value,
                born=state.born,
                age_is_min=state.born == state.segment_start,
            )
            groups = result.setdefault(hpid, {})
            current = groups.get(group)
            if current is None or _prefer(candidate, current):
                groups[group] = candidate
        return result


def _prefer(candidate: GroupDeclaration, current: GroupDeclaration) -> bool:
    """그룹 대표 신고 선택: Y > 불가능, 같으면 최근 born."""
    rank_candidate = 1 if candidate.value == ACCEPT_YES else 0
    rank_current = 1 if current.value == ACCEPT_YES else 0
    if rank_candidate != rank_current:
        return rank_candidate > rank_current
    return candidate.born > current.born
