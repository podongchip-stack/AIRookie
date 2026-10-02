"""관제 지도(role=monitor, 2026-10-03) 앱 레이어 검사.

병원 대시보드는 직접 접속하지 않고 관제 지도에서 환자 요청이 온 병원을 눌러 연다. 지도는 전체 병원·구급차 위치,
사건 요약(통화 전문 등 환자 상세 없이), 구급차 이동을 받고, 거절 비율로 존이 넓혀지면 바깥 존 병원이 사건 요약에
새로 들어온다.

실행: python test_monitor_map.py — 실제 상태·의사결정 로그·거절 로그는 건드리지 않는다(임시 경로로 돌린다).
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
os.environ["HUB_REJECTION_URL"] = "http://127.0.0.1:9/hub/rejection"  # 수신구 없음 — 조용히 흡수된다

import app  # noqa: E402
from ambulance_sim import DispatchSim  # noqa: E402
from schema import (  # noqa: E402
    AmbulanceInfo, DashboardIdentify, GpsPoint, VoiceCallSummaryMessage, VoiceSummary, VoiceTranscript,
)
from test_app_background import _FakeSocket, _hospital  # noqa: E402

SECRET = "통화 원문 — 관제 지도로 나가면 안 됨"


def _types(sock: _FakeSocket) -> list[str]:
    return [m.get("type") for m in sock.sent]


def _last(sock: _FakeSocket, type_: str) -> dict:
    return [m for m in sock.sent if m.get("type") == type_][-1]


def main() -> None:
    app.sim = DispatchSim(None, random.Random(5), pool_dir=Path(_TMP.name) / "sim")
    near = _hospital(beds=3)  # 서울시청 근처(존 1)
    far = near.model_copy(update={"hospitalId": "T_FAR", "name": "[테스트] 먼 병원", "gps": GpsPoint(lat=37.6400, lng=126.9780)})
    app.engine.update_hospital_info(near)
    app.engine.update_hospital_info(far)
    client = app.app.test_client()
    client.post("/info/ambulances", json=AmbulanceInfo(
        apid="A_MAP", name="[테스트] 관제 구급차", gps=GpsPoint(lat=37.5665, lng=126.9780), voicePort=6000,
        updatedAt="2026-10-03T00:00:00Z").model_dump())

    monitor, amb, hosp = _FakeSocket(), _FakeSocket(), _FakeSocket()
    app._dashboard_sockets.update({monitor, amb, hosp})

    print("=== 관제 지도 연결 → 신원·전체 병원/구급차 목록·구급차 상태 ===")
    app._handle_identify(monitor, DashboardIdentify(role="monitor", id="map"))
    app._handle_identify(amb, DashboardIdentify(role="ambulance", id="A_MAP"))
    app._handle_identify(hosp, DashboardIdentify(role="hospital", id=near.hospitalId))
    info = _last(monitor, "identity_info")
    assert info["known"] and info["role"] == "monitor"
    overview = _last(monitor, "map_overview")
    assert {h["hospitalId"] for h in overview["hospitals"]} >= {near.hospitalId, "T_FAR"}
    assert [a["apid"] for a in overview["ambulances"]] == ["A_MAP"] and overview["simDispatch"]
    assert "ambulance_phase" in _types(monitor), "연결 때 구급차 시뮬레이션 상태도 받는다"
    print("  [확인] 병원 2곳·구급차 1대·구급차 상태 수신")

    print("=== 매칭 결과 → 관제 지도엔 요약만(환자 상세 없음), 구급차·병원 탭엔 전체 ===")
    case_id = "case-monitor"
    app.engine.register_case(case_id, "A_MAP")
    result = app.engine.process_voice_summary(
        VoiceCallSummaryMessage(
            caseId=case_id, transcript=VoiceTranscript(raw_text=SECRET, filtered_text=SECRET),
            summary=VoiceSummary(patient="50대 남성", mechanism="흉부 충격", symptoms=[], treatment=[], severity_tag="high"),
            source="ai",
        ),
        GpsPoint(lat=37.5665, lng=126.9780),
    )
    app._send_to_dashboard(result.model_dump())
    case = _last(monitor, "case_overview")
    assert "match_result" not in _types(monitor), "관제 지도는 매칭 결과 원본을 받지 않는다"
    assert SECRET not in str(monitor.sent), "통화 전문이 관제 지도로 나가면 안 된다"
    assert case["caseId"] == case_id and case["apid"] == "A_MAP" and case["severityTag"] == "high"
    assert [h["hospitalId"] for h in case["hospitals"]] == [near.hospitalId] and case["hospitals"][0]["zone"] == 1
    assert case["zoneActive"] == [1] and case["zoneBandKm"] == 5.0
    assert "match_result" in _types(amb) and "match_result" in _types(hosp)
    print("  [확인] 사건 요약(존 1, 근처 병원 1곳) — 통화 전문 없음")

    print("=== 병원 거절 → 거절 비율로 존 확장 → 바깥 존 병원이 요약에 들어온다 ===")
    monitor.sent.clear()
    app._handle_dashboard_action({
        "caseId": case_id, "action": "hospital_reject", "hospital_id": near.hospitalId, "actor": "hospital",
        "timestamp": "2026-10-03T00:01:00Z", "reason": "BEDS_FULL",
    })
    case = _last(monitor, "case_overview")
    statuses = {h["hospitalId"]: (h["status"], h["zone"]) for h in case["hospitals"]}
    assert statuses[near.hospitalId] == ("rejected", 1), statuses
    assert statuses.get("T_FAR", (None, 0))[1] == 2 and max(case["zoneActive"]) == 2, case
    print(f"  [확인] 존 {case['zoneActive']} — 먼 병원(존 2) 추가, 거절 병원 상태 rejected")

    print("=== 구급차 이동·사건 종료·병원 목록 갱신도 관제 지도로 ===")
    monitor.sent.clear()
    app.sim.dispatch("A_MAP", "case-move", GpsPoint(lat=37.5700, lng=126.9900))
    app._broadcast_sim_state("A_MAP")
    assert _last(monitor, "ambulance_phase")["phase"] == "dispatching"
    app._close_case(case_id, "scene_ended")
    assert _last(monitor, "case_closed")["caseId"] == case_id
    client.post("/info/hospitals/roster", json={"hospitalIds": [near.hospitalId, "T_FAR"]})
    assert "map_overview" in _types(monitor), "병원 목록 한 주기가 끝나면 지도 목록을 다시 보낸다"
    print("  [확인] 구급차 상태·case_closed·map_overview 수신")
    print("모든 검사 통과")


if __name__ == "__main__":
    main()
