"""응급실 정원·포화도(erBedCapacity·erOccupancyPct, 2026-10-07) 검증.

- 포화도 = (정원 - 가용) ÷ 정원, 이송 확정 차감(TTL 오버레이)까지 반영
- 병상 미상이면 정원만 싣고 포화도는 None, 정원 정보가 없으면 둘 다 None
- 설명용이라 순위를 바꾸지 않는다

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


def main() -> None:
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
        print(f"  {h.hospitalId} 가용 {h.availableBedCount}/정원 {h.erBedCapacity} 포화도 {h.erOccupancyPct}% "
              f"demote={h.demoteReasons}")

    assert (by_id["C001"].erBedCapacity, by_id["C001"].erOccupancyPct) == (20, 75)
    assert (by_id["C002"].erBedCapacity, by_id["C002"].erOccupancyPct) == (12, None), "미상이면 포화도를 내지 않는다"
    assert (by_id["C003"].erBedCapacity, by_id["C003"].erOccupancyPct) == (None, None), "정원 없는 구 데이터도 통과"
    assert by_id["C004"].erOccupancyPct == 100
    assert [h.hospitalId for h in result.hospitals] == ["C001", "C002", "C003", "C004"], (
        "포화도는 순위에 안 쓴다 — 가까운 순 그대로, 만실(C004)만 beds_full로 뒤"
    )
    print("  [확인] 포화도 계산, 미상·정원 없음은 None, 순위 불변")

    _act(engine, case_id, "hospital_approve", "C001", "hospital")
    _act(engine, case_id, "final_approval", "C001", "paramedic")
    c001 = next(h for h in engine.get_case_result(case_id).hospitals if h.hospitalId == "C001")
    assert (c001.availableBedCount, c001.erOccupancyPct) == (4, 80), "이송 확정 차감까지 반영해 포화도가 오른다"
    print("  [확인] 이송 확정 뒤 가용 4/20 → 포화도 80%")
    print("\ntest_er_occupancy 통과")


if __name__ == "__main__":
    main()
