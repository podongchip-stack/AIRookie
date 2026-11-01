"""관제(dispatcher) 이송 승인 대행(2026-11-01) 검증 — 엔진 규칙만. 소켓이 monitor인지는 app 단에서 막는다.

    python hub/test_dispatcher_approval.py
"""
from test_bed_hold import _hospital, HubEngine, ApprovalAction, SCENE, _voice, _FakeMatcher  # noqa: F401


def _a(engine, action, actor, hpid):
    return engine.apply_approval_action(ApprovalAction(caseId="case-d1", action=action, hospital_id=hpid,
                                                       actor=actor, timestamp="2026-11-01T03:00:00Z"))


def main() -> None:
    engine = HubEngine(specialty_matcher=_FakeMatcher())
    engine.update_hospital_info(_hospital("D001", 37.5700, 10))
    engine.register_case("case-d1", "A0000099")
    engine.process_voice_summary(_voice("case-d1"), SCENE, max_zone=1)

    assert not _a(engine, "final_approval", "dispatcher", "D001"), "병원 승인 전 이송 확정은 관제도 안 된다"
    assert _a(engine, "hospital_approve", "hospital", "D001")
    assert not _a(engine, "hospital_approve", "dispatcher", "D001"), "dispatcher는 이송 승인만 대행"
    assert _a(engine, "final_approval", "dispatcher", "D001")
    print("OK")


if __name__ == "__main__":
    main()
