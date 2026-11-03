"""수용 곤란 사유의 되먹임(2026-11-04, 규칙 기반) — 한 번의 수용 곤란이 다음 배정을 더 정확하게 만들도록.

병원이 사유를 붙여 수용 곤란을 알리면 그 사건에서는 지금처럼 맨 뒤로 가고(rejected), 여기서는 **다른 사건**에 줄 영향을
사유의 축(4축 — info hospital_score/rejection.py REASON_AXIS)에 따라 정한다. 축이 다르면 갱신 대상도 다르다는 원칙:

- 순간적(병상 만실·수술실 사용 중·인력 부족): 그때의 여건이다 — MOMENTARY_HOLD_MIN(30분) 동안 그 병원 줄 길이에
  MOMENTARY_PENALTY_MIN(분)을 더한다. 후보에서 빼지 않고 분으로 설명된다(발표 11장 "순간적 사유는 30분만 반영").
- 구조적(병동·진료과·장비 없음): 그 질환군 역량의 증거다 — 같은 질환군 환자에게 STRUCTURAL_HOLD_HOURS 동안 순서를 내린다
  (declared_no와 같은 원칙: 빼지 않고 뒤로).
- 주기적(당직·야간)·환자 요인(중증도·연령)·사유 없음: 다른 사건에 반영하지 않는다(시간대 패턴·병원 속성이 아님).

상수는 정답 데이터가 없는 초안이다(spider feedback_probe의 시험값 30분). 거절 사유를 AI 학습 정답으로 쓰지는 않는다
(병원 편향 방지, 보고서) — 규칙으로만 반영한다. 메모리에만 두며 hub를 재시작하면 비워진다(30분·24시간 창이라 영향 작음).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

MOMENTARY = {"BEDS_FULL": "병상 만실", "OR_OCCUPIED": "수술실 사용 중", "STAFF_BUSY": "인력 부족"}
STRUCTURAL = {"NO_WARD": "병동 없음", "NO_DEPARTMENT": "해당 진료과 없음", "NO_EQUIPMENT": "필요 장비 없음"}

MOMENTARY_HOLD_MIN = 30
MOMENTARY_PENALTY_MIN = 15.0
STRUCTURAL_HOLD_HOURS = 24


@dataclass(frozen=True)
class Refusal:
    hospital_id: str
    case_id: str
    reason: str
    group: str | None
    at: datetime

    @property
    def axis(self) -> str | None:
        return "momentary" if self.reason in MOMENTARY else "structural" if self.reason in STRUCTURAL else None

    @property
    def until(self) -> datetime:
        if self.axis == "momentary":
            return self.at + timedelta(minutes=MOMENTARY_HOLD_MIN)
        return self.at + timedelta(hours=STRUCTURAL_HOLD_HOURS)


@dataclass(frozen=True)
class Effect:
    penalty_min: float = 0.0
    demote: bool = False
    reasons: tuple[str, ...] = ()


class RefusalMemory:
    """병원별 최근 수용 곤란. 스레드 안전성은 호출자(HubEngine 락)가 맡는다."""

    def __init__(self) -> None:
        self._items: dict[str, list[Refusal]] = {}

    def record(self, hospital_id: str, case_id: str, reason: str | None, group: str | None, at: datetime) -> Refusal | None:
        """반영할 축(순간적·구조적)이면 기억하고 돌려준다. 아니면 None(다른 사건에 영향 없음)."""
        item = Refusal(hospital_id, case_id, reason or "UNSPECIFIED", group, at)
        if item.axis is None:
            return None
        self._items.setdefault(hospital_id, []).append(item)
        return item

    def effect(self, hospital_id: str, case_id: str, group: str | None, now: datetime) -> Effect:
        """이 사건(case_id)에서 이 병원에 줄 영향. 자기 사건의 거절은 이미 rejected라 세지 않는다."""
        items = [r for r in self._items.get(hospital_id, []) if r.until > now]
        if items:
            self._items[hospital_id] = items
        else:
            self._items.pop(hospital_id, None)
        others = [r for r in items if r.case_id != case_id]
        momentary = [r for r in others if r.axis == "momentary"]
        structural = [r for r in others if r.axis == "structural" and group is not None and r.group == group]
        reasons = []
        penalty = 0.0
        if momentary:
            last = max(momentary, key=lambda r: r.at)
            penalty = MOMENTARY_PENALTY_MIN
            reasons.append(f"최근 수용 곤란({MOMENTARY[last.reason]}) — {MOMENTARY_HOLD_MIN}분 반영 +{penalty:g}분"
                           f" ({last.until.astimezone().strftime('%H:%M')}까지)")
        if structural:
            last = max(structural, key=lambda r: r.at)
            reasons.append(f"같은 질환군 수용 곤란({STRUCTURAL[last.reason]}) — {STRUCTURAL_HOLD_HOURS}시간 뒤로")
        return Effect(penalty, bool(structural), tuple(reasons))

    def active(self, now: datetime) -> list[Refusal]:
        return [r for items in self._items.values() for r in items if r.until > now]
