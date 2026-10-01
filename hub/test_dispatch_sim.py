"""출동 시뮬레이션의 앱 레이어 검사(2026-10-01) — 실제 소켓·서버 없이 app 함수를 직접 부른다.

[이동] → 현장 도착(후보 전송·통화 시작 허용) → 매칭 → 병원 승인 → 이송 승인(병원으로 이동, 병원 탭도
위치를 받음) → 병원 도착 15초 → 기지 복귀(병원 탭은 안 받음) → 대기. 그리고 [현장 종료] 흐름.
시계는 가짜로 돌리고 카카오는 부르지 않는다(직선 이동).

    python test_dispatch_sim.py
"""
from __future__ import annotations

import os
import random
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")

import app  # noqa: E402
from ambulance_sim import HOSPITAL_DWELL_SEC, DispatchSim  # noqa: E402
from schema import AmbulanceInfo, CallSignal, GpsPoint, VoiceCallSummaryMessage, VoiceSummary, VoiceTranscript  # noqa: E402
from test_app_background import _FakeSocket, _hospital  # noqa: E402

_REJECTIONS: list[dict] = []
app.send_rejection_to_info = _REJECTIONS.append  # 거절 로그 수신구 대역(전송 내용만 모은다)

BASE = GpsPoint(lat=37.5665, lng=126.9780)


class _Clock:
    t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def _types(sock: _FakeSocket) -> list[str]:
    return [m.get("type") for m in sock.sent]


def _phases(sock: _FakeSocket) -> list[str]:
    return [m["phase"] for m in sock.sent if m.get("type") == "ambulance_phase"]


def _dispatch(case_id: str) -> None:
    app._handle_sim_command({"type": "dispatch", "apid": "A_SIM", "caseId": case_id, "timestamp": "2026-10-01T00:00:00Z"})


def main() -> None:
    clock = _Clock()
    app.sim = DispatchSim(None, random.Random(3), clock, Path(_TMP.name) / "sim")
    app._voice_addresses.clear()
    app.engine.update_hospital_info(_hospital(beds=3))
    far = _hospital(beds=3).model_copy(update={  # 존 1(0~5km) 밖 — 도착 후 수용 불가 때 존 확장으로 들어온다
        "hospitalId": "T_FAR", "name": "[테스트] 먼 병원", "gps": GpsPoint(lat=37.6400, lng=126.9780)})
    app.engine.update_hospital_info(far)
    client = app.app.test_client()
    client.post("/info/ambulances", json=AmbulanceInfo(
        apid="A_SIM", name="[테스트] 시뮬레이션 구급차", gps=BASE, voicePort=6000, updatedAt="2026-10-01T00:00:00Z",
    ).model_dump())

    amb, hosp, other, far_tab = _FakeSocket(), _FakeSocket(), _FakeSocket(), _FakeSocket()
    app._dashboard_sockets.update({amb, hosp, other, far_tab})
    app._socket_identity.update({amb: ("ambulance", "A_SIM"), hosp: ("hospital", "T001"), other: ("hospital", "ZZZ"),
                                 far_tab: ("hospital", "T_FAR")})

    print("=== [이동] → 출동, 현장 도착 전엔 통화 시작 거부 ===")
    case_id = "case-sim"
    _dispatch(case_id)
    assert _phases(amb) == ["dispatching"] and amb.sent[-1]["simulated"] is True and amb.sent[-1]["path"]
    assert app.engine.get_case_apid(case_id) == "A_SIM", "출동 때 사건을 구급차에 묶는다"
    _dispatch("case-other")
    assert app.sim.case_of("A_SIM") == case_id, "출동 중 재출동은 거부"
    app._relay_call_signal(CallSignal(signal="call_started", timestamp="t", apid="A_SIM", caseId=case_id))
    assert "scene_candidates" not in _types(amb), "현장 도착 전 통화 시작은 거부(후보도 안 보냄)"
    assert not hosp.sent, "병원 탭은 출동 단계 위치를 받지 않는다"
    print("  [확인] 출동 상태·경로 전송, 재출동·조기 통화 시작 거부")

    print("=== 현장 도착 → 위치 고정, 거리순 후보, 통화 시작 허용 ===")
    clock.t += 5.0
    app._sim_tick()
    assert "ambulance_position" in _types(amb), "움직이는 동안 위치를 보낸다"
    clock.t += 3600
    app._sim_tick()
    assert _phases(amb)[-1] == "on_scene" and "scene_candidates" in _types(amb)
    incident = app.sim.state("A_SIM")["incident"]
    gps, fallback = app._resolve_ambulance_gps(case_id)
    assert gps.model_dump() == incident and not fallback, "매칭은 현장 좌표 기준"
    amb.sent.clear()
    app._relay_call_signal(CallSignal(signal="call_started", timestamp="t", apid="A_SIM", caseId=case_id))
    assert "scene_candidates" in _types(amb), "현장에서는 통화 시작 허용"
    print("  [확인] 현장 도착 시 후보 전송, 매칭 GPS = 현장 좌표")

    print("=== 매칭 → 병원 승인 → 이송 승인 → 병원으로 이동 ===")
    app.engine.process_voice_summary(
        VoiceCallSummaryMessage(
            caseId=case_id, transcript=VoiceTranscript(raw_text="x", filtered_text="x"),
            summary=VoiceSummary(patient="50대 남성", mechanism="흉부 충격", symptoms=[], treatment=[], severity_tag="high"),
            source="ai",
        ),
        gps, max_zone=app.engine.resolve_start_zone(gps),
    )
    for action, actor in (("hospital_approve", "hospital"), ("final_approval", "paramedic")):
        app._handle_dashboard_action({"caseId": case_id, "action": action, "hospital_id": "T001",
                                      "actor": actor, "timestamp": "2026-10-01T00:01:00Z"})
    assert app.sim.phase_of("A_SIM") == "transporting" and "transporting" in _phases(hosp), "확정 병원 탭도 이송을 본다"
    assert "ambulance_phase" not in _types(other), "다른 병원 탭은 위치를 받지 않는다"
    assert app.engine.refresh_case(case_id, gps) is None, "확정된 사건은 재정렬하지 않는다"
    print("  [확인] 확정 → 이송, 확정 병원 탭만 위치 수신, 확정 사건 재정렬 중단")

    print("=== 병원 도착 → 결과를 고를 때까지 대기 → 도착 후 수용 불가 → 그 자리에서 존 확장 ===")
    app._handle_dashboard_action({"caseId": case_id, "action": "arrival_refused", "hospital_id": "T001",
                                  "actor": "hospital", "timestamp": "2026-10-01T00:10:00Z", "reason": "BEDS_FULL"})
    assert app.engine.get_case_status(case_id, "T001") == "confirmed", "도착 전 도착 결과는 hub가 거부한다"
    clock.t += 3600
    app._sim_tick()
    clock.t += 3600
    app._sim_tick()
    assert app.sim.phase_of("A_SIM") == "at_hospital", "도착 결과가 없으면 병원에서 계속 기다린다"
    assert "T_FAR" not in [h.hospitalId for h in app.engine.get_case_result(case_id).hospitals]
    _REJECTIONS.clear()
    app._handle_dashboard_action({"caseId": case_id, "action": "arrival_refused", "hospital_id": "T001",
                                  "actor": "hospital", "timestamp": "2026-10-01T00:20:00Z", "reason": "BEDS_FULL"})
    assert app.sim.phase_of("A_SIM") == "rerouting", "그 자리에서 재선택 대기"
    refusal = _REJECTIONS[0]
    assert refusal["stage"] == "arrival" and refusal["reasonCode"] == "BEDS_FULL" and "availableBedCountAtRequest" in refusal
    result = app.engine.get_case_result(case_id)
    assert {h.hospitalId: h.status for h in result.hospitals}["T001"] == "rejected"
    assert "T_FAR" in [h.hospitalId for h in result.hospitals], "승인 병원이 없으면 존을 넓혀 다시 요청"
    assert any(m.get("type") == "match_result" and m["caseId"] == case_id for m in far_tab.sent), \
        "넓어진 존의 병원 탭이 같은 환자 정보로 요청을 받는다(재통화 없음)"
    assert not any(r["reasonCode"] == "NO_RESPONSE" for r in _REJECTIONS), "사건이 안 끝났으니 무응답 기록은 아직"
    print("  [확인] 결과 대기, 수용 불가 → 재선택 대기 · 거절 로그(stage=arrival, 결정 시점 스냅샷) · 존 확장 · 새 병원 탭 수신")

    print("=== 새 병원 승인 → 이송 → 도착 수용 → 15초 → 기지 복귀(병원 탭은 안 받음) → 대기 ===")
    app._handle_dashboard_action({"caseId": case_id, "action": "hospital_approve", "hospital_id": "T_FAR",
                                  "actor": "hospital", "timestamp": "2026-10-01T00:21:00Z"})
    app._handle_dashboard_action({"caseId": case_id, "action": "final_approval", "hospital_id": "T_FAR",
                                  "actor": "paramedic", "timestamp": "2026-10-01T00:22:00Z"})
    assert app.sim.phase_of("A_SIM") == "transporting"
    clock.t += 3600
    app._sim_tick()
    app._handle_dashboard_action({"caseId": case_id, "action": "arrival_accepted", "hospital_id": "T_FAR",
                                  "actor": "hospital", "timestamp": "2026-10-01T00:40:00Z"})
    assert app.engine.get_case_result(case_id).arrival.result == "accepted"
    assert any(m.get("type") == "case_closed" and m["caseId"] == case_id for m in amb.sent), "수용 완료 → 화면에서 사건 지움"
    assert not app.engine.get_cases_for_apid("A_SIM") and not app.engine.get_cases_for_hospital("T_FAR"), \
        "수용이 끝난 사건은 따라잡기에서 빠진다"
    clock.t += HOSPITAL_DWELL_SEC + 1
    hosp.sent.clear()
    app._sim_tick()
    assert app.sim.phase_of("A_SIM") == "returning" and _phases(amb)[-1] == "returning"
    assert not hosp.sent, "복귀는 병원과 무관 — 병원 탭에 안 보낸다"
    clock.t += 3600
    app._sim_tick()
    assert app.sim.phase_of("A_SIM") == "idle" and app.engine.get_ambulance("A_SIM").gps == BASE
    print("  [확인] 15초 대기 후 복귀, 기지 도착 시 대기")

    print("=== [현장 종료] → 사건 닫고 바로 복귀 ===")
    case2 = "case-sim-end"
    _dispatch(case2)
    clock.t += 3600
    app._sim_tick()
    app._handle_sim_command({"type": "scene_end", "apid": "A_SIM", "caseId": case2, "timestamp": "2026-10-01T00:05:00Z"})
    assert app.sim.phase_of("A_SIM") == "returning" and "case_closed" in _types(amb)
    print("  [확인] 현장 종료 → case_closed 전송, 복귀")

    print("=== 지정 위치 출동(주소 검색·지도 클릭) ===")
    clock.t += 3600
    app._sim_tick()  # 복귀 완료
    picked = {"lat": 37.5512, "lng": 126.9882}
    app._handle_sim_command({"type": "dispatch", "apid": "A_SIM", "caseId": "case-sim-target",
                             "timestamp": "2026-10-01T00:30:00Z", "target": picked, "targetMode": "map"})
    state = app.sim.state("A_SIM")
    assert state["phase"] == "dispatching" and state["incident"] == picked, "지정 위치로 출동"
    assert state["etaSec"] / state["speedup"] <= 90 + 1e-6, "화면 이동 시간은 상한(90초) 안"
    print("  [확인] 지정 위치로 출동, 구간 배속 자동 조정")

    app._dashboard_sockets.difference_update({amb, hosp, other})
    print("\n모든 검사 통과")


if __name__ == "__main__":
    main()
