"""일시정지 중 조작 거부 · 추가 통화(덧붙이기) · 이송 중 수용 철회 검사(2026-10-05) — 실제 서버·로그 없이 app 함수를 직접 부른다.

- 시연 일시정지 중엔 병원 승인·불가가 거부되고, 그 소켓에 action_refused(paused)가 간다. 매칭 결과에 paused가 실린다
- 이송 중에도 같은 사건으로 다시 통화할 수 있고(추가 통화), 새 요약은 환자 정보에 덧붙는다(앞선 요약은 previousCalls)
  — 이송이 확정된 사건은 병원 목록·상태를 그대로 두고 환자 정보만 바뀐다
- 병원의 이송 중 수용 철회: 확정이 풀려 그 병원은 수용 불가(사유 포함)·이 사건에서 제외(다시 승인 불가),
  구급차는 그 자리에서 재선택 대기, 거절 로그엔 stage "transport"
- 통화 취소: 통화 상태에 cancelled가 실리고, 사건 진행 과정에 "통화 취소"가 남는다

    python test_transport_withdraw.py
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


def _voice(case_id: str, text: str, mechanism: str, severity: str = "high") -> VoiceCallSummaryMessage:
    return VoiceCallSummaryMessage(
        caseId=case_id, transcript=VoiceTranscript(raw_text=text, filtered_text=text),
        summary=VoiceSummary(patient="50대 남성", mechanism=mechanism, symptoms=["흉통"], treatment=[], severity_tag=severity),
        source="ai",
    )


def _action(case_id: str, action: str, hospital: str, actor: str = "hospital", reason: str | None = None) -> dict:
    payload = {"caseId": case_id, "action": action, "hospital_id": hospital, "actor": actor, "timestamp": "2026-10-05T00:00:00Z"}
    if reason:
        payload["reason"] = reason
    return payload


def _last(sock: _FakeSocket, type_: str, case_id: str | None = None) -> dict:
    return [m for m in sock.sent if m.get("type") == type_ and (case_id is None or m.get("caseId") == case_id)][-1]


def main() -> None:
    app._match_executor = _SyncExecutor()
    clock = [9000.0]
    app.sim = DispatchSim(None, random.Random(3), lambda: clock[0], Path(_TMP.name) / "sim")
    a = _hospital(beds=3)
    b = a.model_copy(update={"hospitalId": "T002", "name": "[테스트] 두 번째 병원", "gps": GpsPoint(lat=37.5690, lng=126.9800)})
    for h in (a, b):
        app.engine.update_hospital_info(h)
    app.app.test_client().post("/info/ambulances", json=AmbulanceInfo(
        apid="A_T", name="[테스트] 구급차", gps=GpsPoint(lat=37.5665, lng=126.9780), voicePort=6000,
        updatedAt="2026-10-05T00:00:00Z").model_dump())
    hospital_tab, ambulance_tab = _FakeSocket(), _FakeSocket()
    app._dashboard_sockets.update({hospital_tab, ambulance_tab})
    app._handle_identify(hospital_tab, DashboardIdentify(role="hospital", id=a.hospitalId))
    app._handle_identify(ambulance_tab, DashboardIdentify(role="ambulance", id="A_T"))

    case_id = "case-withdraw"
    app._handle_sim_command({"type": "dispatch", "apid": "A_T", "caseId": case_id, "timestamp": "t",
                             "target": {"lat": 37.5670, "lng": 126.9785}, "targetMode": "map"})
    clock[0] += 10
    app._sim_tick()
    assert app.sim.phase_of("A_T") == "on_scene"
    app._run_match_job(_voice(case_id, "1차 통화", "흉통 — 경색 의심"))

    print("=== 일시정지 중엔 병원 승인이 거부되고, 그 탭에 안내가 간다 ===")
    app._handle_sim_command({"type": "sim_pause", "apid": "A_T", "caseId": case_id, "timestamp": "t"})
    assert _last(hospital_tab, "match_result", case_id)["paused"] is True, "정지하면 매칭 결과에 paused가 실린다"
    app._handle_dashboard_action(_action(case_id, "hospital_approve", a.hospitalId), hospital_tab)
    refused = _last(hospital_tab, "action_refused")
    assert refused["reason"] == "paused" and refused["caseId"] == case_id, refused
    assert app.engine.get_case_status(case_id, a.hospitalId) == "pending", "정지 중 승인은 반영되지 않는다"
    app._handle_sim_command({"type": "sim_resume", "apid": "A_T", "caseId": case_id, "timestamp": "t"})
    assert _last(hospital_tab, "match_result", case_id)["paused"] is False
    print("  [확인] 정지 중 승인 거부 + action_refused(paused), 재개하면 paused=false")

    print("=== 승인·이송 확정 뒤 이송 중 추가 통화 → 환자 정보 덧붙이기(병원 목록은 그대로) ===")
    for h in (a, b):
        app._handle_dashboard_action(_action(case_id, "hospital_approve", h.hospitalId))
    app._handle_dashboard_action(_action(case_id, "final_approval", a.hospitalId, actor="paramedic"))
    assert app.sim.phase_of("A_T") == "transporting"
    before = app.engine.get_case_result(case_id)
    app._relay_call_signal(CallSignal(signal="call_started", timestamp="t", apid="A_T", caseId=case_id,
                                      hospitalId=a.hospitalId, device="phone"), ambulance_tab)
    status = _last(ambulance_tab, "call_status", case_id)
    assert status["state"] == "calling" and status["followup"] is True, "이송 중에도 추가 통화를 받는다"
    state = app.sim.state("A_T")
    assert state["paused"] and state["pauseReason"] == "call", "추가 통화가 연결되면 이송(이동)이 잠시 멈춘다"
    assert not app._case_paused(case_id), "통화 멈춤은 조작을 잠그지 않는다(운영자 일시정지와 구분)"
    app._relay_call_signal(CallSignal(signal="call_ended", timestamp="t", apid="A_T", caseId=case_id,
                                      hospitalId=a.hospitalId, device="phone"), ambulance_tab)
    assert app.sim.state("A_T")["paused"], "전송 뒤에도 요약이 반영될 때까지는 멈춰 있다"
    app._run_match_job(_voice(case_id, "2차 통화", "흉통 악화 — 쇼크 의심"))
    assert not app.sim.state("A_T")["paused"] and app.sim.phase_of("A_T") == "transporting", "요약이 반영되면 이송 재개"
    after = app.engine.get_case_result(case_id)
    p = after.patientInfo
    assert p.callRound == 2 and p.expectedDiagnosis == "흉통 악화 — 쇼크 의심", p
    assert [u.expectedDiagnosis for u in p.previousCalls] == ["흉통 — 경색 의심"], p.previousCalls
    assert "1차 통화" in p.rawTranscript and "2차 통화" in p.rawTranscript and "── 2차 통화 ──" in p.rawTranscript
    assert [(h.hospitalId, h.status) for h in after.hospitals] == [(h.hospitalId, h.status) for h in before.hospitals]
    print("  [확인] 추가 통화 중 이동 멈춤(조작 잠금 없음)→요약 반영 뒤 재개, 2차 요약이 최신 환자 정보, 1차는 previousCalls, 확정 병원 유지")

    print("=== 병원의 이송 중 수용 철회 → 확정 해제·제외·재선택 대기 ===")
    app._handle_dashboard_action(_action(case_id, "transport_withdraw", a.hospitalId, reason="BEDS_FULL"))
    result = app.engine.get_case_result(case_id)
    withdrawn = next(h for h in result.hospitals if h.hospitalId == a.hospitalId)
    assert withdrawn.status == "rejected" and withdrawn.rejectReason == "BEDS_FULL", withdrawn
    assert app.sim.phase_of("A_T") == "rerouting", "구급차는 그 자리에서 재선택 대기"
    assert app.engine.is_excluded(case_id, a.hospitalId)
    app._handle_dashboard_action(_action(case_id, "hospital_approve", a.hospitalId))
    assert app.engine.get_case_status(case_id, a.hospitalId) == "rejected", "철회한 병원은 이 사건에서 다시 승인되지 않는다"
    app._handle_dashboard_action(_action(case_id, "final_approval", b.hospitalId, actor="paramedic"))
    assert app.engine.get_case_status(case_id, b.hospitalId) == "confirmed" and app.sim.phase_of("A_T") == "transporting"
    payload = app._build_rejection_payload(app.ApprovalAction.model_validate(
        _action(case_id, "transport_withdraw", a.hospitalId, reason="BEDS_FULL")))
    assert payload["stage"] == "transport", payload
    print("  [확인] 철회 → 수용 불가(병상 만실)·제외·rerouting → 다른 승인 병원으로 재확정, 거절 로그 stage=transport")

    print("=== 통화 취소는 cancelled로 알리고 진행 과정에 남긴다 ===")
    app._relay_call_signal(CallSignal(signal="call_started", timestamp="t", apid="A_T", caseId=case_id,
                                      hospitalId=b.hospitalId, device="phone"), ambulance_tab)
    app._relay_call_signal(CallSignal(signal="call_ended", timestamp="t", apid="A_T", caseId=case_id,
                                      hospitalId=b.hospitalId, device="phone", cancelled=True), ambulance_tab)
    status = _last(ambulance_tab, "call_status", case_id)
    assert status["state"] == "ended" and status["cancelled"] is True, status
    assert not app.sim.state("A_T")["paused"], "취소하면 바로 이송 재개"
    assert any("통화 취소" in e["text"] for e in app.case_tracker.events(case_id))
    print("  [확인] 취소 통화 → call_status.cancelled=true, 진행 과정 '통화 취소 — 전달하지 않음'")
    app.sim = None
    print("\n모든 검사 통과")


if __name__ == "__main__":
    main()
