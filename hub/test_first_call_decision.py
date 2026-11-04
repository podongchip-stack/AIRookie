"""첫 통화 뒤 이송확정·이송불가 판단 검사(2026-11-04) — 실제 서버·로그 없이 app 함수를 직접 부른다.

- 통화가 끝나도(call_ended + awaitDecision) 요약은 병원에 가지 않고 hub가 붙잡아 둔다
- [이송불가]: 통화한 병원은 거절(rejected)로 적고 요약이 존 전체에 간다(기존 동시 전달)
- [이송확정]: 요약이 통화한 병원 한 곳에만 가고 바로 이송 확정(구급차 출발). 판단이 요약보다 먼저 와도 같다
- 판단이 없는 사건·다른 구급차 소켓·취소는 거부/정리된다
- 확정 사건이 갈 곳을 잃으면(존 확장 재요청) 좁힌 요청 목록이 풀린다

    python test_first_call_decision.py
"""
from __future__ import annotations

import os
import random
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decision_log.jsonl")
os.environ["HOSPITAL_REJECTION_LOG_DIR"] = str(Path(_TMP.name) / "rejections")
os.environ["HUB_REJECTION_URL"] = "http://127.0.0.1:9/hub/rejection"

import app  # noqa: E402
from ambulance_sim import DispatchSim  # noqa: E402
from schema import (  # noqa: E402
    AmbulanceInfo, CallSignal, DashboardIdentify, GpsPoint, VoiceCallSummaryMessage, VoiceSummary, VoiceTranscript,
)
from test_app_background import _FakeSocket, _hospital  # noqa: E402


class _SyncExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


def _voice(case_id: str) -> VoiceCallSummaryMessage:
    return VoiceCallSummaryMessage(
        caseId=case_id, transcript=VoiceTranscript(raw_text="통화 원문", filtered_text="통화 원문"),
        # 경증(KTAS 5) — 중증이면 규칙(KTAS 적합도)이 얇은 병원을 병원 탭 전달 대상에서 빼서, 동시 전달 검사가 흐려진다
        summary=VoiceSummary(patient="50대 남성", mechanism="복통", symptoms=["복통"], treatment=[],
                             severity_tag="low", ktas_level=5),
        source="ai",
    )


def _results(sock: _FakeSocket, case_id: str) -> list[dict]:
    return [m for m in sock.sent if m.get("type") == "match_result" and m.get("caseId") == case_id]


def _decision(case_id: str, decision: str) -> dict:
    return {"type": "call_decision", "caseId": case_id, "decision": decision, "timestamp": "2026-11-04T00:00:00Z"}


def main() -> None:
    app._match_executor = _SyncExecutor()
    clock = [9000.0]
    app.sim = DispatchSim(None, random.Random(5), lambda: clock[0], Path(_TMP.name) / "sim")
    a = _hospital(beds=5)
    b = a.model_copy(update={"hospitalId": "T002", "name": "[테스트] 두 번째 병원", "gps": GpsPoint(lat=37.5690, lng=126.9800)})
    for h in (a, b):
        app.engine.update_hospital_info(h)
    client = app.app.test_client()
    tabs: dict[str, _FakeSocket] = {}
    for apid in ("A_T1", "A_T2"):
        client.post("/info/ambulances", json=AmbulanceInfo(
            apid=apid, name=f"[테스트] {apid}", gps=GpsPoint(lat=37.5665, lng=126.9780), voicePort=6000,
            updatedAt="2026-11-04T00:00:00Z").model_dump())
        tabs[apid] = _FakeSocket()
        app._dashboard_sockets.add(tabs[apid])
        app._handle_identify(tabs[apid], DashboardIdentify(role="ambulance", id=apid))
    hospital_tabs = {h.hospitalId: _FakeSocket() for h in (a, b)}
    for hid, sock in hospital_tabs.items():
        app._dashboard_sockets.add(sock)
        app._handle_identify(sock, DashboardIdentify(role="hospital", id=hid))

    def to_scene(apid: str, case_id: str) -> None:
        app._handle_sim_command({"type": "dispatch", "apid": apid, "caseId": case_id, "timestamp": "t",
                                 "target": {"lat": 37.5670, "lng": 126.9785}, "targetMode": "map"})
        clock[0] += 10
        app._sim_tick()
        assert app.sim.phase_of(apid) == "on_scene", app.sim.phase_of(apid)

    def call(apid: str, case_id: str) -> None:
        """통화를 걸고(병원 a) 끊는다 — 판단 대기(awaitDecision)로."""
        app._relay_call_signal(CallSignal(signal="call_started", timestamp="t", apid=apid, caseId=case_id,
                                          hospitalId=a.hospitalId, device="phone"), tabs[apid])
        app._relay_call_signal(CallSignal(signal="call_ended", timestamp="t", apid=apid, caseId=case_id,
                                          hospitalId=a.hospitalId, device="phone", awaitDecision=True), tabs[apid])

    print("=== 통화가 끝나도 요약은 병원에 가지 않는다 ===")
    case1 = "case-reject"
    to_scene("A_T1", case1)
    call("A_T1", case1)
    assert case1 in app._first_call_wait
    app._run_match_job(_voice(case1))
    assert app.engine.get_case_result(case1) is None, "판단 전엔 매칭 결과가 없다"
    assert not any(_results(s, case1) for s in (*hospital_tabs.values(), tabs["A_T1"])), "어느 탭에도 요약이 가지 않는다"
    print("  [확인] 요약 보류 — 결과 0건, 병원·구급차 탭에 전송 없음")

    print("=== [이송불가] → 통화한 병원은 거절, 요약은 존 전체에 ===")
    app._handle_call_decision(tabs["A_T1"], _decision(case1, "reject"))
    result = app.engine.get_case_result(case1)
    assert result is not None and {h.hospitalId for h in result.hospitals} == {a.hospitalId, b.hospitalId}, result
    assert app.engine.get_case_status(case1, a.hospitalId) == "rejected", "통화한 병원은 불가로 기록"
    assert app.engine.get_case_status(case1, b.hospitalId) == "pending"
    assert _results(hospital_tabs[b.hospitalId], case1), "다른 병원도 요약을 받는다(동시 전달)"
    assert app.sim.phase_of("A_T1") == "on_scene", "불가면 출발하지 않는다"
    assert case1 not in app._first_call_wait
    print("  [확인] 존 전체 전달, 통화 병원 rejected, 구급차는 현장 그대로")

    print("=== [이송확정](판단이 요약보다 먼저) → 통화한 병원에만 전달하고 바로 출발 ===")
    case2 = "case-confirm"
    to_scene("A_T2", case2)
    call("A_T2", case2)
    app._handle_call_decision(tabs["A_T2"], _decision(case2, "confirm"))
    assert app.engine.get_case_result(case2) is None, "요약이 아직 없으니 처리를 기다린다"
    app._run_match_job(_voice(case2))
    result = app.engine.get_case_result(case2)
    assert result is not None and [h.hospitalId for h in result.hospitals] == [a.hospitalId], result.hospitals
    assert result.hospitals[0].status == "confirmed", result.hospitals[0].status
    assert _results(hospital_tabs[a.hospitalId], case2), "통화한 병원은 요약을 받는다"
    assert not _results(hospital_tabs[b.hospitalId], case2), "다른 병원에는 가지 않는다"
    assert app.sim.phase_of("A_T2") == "transporting", "확정하면 출발"
    print("  [확인] 요약은 통화 병원 한 곳에만, 상태 confirmed, 구급차 이송 중")

    print("=== 판단이 없는 사건·남의 소켓·중복·취소 ===")
    app._handle_call_decision(tabs["A_T1"], _decision(case1, "reject"))
    assert [m for m in tabs["A_T1"].sent if m.get("type") == "action_refused"][-1]["reason"] == "no_pending_decision"
    case3 = "case-cancel"
    app._sim_tick()
    app._handle_sim_command({"type": "sim_reset", "apid": "A_T1", "timestamp": "t"})
    to_scene("A_T1", case3)
    call("A_T1", case3)
    app._handle_call_decision(tabs["A_T2"], _decision(case3, "confirm"))  # 다른 구급차 소켓
    assert [m for m in tabs["A_T2"].sent if m.get("type") == "action_refused"][-1]["reason"] == "not_owner"
    assert case3 in app._first_call_wait and app._first_call_wait[case3]["decision"] is None
    app._handle_call_decision(tabs["A_T1"], _decision(case3, "cancel"))
    assert case3 not in app._first_call_wait, "취소하면 대기를 비운다"
    app._run_match_job(_voice(case3))  # 대기가 없으니 기존대로 바로 처리된다(판단 없이 남은 요약이 새지 않는 건 앱이 취소로 닫기 때문)
    print("  [확인] no_pending_decision / not_owner 거부, cancel은 대기 정리")

    print("=== 통화 취소는 판단 대기를 지운다 ===")
    case4 = "case-hangup-cancel"
    app._handle_sim_command({"type": "sim_reset", "apid": "A_T1", "timestamp": "t"})
    to_scene("A_T1", case4)
    call("A_T1", case4)
    assert case4 in app._first_call_wait
    app._relay_call_signal(CallSignal(signal="call_ended", timestamp="t", apid="A_T1", caseId=case4,
                                      hospitalId=a.hospitalId, device="phone", cancelled=True), tabs["A_T1"])
    assert case4 not in app._first_call_wait
    print("  [확인] cancelled call_ended → 대기 삭제")

    print("=== 확정 사건이 갈 곳을 잃으면(존 확장 재요청) 좁힌 요청 목록이 풀린다 ===")
    assert app.engine._case_only.get(case2) == {a.hospitalId}
    app.engine.force_expand_zone(case2, GpsPoint(lat=37.5665, lng=126.9780))
    assert case2 not in app.engine._case_only
    print("  [확인] 요청 목록 제한 해제")
    print("\n모든 검사 통과")


if __name__ == "__main__":
    main()
