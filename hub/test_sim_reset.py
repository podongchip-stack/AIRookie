"""[시연 초기화] 검사(2026-10-04) — 진행 중 사건이 이송 확정·현장·출동 중 어느 단계든 전부 닫힌다.

대량사고를 연달아 돌린 뒤 초기화하면 이송 확정 사건이 하나 남는 문제가 있었다: 초기화가 구급차가 맡은 사건만
닫았고, 그것도 이송 확정 사건은 엔진이 60분 보관 규칙으로 거절했다. 구급차는 기지로 돌아가 주인 없는 사건이 되어
구급차 대시보드에도 이어지지 않았다.

    python test_sim_reset.py
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
from schema import AmbulanceInfo, DashboardIdentify, GpsPoint, VoiceCallSummaryMessage, VoiceSummary, VoiceTranscript  # noqa: E402
from test_app_background import _FakeSocket, _hospital  # noqa: E402


class _Clock:
    t = 2_000_000.0

    def __call__(self) -> float:
        return self.t


def _types(sock: _FakeSocket) -> list[str]:
    return [m.get("type") for m in sock.sent]


def main() -> None:
    clock = _Clock()
    app.sim = DispatchSim(None, random.Random(7), clock, Path(_TMP.name) / "sim")
    hospital = _hospital(beds=5)
    app.engine.update_hospital_info(hospital)
    client = app.app.test_client()
    base = GpsPoint(lat=37.5665, lng=126.9780)
    for apid in ("A1", "A2", "A3"):
        client.post("/info/ambulances", json=AmbulanceInfo(apid=apid, name=f"[테스트] {apid}", gps=base, voicePort=6000,
                                                          updatedAt="2026-10-04T00:00:00Z").model_dump())
    monitor = _FakeSocket()
    app._dashboard_sockets.add(monitor)
    app._handle_identify(monitor, DashboardIdentify(role="monitor", id="map"))

    def dispatch(apid: str, case_id: str) -> None:
        app._handle_sim_command({"type": "dispatch", "apid": apid, "caseId": case_id, "timestamp": "t",
                                 "target": {"lat": 37.5700, "lng": 126.9800}, "targetMode": "map"})

    def match(case_id: str) -> None:
        result = app.engine.process_voice_summary(
            VoiceCallSummaryMessage(caseId=case_id, transcript=VoiceTranscript(raw_text="t", filtered_text="t"),
                                    summary=VoiceSummary(patient="50대", mechanism="흉통", symptoms=[], treatment=[],
                                                         severity_tag="high"), source="ai"),
            GpsPoint(lat=37.5700, lng=126.9800))
        app._send_to_dashboard(result.model_dump())

    print("=== 구급차 셋: 이송 확정(A1) · 현장 매칭(A2) · 출동 중(A3) ===")
    for apid, case_id in (("A1", "c-confirmed"), ("A2", "c-scene"), ("A3", "c-dispatch")):
        dispatch(apid, case_id)
    clock.t += 10
    app._sim_tick()  # A1·A2·A3 모두 현장 도착
    match("c-confirmed")
    match("c-scene")
    for action, actor in (("hospital_approve", "hospital"), ("final_approval", "paramedic")):
        app._handle_dashboard_action({"caseId": "c-confirmed", "action": action, "hospital_id": hospital.hospitalId,
                                      "actor": actor, "timestamp": "2026-10-04T00:00:00Z"})
    assert app.sim.phase_of("A1") == "transporting", app.sim.phase_of("A1")
    # A3는 출동만 한 상태로 되돌려 둔다(현장 도착 전 사건)
    app.sim.reset("A3")
    dispatch("A3", "c-dispatch2")
    assert set(app.engine.list_open_case_ids()) >= {"c-confirmed", "c-scene", "c-dispatch2"}
    # 엔진엔 없는 사건의 흔적(2026-10-06 실서버에서 초기화 뒤에도 남아 새로 연 화면마다 다시 보내졌다) —
    # 매칭 전에 끝난 사건의 예비 고지, 이미 끝난 사건의 통화 상태
    app._pre_alerts["c-orphan"] = {"type": "pre_alert", "caseId": "c-orphan", "apid": "A2"}
    app._case_call["c-old-call"] = {"type": "call_status", "caseId": "c-old-call", "apid": "A3", "state": "ended"}

    print("=== [시연 초기화] → 세 사건 모두 닫힘, 구급차 전부 기지 대기 ===")
    monitor.sent.clear()
    app._handle_sim_command({"type": "sim_reset", "apid": "*", "timestamp": "t"})
    closed = {m["caseId"] for m in monitor.sent if m.get("type") == "case_closed"}
    assert {"c-confirmed", "c-scene", "c-dispatch2"} <= closed, closed
    assert app.engine.list_open_case_ids() == [], app.engine.list_open_case_ids()
    assert all(app.sim.phase_of(a) == "idle" for a in ("A1", "A2", "A3"))
    past = [m for m in monitor.sent if m.get("type") == "case_history"][-1]["cases"]
    assert {"c-confirmed", "c-scene"} <= {p["caseId"] for p in past}, "지난 사건에도 '시연 초기화'로 남는다"
    assert {"c-orphan", "c-old-call"} <= closed, "엔진 밖 사건 흔적도 화면에 case_closed로 알린다"
    assert "c-orphan" not in app._pre_alerts and "c-old-call" not in app._case_call
    print(f"  [확인] 닫힌 사건 {sorted(closed)}")

    print("=== 초기화 뒤 관제 지도를 새로 열어도 예비 고지·통화 상태가 따라오지 않는다 ===")
    monitor2 = _FakeSocket()
    app._dashboard_sockets.add(monitor2)
    app._handle_identify(monitor2, DashboardIdentify(role="monitor", id="map2"))
    stale = [m for m in monitor2.sent if m.get("type") in ("pre_alert", "call_status", "case_overview", "case_meta")]
    assert not stale, stale
    print("  [확인] 따라잡기 흔적 0건")

    print("=== 초기화 뒤 구급차 탭을 열어도 남은 사건이 따라오지 않는다 ===")
    amb = _FakeSocket()
    app._dashboard_sockets.add(amb)
    app._handle_identify(amb, DashboardIdentify(role="ambulance", id="A1"))
    assert "match_result" not in _types(amb), "닫힌 사건이 따라잡기로 오면 안 된다"
    sync = [m for m in amb.sent if m.get("type") == "case_sync"]
    assert not sync or sync[-1]["caseIds"] == [], sync
    print("  [확인] 따라잡기 사건 0건")

    print("=== [이 구급대 초기화] A2만 → A2 사건만 닫히고 A1은 그대로 ===")
    dispatch("A1", "c-u1")
    dispatch("A2", "c-u2")
    clock.t += 10
    app._sim_tick()
    match("c-u1")
    match("c-u2")
    app._pre_alerts["c-u2-pre"] = {"type": "pre_alert", "caseId": "c-u2-pre", "apid": "A2"}
    monitor.sent.clear()
    app._handle_sim_command({"type": "sim_reset", "apid": "A2", "timestamp": "t"})
    closed = {m["caseId"] for m in monitor.sent if m.get("type") == "case_closed"}
    assert {"c-u2", "c-u2-pre"} <= closed and "c-u1" not in closed, closed
    assert app.sim.phase_of("A2") == "idle" and app.sim.phase_of("A1") == "on_scene"
    assert "c-u1" in app.engine.list_open_case_ids() and "c-u2" not in app.engine.list_open_case_ids()
    assert "c-u2-pre" not in app._pre_alerts
    print(f"  [확인] 닫힌 사건 {sorted(closed)}, A1 사건 유지")
    print("\n모든 검사 통과")


if __name__ == "__main__":
    main()
