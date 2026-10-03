"""중앙 voice·휴대폰 통화(2026-10-03) 앱 레이어 검사.

voice 서버 한 대(중앙 모드)가 hub에 등록하면, 구급차 대시보드(휴대폰·태블릿)의 통화 시작·음성·종료가 hub를 거쳐
그 voice로 간다. 휴대폰 통화 화면에서 고른 병원에는 "통화 중"(call_status)이 뜨고, 첫 통화 병원이 기록된다.
가짜 voice 서버(127.0.0.1:임의 포트)를 띄워 hub가 실제로 보내는 HTTP 요청을 받아 본다.

실행: python test_central_voice.py — 실제 상태·의사결정 로그·거절 로그는 건드리지 않는다(임시 경로).
"""
from __future__ import annotations

import json
import os
import random
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
DECISION_LOG = Path(_TMP.name) / "decision_log.jsonl"  # test_app_background import가 환경변수를 덮어쓰므로 미리 잡아 둔다
os.environ["HUB_DECISION_LOG_PATH"] = str(DECISION_LOG)
os.environ["HOSPITAL_REJECTION_LOG_DIR"] = str(Path(_TMP.name) / "rejections")
os.environ["HUB_REJECTION_URL"] = "http://127.0.0.1:9/hub/rejection"

import app  # noqa: E402
from ambulance_sim import DispatchSim  # noqa: E402
from schema import AmbulanceInfo, CallSignal, DashboardIdentify, GpsPoint  # noqa: E402
from test_app_background import _FakeSocket, _hospital  # noqa: E402

RECEIVED: list[tuple[str, object]] = []


class _FakeVoice(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.endswith("/audio"):
            RECEIVED.append((self.path, len(body)))
        else:
            RECEIVED.append((self.path, json.loads(body or b"{}")))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


def _types(sock: _FakeSocket) -> list[str]:
    return [m.get("type") for m in sock.sent]


def _last(sock: _FakeSocket, type_: str) -> dict:
    return [m for m in sock.sent if m.get("type") == type_][-1]


def _wait(cond, sec: float = 5.0) -> bool:
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def main() -> None:
    voice = ThreadingHTTPServer(("127.0.0.1", 0), _FakeVoice)
    threading.Thread(target=voice.serve_forever, daemon=True).start()
    port = voice.server_address[1]

    app.sim = DispatchSim(None, random.Random(9), pool_dir=Path(_TMP.name) / "sim")
    near = _hospital(beds=3)
    other = near.model_copy(update={"hospitalId": "T_OTHER", "name": "[테스트] 다른 병원",
                                    "gps": GpsPoint(lat=37.5690, lng=126.9810)})
    app.engine.update_hospital_info(near)
    app.engine.update_hospital_info(other)
    client = app.app.test_client()
    client.post("/info/ambulances", json=AmbulanceInfo(
        apid="A_CALL", name="[테스트] 통화 구급차", gps=GpsPoint(lat=37.5665, lng=126.9780), voicePort=6001,
        updatedAt="2026-10-03T00:00:00Z").model_dump())

    print("=== 중앙 voice 등록 ===")
    r = client.post("/voice/register", json={"central": True, "ip": "127.0.0.1", "port": port})
    assert r.status_code == 200 and app._central_voice_url() == f"http://127.0.0.1:{port}"
    assert client.post("/voice/register", json={"ip": "1.2.3.4"}).status_code == 400, "구급차별 등록엔 apid 필요"
    print(f"  [확인] 중앙 voice http://127.0.0.1:{port} 등록")

    phone, tablet, hosp, other_hosp, monitor = (_FakeSocket() for _ in range(5))
    app._dashboard_sockets.update({phone, tablet, hosp, other_hosp, monitor})
    for sock, role, id_ in ((phone, "ambulance", "A_CALL"), (tablet, "ambulance", "A_CALL"),
                            (hosp, "hospital", near.hospitalId), (other_hosp, "hospital", "T_OTHER"),
                            (monitor, "monitor", "map")):
        app._handle_identify(sock, DashboardIdentify(role=role, id=id_))

    # 현장 도착 상태로 만든다(출동 시뮬레이션 규칙: 현장에서만 통화)
    case_id = "case-phone-call"
    app.sim.ensure_unit("A_CALL", GpsPoint(lat=37.5665, lng=126.9780))
    unit = app.sim._units["A_CALL"]
    unit.phase, unit.case_id, unit.incident = "on_scene", case_id, GpsPoint(lat=37.5665, lng=126.9780)
    app.engine.register_case(case_id, "A_CALL")
    app._case_recommended[case_id] = "T_OTHER"  # 추천과 다른 병원을 고른 상황

    print("=== 대시보드 통화가 꺼져 있으면(기본) 태블릿 통화 시작은 거부 ===")
    assert app.DASHBOARD_CALL is False
    app._relay_call_signal(CallSignal(signal="call_started", timestamp="2026-10-03T00:59:00Z", apid="A_CALL",
                                      caseId=case_id, device="tablet"), tablet)
    assert not any(path == "/call/start" for path, _ in RECEIVED) and "call_status" not in _types(tablet)
    print("  [확인] 태블릿 통화 시작 거부(voice로 안 감, 통화 상태 없음)")

    print("=== 휴대폰에서 병원을 골라 통화 시작 → 중앙 voice + 통화 상태 ===")
    app._relay_call_signal(CallSignal(signal="call_started", timestamp="2026-10-03T01:00:00Z", apid="A_CALL",
                                      caseId=case_id, hospitalId=near.hospitalId, device="phone"), phone)
    start = next(body for path, body in RECEIVED if path == "/call/start")
    assert start["caseId"] == case_id and start["apid"] == "A_CALL" and start["hospitalId"] == near.hospitalId
    for sock in (phone, tablet, hosp, monitor):
        status = _last(sock, "call_status")
        assert status["state"] == "calling" and status["hospitalId"] == near.hospitalId and status["device"] == "phone"
    assert "call_status" not in _types(other_hosp), "전화 걸지 않은 병원 탭은 통화 상태를 받지 않는다"
    log = [json.loads(line) for line in DECISION_LOG.read_text(encoding="utf-8").splitlines()]
    chosen = [e for e in log if e["eventType"] == "first_call_selected"][-1]["payload"]
    assert chosen["hospitalId"] == near.hospitalId and chosen["followedRecommendation"] is False
    print("  [확인] voice /call/start, 휴대폰·태블릿·고른 병원·관제 지도에 통화 중, 다른 병원 X, 첫 통화 기록")

    print("=== 통화 중에 연 병원 탭도 '통화 중'을 받는다 ===")
    late = _FakeSocket()
    app._dashboard_sockets.add(late)
    app._handle_identify(late, DashboardIdentify(role="hospital", id=near.hospitalId))
    assert _last(late, "call_status")["state"] == "calling"
    print("  [확인] 늦게 연 병원 탭 통화 상태 수신")

    print("=== 휴대폰 음성 → 그 사건으로 voice에 전달, 다른 소켓 음성은 버림 ===")
    second = bytes(3200)  # 0.1초 분량
    for _ in range(5):
        app._handle_audio_frame(phone, second)
    app._handle_audio_frame(tablet, second)  # 태블릿은 이 통화에 묶이지 않았다 — 버린다
    assert _wait(lambda: sum(n for p, n in RECEIVED if p.endswith("/audio")) == 5 * 3200), RECEIVED
    assert all(p == f"/call/{case_id}/audio" for p, _ in RECEIVED if p.endswith("/audio"))
    print("  [확인] 0.5초 분량(16,000바이트) 전달, 태블릿 음성은 버림")

    print("=== 통화 종료 → 남은 음성을 다 보낸 뒤 /call/end, 통화 상태 ended ===")
    app._handle_audio_frame(phone, second)  # 종료 직전 마지막 음성
    app._relay_call_signal(CallSignal(signal="call_ended", timestamp="2026-10-03T01:01:00Z", apid="A_CALL",
                                      caseId=case_id, device="phone"), phone)
    assert _wait(lambda: any(p == "/call/end" for p, _ in RECEIVED))
    paths = [p for p, _ in RECEIVED]
    assert paths.index("/call/end") > max(i for i, p in enumerate(paths) if p.endswith("/audio")), "종료는 마지막 음성 뒤"
    assert sum(n for p, n in RECEIVED if p.endswith("/audio")) == 6 * 3200
    assert _last(hosp, "call_status")["state"] == "ended" and _last(phone, "call_status")["state"] == "ended"
    assert phone not in app._socket_call
    print("  [확인] 마지막 음성까지 전달 후 종료 신호, 통화 상태 ended")

    print("=== 중앙 voice 등록이 오래되면(꺼짐) 구급차별 voice 방식으로 돌아간다 ===")
    app._central_voice["seenAt"] = time.monotonic() - app.CENTRAL_VOICE_STALE_SEC - 1
    assert app._central_voice_url() is None
    print("  [확인] 등록 90초 초과 → 중앙 voice 사용 안 함")

    app._close_case(case_id, "scene_ended")
    assert case_id not in app._case_call
    voice.shutdown()
    print("모든 검사 통과")


if __name__ == "__main__":
    main()
