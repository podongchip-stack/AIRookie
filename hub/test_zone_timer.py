"""시간 기반 존 확장 · 건너뛰기 · 이송 빨리감기 검사(2026-10-04) — 실제 서버·로그 없이 app 함수를 직접 부른다.

- 요청이 나간 뒤 30초 동안 승인·확정 병원이 없으면 존을 한 단계 넓힌다(거절 비율과 별개)
- 시연 콘솔 [건너뛰기]는 기다리지 않고 바로 넓힌다
- 더 넓힐 수 없으면 타이머가 멈추고, 승인 병원이 생겨도 멈춘다(관제 지도의 다음 확장 시각이 사라진다)
- 이송 구간은 30초, [빨리감기]는 남은 이동을 3초 안에 마친다

    python test_zone_timer.py
"""
from __future__ import annotations

import os
import random
import tempfile
import time
from datetime import datetime
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decision_log.jsonl")
os.environ["HOSPITAL_REJECTION_LOG_DIR"] = str(Path(_TMP.name) / "rejections")
os.environ["HUB_REJECTION_URL"] = "http://127.0.0.1:9/hub/rejection"

import app  # noqa: E402
from ambulance_sim import FAST_FORWARD_SEC, TRANSPORT_SEC, DispatchSim, Trip  # noqa: E402
from schema import DashboardIdentify, GpsPoint, VoiceCallSummaryMessage, VoiceSummary, VoiceTranscript  # noqa: E402
from test_app_background import _FakeSocket, _hospital  # noqa: E402


class _SyncExecutor:
    """작업 스레드 대신 바로 실행(검사가 결과를 바로 보게)."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


def _last(sock: _FakeSocket, type_: str) -> dict:
    return [m for m in sock.sent if m.get("type") == type_][-1]


def main() -> None:
    app.sim = None
    app._match_executor = _SyncExecutor()
    near = _hospital(beds=3)  # 존 1
    mid = near.model_copy(update={"hospitalId": "T_MID", "name": "[테스트] 존2 병원", "gps": GpsPoint(lat=37.6400, lng=126.9780)})
    far = near.model_copy(update={"hospitalId": "T_FAR", "name": "[테스트] 존3 병원", "gps": GpsPoint(lat=37.6800, lng=126.9780)})
    for h in (near, mid, far):
        app.engine.update_hospital_info(h)
    monitor = _FakeSocket()
    app._dashboard_sockets.add(monitor)
    app._handle_identify(monitor, DashboardIdentify(role="monitor", id="map"))

    case_id = "case-zone-timer"
    app.engine.register_case(case_id, "A_NONE")
    result = app.engine.process_voice_summary(
        VoiceCallSummaryMessage(
            caseId=case_id, transcript=VoiceTranscript(raw_text="t", filtered_text="t"),
            summary=VoiceSummary(patient="50대 남성", mechanism="흉통", symptoms=[], treatment=[], severity_tag="high"),
            source="ai",
        ),
        GpsPoint(lat=37.5665, lng=126.9780),
    )
    start = time.time()
    app._send_to_dashboard(result.model_dump())

    print("=== 요청 직후: 다음 자동 확장 시각이 30초 뒤로 잡힌다 ===")
    case = _last(monitor, "case_overview")
    assert case["zoneActive"] == [1] and case["zoneExpandAt"], case
    print(f"  [확인] 다음 확장 {case['zoneExpandAt']}")

    print("=== 29초엔 그대로, 31초가 지나면 존 1 → 2 ===")
    app._zone_timer_tick(start + app.ZONE_EXPAND_SEC - 1)
    assert max(_last(monitor, "case_overview")["zoneActive"]) == 1
    app._zone_timer_tick(start + app.ZONE_EXPAND_SEC + 1)
    case = _last(monitor, "case_overview")
    assert max(case["zoneActive"]) == 2 and "T_MID" in {h["hospitalId"] for h in case["hospitals"]}, case
    assert any("30초 동안 수용 병원 없음 · 존 1~2로" in e["text"] for e in case["events"]), case["events"]
    assert case["zoneExpandAt"], "확장 뒤 타이머가 새로 돈다"
    print("  [확인] 시간 확장 — 진행 과정에 '30초 동안 수용 병원 없음'")

    print("=== [건너뛰기] → 바로 존 3, 더 넓힐 곳이 없으면 타이머 멈춤 ===")
    app._expand_case_zone(case_id, "manual")
    case = _last(monitor, "case_overview")
    assert max(case["zoneActive"]) == 3 and any("관제 건너뛰기" in e["text"] for e in case["events"]), case
    app._expand_case_zone(case_id, "manual")  # 존 3 바깥엔 병원이 없다(상한)
    case = _last(monitor, "case_overview")
    assert max(case["zoneActive"]) == 3 and case["zoneExpandAt"] is None, "넓힐 수 없으면 카운트다운이 사라진다"
    print("  [확인] 건너뛰기 확장, 상한에서 멈춤")

    print("=== 승인 병원이 생기면 자동 확장은 멈춘다 ===")
    with app._zone_timer_lock:
        app._zone_timer[case_id]["ok"] = True  # 다시 넓힐 수 있는 상태로 되돌려 승인 효과만 본다
    app._handle_dashboard_action({"caseId": case_id, "action": "hospital_approve", "hospital_id": near.hospitalId,
                                  "actor": "hospital", "timestamp": "2026-10-04T00:00:00Z"})
    case = _last(monitor, "case_overview")
    assert case["zoneExpandAt"] is None, case
    app._zone_timer_tick(time.time() + 999)
    assert max(_last(monitor, "case_overview")["zoneActive"]) == 3, "승인 병원이 있으면 시간이 지나도 안 넓힌다"
    print("  [확인] 승인 후 자동 확장 멈춤")

    print("=== [정지] 중엔 존 확장 시간도 멈추고, [상황 재개]하면 남은 시간부터 ===")
    clock = [9000.0]
    app.sim = DispatchSim(None, random.Random(2), lambda: clock[0], Path(_TMP.name) / "sim-pause")
    from schema import AmbulanceInfo
    app.app.test_client().post("/info/ambulances", json=AmbulanceInfo(
        apid="A_P", name="[테스트] 정지 구급차", gps=GpsPoint(lat=37.5665, lng=126.9780), voicePort=6000,
        updatedAt="2026-10-04T00:00:00Z").model_dump())
    pause_case = "case-pause"
    app._handle_sim_command({"type": "dispatch", "apid": "A_P", "caseId": pause_case, "timestamp": "t",
                             "target": {"lat": 37.5670, "lng": 126.9785}, "targetMode": "map"})
    clock[0] += 10
    app._sim_tick()
    assert app.sim.phase_of("A_P") == "on_scene"
    result = app.engine.process_voice_summary(
        VoiceCallSummaryMessage(caseId=pause_case, transcript=VoiceTranscript(raw_text="t", filtered_text="t"),
                                summary=VoiceSummary(patient="50대", mechanism="흉통", symptoms=[], treatment=[],
                                                     severity_tag="high"), source="ai"),
        GpsPoint(lat=37.5670, lng=126.9785))
    app._send_to_dashboard(result.model_dump())
    with app._zone_timer_lock:
        app._zone_timer[pause_case]["since"] -= 20  # 이미 20초 흘렀다고 치자 → 남은 10초
    app._handle_sim_command({"type": "sim_pause", "apid": "A_P", "caseId": pause_case, "timestamp": "t"})
    case = [m for m in monitor.sent if m.get("type") == "case_overview" and m["caseId"] == pause_case][-1]
    assert case["zoneExpandAt"] is None and case["zonePausedLeftSec"] == 10, case
    zone_before = max(case["zoneActive"])
    app._zone_timer_tick(time.time() + 600)  # 정지 중엔 10분이 지나도
    case = [m for m in monitor.sent if m.get("type") == "case_overview" and m["caseId"] == pause_case][-1]
    assert max(case["zoneActive"]) == zone_before, "정지 중엔 시간이 흐르지 않아 확장되지 않는다"
    app._handle_sim_command({"type": "sim_resume", "apid": "A_P", "caseId": pause_case, "timestamp": "t"})
    case = [m for m in monitor.sent if m.get("type") == "case_overview" and m["caseId"] == pause_case][-1]
    left = (datetime.fromisoformat(case["zoneExpandAt"]).timestamp() - time.time())
    assert case["zonePausedLeftSec"] is None and 8 <= left <= 11, (case, left)
    app._zone_timer_tick(time.time() + 11)
    case = [m for m in monitor.sent if m.get("type") == "case_overview" and m["caseId"] == pause_case][-1]
    assert max(case["zoneActive"]) > zone_before, "재개 뒤 남은 10초가 지나면 확장"
    print(f"  [확인] 정지 중 남은 10초 유지 → 재개 후 {left:.0f}초 뒤 확장")
    app.sim = None

    print("=== 이송 30초 · [빨리감기]는 남은 이동을 3초 안에 ===")
    trip = Trip([(37.5, 127.0), (37.6, 127.0)], duration_sec=600, started_at=1000.0, speedup=600 / TRANSPORT_SEC)
    assert abs(trip.progress(1000 + TRANSPORT_SEC / 2) - 0.5) < 1e-9 and not trip.done(1000 + TRANSPORT_SEC - 1)
    trip.fast_forward(1010.0, FAST_FORWARD_SEC)
    p = trip.progress(1010.0)
    assert abs(p - 10 / TRANSPORT_SEC) < 1e-9, "빨리감기해도 지금 위치는 그대로"
    assert not trip.done(1010.0 + FAST_FORWARD_SEC - 0.1) and trip.done(1010.0 + FAST_FORWARD_SEC)

    clock = [5000.0]
    sim = DispatchSim(None, random.Random(1), lambda: clock[0], Path(_TMP.name) / "sim")
    sim.ensure_unit("A1", GpsPoint(lat=37.55, lng=126.97))
    assert sim.fast_forward("A1") == (False, "phase_idle"), "이송 중이 아니면 거부"
    sim.dispatch("A1", "c1", GpsPoint(lat=37.56, lng=126.98))
    clock[0] += 10
    sim.tick()
    assert sim.phase_of("A1") == "on_scene"
    sim.on_confirmed("A1", "c1", "H1", GpsPoint(lat=37.60, lng=127.00))
    clock[0] += 5
    sim.tick()
    assert sim.phase_of("A1") == "transporting", "이송은 30초 — 5초 뒤엔 아직 가는 중"
    assert sim.fast_forward("A1") == (True, "ok")
    clock[0] += FAST_FORWARD_SEC + 0.01
    sim.tick()
    assert sim.phase_of("A1") == "at_hospital", "빨리감기 3초 뒤 병원 도착"
    print(f"  [확인] 이송 {TRANSPORT_SEC:g}초, 빨리감기 {FAST_FORWARD_SEC:g}초 안에 도착")
    print("\n모든 검사 통과")


if __name__ == "__main__":
    main()
