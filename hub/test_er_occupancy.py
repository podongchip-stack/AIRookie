"""응급실 정원·포화도(erBedCapacity·erOccupancyPct)와 포화도 페널티(occupancyPenaltyMin, 2026-10-07) 검증.

- 포화도 = (정원 - 가용) ÷ 정원, 표시값은 이송 확정 차감(TTL 오버레이)까지 반영
- 병상 미상이면 정원만 싣고 포화도는 None, 정원 정보가 없으면 둘 다 None — 둘 다 페널티 0
- 포화도에 비례해 이동시간에 최대 5분을 더한다(차감 전 E-Gen 값 기준 — 부하 페널티와 이중 계산 안 함)
- 불변식: 페널티를 다 받아도 5분 넘게 가까운 병원은 역전당하지 않는다

    python hub/test_er_occupancy.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ.setdefault("HUB_DECISION_LOG_PATH", str(Path(_TMP.name) / "decision_log.jsonl"))
os.environ.setdefault("HUB_STATE_PATH", str(Path(_TMP.name) / "hub_state.json"))

from hub_engine import HubEngine  # noqa: E402
from schema import ApprovalAction, GpsPoint, HospitalInfo, Specialty  # noqa: E402
from scoring import OCCUPANCY_PENALTY_MAX_MIN, final_score, occupancy_penalty_min  # noqa: E402
from test_acceptance_messages import SCENE, _FakeMatcher, _voice  # noqa: E402


def _hospital(hpid: str, lat: float, beds: dict[str, int] | None, capacity: dict[str, int] | None) -> HospitalInfo:
    return HospitalInfo(
        hospitalId=hpid, name=f"[테스트] {hpid}", gps=GpsPoint(lat=lat, lng=126.9780),
        availableBedCount=(beds or {}).get("ER_ADULT", 0), nightDutyAvailable=True,
        specialties=[Specialty(department="흉부외과", doctorCount=0)],
        updatedAt="2026-10-07T00:00:00Z", bedsByType=beds, bedCapacityByType=capacity,
    )


def _act(engine: HubEngine, case_id: str, action: str, hpid: str, actor: str) -> None:
    engine.apply_approval_action(ApprovalAction(caseId=case_id, action=action, hospital_id=hpid,
                                                actor=actor, timestamp="2026-10-07T00:00:00Z"))


def test_penalty_rule() -> None:
    assert occupancy_penalty_min(None) == (0.0, None) and occupancy_penalty_min(0) == (0.0, None), "미상·0%는 0분"
    assert occupancy_penalty_min(100)[0] == OCCUPANCY_PENALTY_MAX_MIN == 5.0
    assert occupancy_penalty_min(40)[0] == 2.0
    for near in (1.0, 5.0, 12.0, 30.0):
        far = near + OCCUPANCY_PENALTY_MAX_MIN + 0.01
        assert final_score(0.5, near, occupancy_min=OCCUPANCY_PENALTY_MAX_MIN) > final_score(0.5, far), (
            f"{near}분: 포화도 100%여도 5분 넘게 먼 병원에 역전당하면 안 된다"
        )
    print("  [확인] 포화도 비례 0~5분, 미상 0분, 5분 불변식")


def main() -> None:
    test_penalty_rule()
    engine = HubEngine(specialty_matcher=_FakeMatcher())
    engine.update_hospital_info(_hospital("C001", 37.5700, {"ER_ADULT": 5}, {"ER_ADULT": 20}))
    engine.update_hospital_info(_hospital("C002", 37.5750, None, {"ER_ADULT": 12}))  # 병상 미상
    engine.update_hospital_info(_hospital("C003", 37.5800, {"ER_ADULT": 2}, None))  # 정원 정보 없음(구 info)
    engine.update_hospital_info(_hospital("C004", 37.5850, {"ER_ADULT": 0}, {"ER_ADULT": 8}))  # 만실

    case_id = "case-er-occupancy"
    engine.register_case(case_id, "A0000099")
    result = engine.process_voice_summary(_voice(case_id), SCENE, max_zone=1)
    by_id = {h.hospitalId: h for h in result.hospitals}
    for h in result.hospitals:
        print(f"  {h.hospitalId} {h.travelMin}분 가용 {h.availableBedCount}/정원 {h.erBedCapacity} "
              f"포화도 {h.erOccupancyPct}% 페널티 +{h.occupancyPenaltyMin}분 demote={h.demoteReasons}")

    assert (by_id["C001"].erBedCapacity, by_id["C001"].erOccupancyPct) == (20, 75)
    assert (by_id["C002"].erBedCapacity, by_id["C002"].erOccupancyPct) == (12, None), "미상이면 포화도를 내지 않는다"
    assert (by_id["C003"].erBedCapacity, by_id["C003"].erOccupancyPct) == (None, None), "정원 없는 구 데이터도 통과"
    assert by_id["C004"].erOccupancyPct == 100
    assert by_id["C001"].occupancyPenaltyMin in (3.7, 3.8) and by_id["C001"].occupancyReason
    assert by_id["C002"].occupancyPenaltyMin == by_id["C003"].occupancyPenaltyMin == 0.0, "미상·정원 없음은 페널티 0"
    assert [h.hospitalId for h in result.hospitals] == ["C002", "C003", "C001", "C004"], (
        "가장 가깝지만 75% 찬 C001이 1~2분 더 먼 병원들 뒤로, 만실(C004)은 beds_full로 맨 뒤"
    )
    print("  [확인] 포화도 계산, 미상·정원 없음은 None·페널티 0, 붐비는 근접 병원이 조금 먼 병원 뒤로")

    _act(engine, case_id, "hospital_approve", "C001", "hospital")
    _act(engine, case_id, "final_approval", "C001", "paramedic")
    c001 = next(h for h in engine.get_case_result(case_id).hospitals if h.hospitalId == "C001")
    assert (c001.availableBedCount, c001.erOccupancyPct) == (4, 80), "이송 확정 차감까지 반영해 표시 포화도가 오른다"
    rematch = engine.process_voice_summary(_voice("case-er-occupancy-2"), SCENE, max_zone=1)
    c001_next = next(h for h in rematch.hospitals if h.hospitalId == "C001")
    assert c001_next.occupancyPenaltyMin == by_id["C001"].occupancyPenaltyMin and c001_next.inFlightCount == 1, (
        "확정 차감은 부하 페널티가 센다 — 포화도 페널티는 차감 전 E-Gen 값 그대로(이중 계산 없음)"
    )
    print("  [확인] 이송 확정 뒤 표시 포화도 80%, 포화도 페널티는 그대로이고 이송 중 1건은 부하 페널티로")
    print("\ntest_er_occupancy 통과")


if __name__ == "__main__":
    main()
