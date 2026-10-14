"""병상 차감 유지·해제 규칙(BedHold, 2026-10-08) 검증 — 예전 고정 15분 TTL을 대체.

- 최소 유지: 확정 + 예상 이동시간 + BED_HOLD_GRACE_MIN까지는 E-Gen 값이 줄어도 유지
- 조기 해제: 그 뒤 E-Gen 응급실 원값이 확정 당시보다 줄었으면 해제(이중 차감 방지), 줄어든 만큼만
- 상한: 끝까지 안 줄면 도착 예상 + BED_HOLD_MAX_AFTER_ARRIVAL_MIN에 해제
- 수용 완료(arrival_accepted)면 기준을 실제 도착 시각으로 다시 잡는다
- 재선택 때 이전 병원의 차감 회수, 상태 파일 저장·복구(예전 형식 포함)

임베딩 모델 없이 가짜 진료과 매처, 시계는 hub_engine._utcnow를 바꿔 끼운다.

    python hub/test_bed_hold.py
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ.setdefault("HUB_DECISION_LOG_PATH", str(Path(_TMP.name) / "decision_log.jsonl"))
os.environ.setdefault("HUB_STATE_PATH", str(Path(_TMP.name) / "hub_state.json"))

import hub_engine  # noqa: E402
from hub_engine import BED_HOLD_GRACE_MIN, BED_HOLD_MAX_AFTER_ARRIVAL_MIN, HubEngine  # noqa: E402
from schema import ApprovalAction, GpsPoint, HospitalInfo, Specialty  # noqa: E402
from test_acceptance_messages import SCENE, _FakeMatcher, _voice  # noqa: E402

T0 = datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc)


class _Clock:
    now = T0

    def __call__(self) -> datetime:
        return self.now


CLOCK = _Clock()
hub_engine._utcnow = CLOCK


def _hospital(hpid: str, lat: float, beds: int) -> HospitalInfo:
    return HospitalInfo(
        hospitalId=hpid, name=f"[테스트] {hpid}", gps=GpsPoint(lat=lat, lng=126.9780),
        availableBedCount=beds, nightDutyAvailable=True,
        specialties=[Specialty(department="흉부외과", doctorCount=0)],
        updatedAt="2026-10-08T00:00:00Z", bedsByType={"ER_ADULT": beds},
    )


def _act(engine: HubEngine, case_id: str, action: str, hpid: str) -> bool:
    actor = "paramedic" if action == "final_approval" else "hospital"
    return engine.apply_approval_action(ApprovalAction(caseId=case_id, action=action, hospital_id=hpid,
                                                       actor=actor, timestamp="2026-10-08T03:00:00Z"))


def _confirm(engine: HubEngine, case_id: str, hpid: str) -> float:
    """사건을 매칭하고 hpid에 병원 승인 → 이송 승인. 그 병원의 이동시간(분)을 돌려준다."""
    engine.register_case(case_id, "A0000099")
    result = engine.process_voice_summary(_voice(case_id), SCENE, max_zone=1)
    _act(engine, case_id, "hospital_approve", hpid)
    assert _act(engine, case_id, "final_approval", hpid)
    return next(h.travelMin for h in result.hospitals if h.hospitalId == hpid)


def _beds(engine: HubEngine, hpid: str) -> int:
    return engine.effective_bed_count(engine.get_hospital(hpid))


def _set_egen(engine: HubEngine, hpid: str, lat: float, beds: int) -> None:
    engine.update_hospital_info(_hospital(hpid, lat, beds))


def _at(minutes: float) -> None:
    CLOCK.now = T0 + timedelta(minutes=minutes)


def test_hold_and_reconcile() -> None:
    print("=== 최소 유지 → E-Gen 반영 시 해제(이중 차감 없음) ===")
    engine = HubEngine(specialty_matcher=_FakeMatcher())
    _at(0)
    _set_egen(engine, "B001", 37.5900, 5)
    travel = _confirm(engine, "case-hold-1", "B001")
    assert _beds(engine, "B001") == 4 and engine.in_flight_count("B001") == 1
    release_at = travel + BED_HOLD_GRACE_MIN
    print(f"  이동 {travel}분 → 최소 유지 {release_at:.1f}분까지")

    _at(15)  # 예전 고정 TTL(15분)이면 여기서 풀렸다 — 구급차 도착 전
    assert _beds(engine, "B001") == 4, "도착 전·최소 유지 중에는 차감이 남아야 한다"
    _set_egen(engine, "B001", 37.5900, 4)  # 병원이 반영함(E-Gen 5 → 4)
    _at(release_at - 0.5)
    assert _beds(engine, "B001") == 3, "최소 유지 중이면 E-Gen이 줄어도 차감 유지(보수적)"
    _at(release_at + 0.5)
    assert _beds(engine, "B001") == 4 and engine.in_flight_count("B001") == 0, (
        "최소 유지가 끝나고 E-Gen이 확정 당시보다 줄었으면 해제 — E-Gen 4석 그대로, 이중 차감 없음"
    )
    assert ("case-hold-1", "B001") not in engine._case_overlay
    print("  [확인] 15분에도 유지, 최소 유지 끝 + E-Gen 반영이면 해제(표시 4석, 이중 차감 없음)")


def test_max_age() -> None:
    print("=== E-Gen이 끝내 안 줄면 상한에서 해제 ===")
    engine = HubEngine(specialty_matcher=_FakeMatcher())
    _at(0)
    _set_egen(engine, "B002", 37.5900, 5)
    travel = _confirm(engine, "case-hold-2", "B002")
    _at(travel + BED_HOLD_MAX_AFTER_ARRIVAL_MIN - 1)
    assert _beds(engine, "B002") == 4, "상한 전에는 E-Gen이 안 줄었으면 유지"
    _at(travel + BED_HOLD_MAX_AFTER_ARRIVAL_MIN + 1)
    assert _beds(engine, "B002") == 5 and "B002" not in engine._bed_overlay
    print(f"  [확인] 도착 예상 + {BED_HOLD_MAX_AFTER_ARRIVAL_MIN}분 전엔 유지, 지나면 해제")


def test_two_holds_partial() -> None:
    print("=== 같은 병원 2건 — 줄어든 만큼만 해제 ===")
    engine = HubEngine(specialty_matcher=_FakeMatcher())
    _at(0)
    _set_egen(engine, "B003", 37.5900, 6)
    travel = _confirm(engine, "case-hold-3a", "B003")
    _confirm(engine, "case-hold-3b", "B003")
    assert _beds(engine, "B003") == 4 and engine.in_flight_count("B003") == 2
    _set_egen(engine, "B003", 37.5900, 5)  # 한 명만 반영됨
    _at(travel + BED_HOLD_GRACE_MIN + 1)
    assert engine.in_flight_count("B003") == 1 and _beds(engine, "B003") == 4, "1석 줄었으면 먼저 확정된 1건만 해제"
    _set_egen(engine, "B003", 37.5900, 4)
    assert engine.in_flight_count("B003") == 0 and _beds(engine, "B003") == 4
    print("  [확인] E-Gen 1석 감소 → 1건 해제(다음 조회에도 1건 유지), 2석 감소 → 나머지도 해제")

    # 앞 환자가 E-Gen에 반영된 뒤에 다음 확정이 잡힌 경우 — 나중 차감의 baseline은 이미 줄어든 값이라 더 깎으면 안 된다
    engine = HubEngine(specialty_matcher=_FakeMatcher())
    _at(0)
    _set_egen(engine, "B007", 37.5900, 6)
    travel = _confirm(engine, "case-hold-7a", "B007")
    _set_egen(engine, "B007", 37.5900, 5)  # 첫 환자 반영
    _at(10)
    _confirm(engine, "case-hold-7b", "B007")  # baseline 5
    _at(travel + BED_HOLD_GRACE_MIN + 1)
    assert engine.in_flight_count("B007") == 1 and engine.in_flight_count("B007") == 1
    _set_egen(engine, "B007", 37.5900, 4)  # 둘째 환자 반영
    _at(10 + travel + BED_HOLD_GRACE_MIN + 1)
    assert engine.in_flight_count("B007") == 0, "둘째 환자가 반영되면 둘째 차감도 풀려야 한다(이중 차감 방지)"
    print("  [확인] 이미 줄어든 값으로 잡힌 차감은 더 깎지 않아, 그 환자가 반영되면 제때 풀림")


def test_arrival_reanchor() -> None:
    print("=== 수용 완료 시각으로 기준 재설정 ===")
    engine = HubEngine(specialty_matcher=_FakeMatcher())
    _at(0)
    _set_egen(engine, "B004", 37.5900, 5)
    travel = _confirm(engine, "case-hold-4", "B004")
    arrived = travel + 30  # 예상보다 30분 늦게 도착(교통·현장 지연)
    _at(arrived)
    assert _act(engine, "case-hold-4", "arrival_accepted", "B004")
    _set_egen(engine, "B004", 37.5900, 4)  # E-Gen엔 이미 다른 이유로 줄어 있다
    _at(arrived + BED_HOLD_GRACE_MIN - 1)
    assert engine.in_flight_count("B004") == 1, "실제 도착 뒤 최소 유지가 다시 시작돼야 한다"
    _at(arrived + BED_HOLD_GRACE_MIN + 1)
    assert engine.in_flight_count("B004") == 0
    print(f"  [확인] 수용 완료 시점부터 {BED_HOLD_GRACE_MIN}분 유지 후 해제")


def test_reselect_and_state() -> None:
    print("=== 재선택 회수 · 상태 저장/복구 ===")
    engine = HubEngine(specialty_matcher=_FakeMatcher())
    _at(0)
    _set_egen(engine, "B005", 37.5900, 5)
    _set_egen(engine, "B006", 37.5950, 5)
    _confirm(engine, "case-hold-5", "B005")
    _act(engine, "case-hold-5", "hospital_approve", "B006")
    assert _act(engine, "case-hold-5", "final_approval", "B006")
    assert _beds(engine, "B005") == 5 and _beds(engine, "B006") == 4, "재선택하면 이전 병원 차감 회수"

    state = engine.export_state()
    restored = HubEngine(specialty_matcher=_FakeMatcher())
    restored.import_state(state)
    hold = restored._case_overlay[("case-hold-5", "B006")]
    assert hold in restored._bed_overlay["B006"] and hold.baseline == 5 and _beds(restored, "B006") == 4
    print("  [확인] 재선택 회수, 저장·복구 후 차감·사건 연결·확정 당시 값 유지")

    legacy = HubEngine(specialty_matcher=_FakeMatcher())
    expires = (T0 + timedelta(minutes=10)).isoformat()
    legacy.import_state({**state, "bedOverlay": {"B006": [expires]}, "caseOverlay": [["case-old", "B006", expires]]})
    assert legacy.in_flight_count("B006") == 1 and ("case-old", "B006") in legacy._case_overlay
    _at(11)
    assert legacy.in_flight_count("B006") == 0
    print("  [확인] 예전 형식(만료 시각 문자열) 상태 파일도 그 시각에 풀리는 차감으로 복구")


def main() -> None:
    test_hold_and_reconcile()
    test_max_age()
    test_two_holds_partial()
    test_arrival_reanchor()
    test_reselect_and_state()
    print("\ntest_bed_hold 통과")


if __name__ == "__main__":
    main()
