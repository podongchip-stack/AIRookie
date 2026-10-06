"""시연 콘솔 통화 방식 잠금 검사(2026-10-06) — ② 현장 확인·④ 이송 중에서 "정해진 상황 선택"이면 그 단계의 휴대폰
통화를 hub가 거부하고, "음성으로 통화"면 받는다. 두 단계의 방식은 따로다(② 정해진 상황이 ④ 목적지 병원 통화를 막지 않는다).

    python test_input_mode.py
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
from schema import (AmbulanceInfo, CallSignal, DashboardIdentify, GpsPoint, VoiceCallSummaryMessage,  # noqa: E402
                    VoiceSummary, VoiceTranscript)
from test_app_background import _FakeSocket, _hospital  # noqa: E402
from test_sim_reset import _Clock  # noqa: E402

CASE, APID = "c-mode", "A1"


def _refused(sock: _FakeSocket) -> bool:
    return any(m.get("type") == "action_refused" and m.get("reason") == "template_mode" for m in sock.sent)


def _try_call(phone: _FakeSocket, hospital_id: str) -> bool:
    """통화 시작을 보내고, 받아들여졌으면(거부 안 됨) 바로 끝내 다음 시도를 할 수 있게 한다."""
    phone.sent.clear()
    app._relay_call_signal(CallSignal(signal="call_started", timestamp="t", apid=APID, caseId=CASE,
                                      hospitalId=hospital_id, device="phone"), phone)
    ok = not _refused(phone)
    if ok:
        app._relay_call_signal(CallSignal(signal="call_ended", timestamp="t", apid=APID, caseId=CASE,
                                          hospitalId=hospital_id, device="phone", cancelled=True), phone)
    return ok


def main() -> None:
    clock = _Clock()
    app.sim = DispatchSim(None, random.Random(7), clock, Path(_TMP.name) / "sim")
    hospital = _hospital(beds=5)
    app.engine.update_hospital_info(hospital)
    client = app.app.test_client()
    client.post("/info/ambulances", json=AmbulanceInfo(apid=APID, name="[테스트] A1", gps=GpsPoint(lat=37.5665, lng=126.9780),
                                                      voicePort=6000, updatedAt="2026-10-06T00:00:00Z").model_dump())
    phone = _FakeSocket()
    app._dashboard_sockets.add(phone)
    app._handle_identify(phone, DashboardIdentify(role="ambulance", id=APID))
    app._handle_sim_command({"type": "dispatch", "apid": APID, "caseId": CASE, "timestamp": "t",
                             "target": {"lat": 37.5700, "lng": 126.9800}, "targetMode": "map"})
    clock.t += 10
    app._sim_tick()
    assert app.sim.phase_of(APID) == "on_scene"

    print("=== ② 현장: 정해진 상황 선택이면 통화 거부, 휴대폰에 stage scene으로 알림 ===")
    phone.sent.clear()
    app._handle_scene_input_mode({"caseId": CASE, "apid": APID, "mode": "template"})
    sent = [m for m in phone.sent if m.get("type") == "scene_input_mode"]
    assert sent and sent[-1]["stage"] == "scene" and sent[-1]["mode"] == "template", sent
    assert not _try_call(phone, hospital.hospitalId), "② 정해진 상황이면 현장 통화 거부"

    print("=== ② 정해진 상황으로 매칭 → 이송 확정 → 이송 중 ===")
    result = app.engine.process_voice_summary(
        VoiceCallSummaryMessage(caseId=CASE, transcript=VoiceTranscript(raw_text="t", filtered_text="t"),
                                summary=VoiceSummary(patient="50대", mechanism="흉통", symptoms=[], treatment=[],
                                                     severity_tag="high"), source="ai"),
        GpsPoint(lat=37.5700, lng=126.9800))
    app._send_to_dashboard(result.model_dump())
    for action, actor in (("hospital_approve", "hospital"), ("final_approval", "paramedic")):
        app._handle_dashboard_action({"caseId": CASE, "action": action, "hospital_id": hospital.hospitalId,
                                      "actor": actor, "timestamp": "2026-10-06T00:00:00Z"})
    assert app.sim.phase_of(APID) == "transporting", app.sim.phase_of(APID)
    assert _try_call(phone, hospital.hospitalId), "② 방식은 ④ 목적지 병원 통화를 막지 않는다(④ 방식 미지정)"

    print("=== ④ 이송 중: 정해진 상황 선택이면 목적지 병원 통화 거부, 음성이면 허용 ===")
    phone.sent.clear()
    app._handle_scene_input_mode({"caseId": CASE, "apid": APID, "mode": "template", "stage": "transport"})
    sent = [m for m in phone.sent if m.get("type") == "scene_input_mode"]
    assert sent and sent[-1]["stage"] == "transport" and sent[-1]["mode"] == "template", sent
    assert not _try_call(phone, hospital.hospitalId), "④ 정해진 상황이면 이송 중 통화 거부"
    app._handle_scene_input_mode({"caseId": CASE, "apid": APID, "mode": "voice", "stage": "transport"})
    assert _try_call(phone, hospital.hospitalId), "④ 음성이면 이송 중 통화 허용"

    print("=== 휴대폰 앱을 새로 열면 두 단계 방식을 모두 따라잡는다 ===")
    phone2 = _FakeSocket()
    app._dashboard_sockets.add(phone2)
    app._handle_identify(phone2, DashboardIdentify(role="ambulance", id=APID))
    stages = {m["stage"]: m["mode"] for m in phone2.sent if m.get("type") == "scene_input_mode"}
    assert stages == {"scene": "template", "transport": "voice"}, stages
    print("\n모든 검사 통과")


if __name__ == "__main__":
    main()
