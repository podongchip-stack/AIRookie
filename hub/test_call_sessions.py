"""실제 양방향 통화(WebRTC) 세션 검사(2026-11-04) — 네트워크·실서버·운영 로그 없이 가짜 소켓으로 돈다.

1부(상태 기계): call_sessions.CallSessionManager를 가짜 시계로 — 정상 흐름, 거절·취소·시간 초과, busy·중복, 권한,
                늦은/중복 메시지, 신호 끊김·재접속, ICE 서버(TURN 만료형 자격 증명).
2부(app 연결): 실제 app 함수로 — 병원 앱(callCapable)에만 수신이 울리는지, call_status 연동, 시연 연출 통화와의 충돌 방지,
                사건이 닫히면 통화도 끝나는지.

    python test_call_sessions.py
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import random
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decision_log.jsonl")
os.environ["HOSPITAL_REJECTION_LOG_DIR"] = str(Path(_TMP.name) / "rejections")
os.environ["HUB_REJECTION_URL"] = "http://127.0.0.1:9/hub/rejection"

from call_sessions import CallSessionManager, ice_servers_for  # noqa: E402


class _Clock:
    t = 1_000.0

    def __call__(self) -> float:
        return self.t


def _types(outcome) -> list[tuple[str, str]]:
    return [(to, msg.get("type") + ":" + str(msg.get("state") or "")) for to, msg in outcome.sends]


def _manager(clock: _Clock) -> CallSessionManager:
    return CallSessionManager(clock=clock, ice_provider=lambda call_id: [{"urls": ["stun:test"]}],
                              ringing_sec=30, connecting_sec=15, grace_sec=10)


def _invite(m: CallSessionManager, call_id="c1", case_id="case1", apid="A1", hospital_id="H1", online=True, ws="amb-ws"):
    return m.invite(call_id=call_id, case_id=case_id, apid=apid, hospital_id=hospital_id, caller_ws=ws, hospital_online=online,
                    caller_name="구급 1호차", hospital_name="테스트병원")


def _connect(m: CallSessionManager, call_id="c1"):
    assert _invite(m, call_id).ok
    assert m.accept(call_id, "hospital", "H1", "hosp-ws").ok


def part1_state_machine() -> None:
    print("=== 1부: 정상 흐름 — 초대 → 받기 → 협상 → media_ready → 통화 중 → 종료 ===")
    clock = _Clock()
    m = _manager(clock)
    out = _invite(m)
    assert out.ok and ("caller", "call_state:ringing") in _types(out) and ("hospital:H1", "call_incoming:") in _types(out), _types(out)
    assert out.sends[0][1]["iceServers"] and out.sends[1][1]["iceServers"], "양쪽이 받는 첫 메시지에 ICE 서버가 실린다"
    out = m.accept("c1", "hospital", "H1", "hosp-ws")
    assert out.ok and m.get("c1").state == "connecting"
    assert ("caller", "call_state:connecting") in _types(out) and ("callee", "call_state:connecting") in _types(out)
    assert ("hospital_others:H1", "call_state:ended") in _types(out), "같은 병원의 다른 기기 수신 화면은 닫힌다"
    out = m.offer("c1", "ambulance", "A1", "amb-ws", "v=0 offer", 1)
    assert out.ok and out.sends[0][0] == "callee" and out.sends[0][1]["type"] == "rtc_offer"
    out = m.answer("c1", "hospital", "H1", "hosp-ws", "v=0 answer", 1)
    assert out.ok and out.sends[0][0] == "caller" and out.sends[0][1]["type"] == "rtc_answer"
    assert m.ice("c1", "ambulance", "A1", "amb-ws", {"candidate": "x"}, 1).sends[0][0] == "callee"
    assert m.ice("c1", "hospital", "H1", "hosp-ws", {"candidate": "y"}, 1).sends[0][0] == "caller"
    out = m.media_ready("c1", "ambulance", "A1", "amb-ws")
    assert out.ok and not out.changed and m.get("c1").state == "connecting", "한쪽만 준비되면 아직 통화 중이 아니다(받았다는 이유만으로 시작하지 않는다)"
    clock.t += 3
    out = m.media_ready("c1", "hospital", "H1", "hosp-ws")
    assert out.changed and m.get("c1").state == "active" and m.get("c1").started_at == clock.t
    assert m.media_ready("c1", "hospital", "H1", "hosp-ws").reason == "already_active", "중복 media_ready는 멱등"
    clock.t += 20
    out = m.hangup("c1", "hospital", "H1", "hosp-ws")
    assert out.changed and m.get("c1").state == "ended"
    reasons = {to: msg["reason"] for to, msg in out.sends}
    assert reasons == {"caller": "remote_hangup", "callee": "local_hangup"}, reasons
    again = m.hangup("c1", "ambulance", "A1", "amb-ws")
    assert again.ok and again.reason == "already_ended" and not again.sends and not again.changed, "종료 신호가 중복돼도 한 번만 처리"
    assert not m.ice("c1", "ambulance", "A1", "amb-ws", {"candidate": "late"}, 1).ok, "종료된 통화의 늦은 ICE는 버린다"
    synced = m.sync("ambulance", "A1", "amb-ws2", "c1").sends[0][1]
    assert synced["state"] == "ended" and synced["reason"] == "remote_hangup", "재접속한 발신 앱은 종료 사유를 자기 입장에서 받는다"
    print("  [확인] 정상 흐름, 한쪽 준비로는 시작 안 됨, 양쪽 종료 시 쪽별 사유, 중복·늦은 메시지 무시")

    print("=== 병원 기기 없음 · busy · 사건 중복 ===")
    out = _invite(m, "c2", case_id="case2", online=False)
    assert out.ok and m.get("c2").end_reason == "unavailable" and len(out.sends) == 1 and out.sends[0][0] == "caller"
    assert _invite(m, "c3", case_id="case3").ok and m.get("c3").state == "ringing"
    busy = _invite(m, "c4", case_id="case4")  # 같은 병원 H1에 다른 사건이 이미 ringing
    assert m.get("c4").end_reason == "busy" and busy.sends[0][1]["type"] == "call_busy", busy.sends
    assert _invite(m, "c5", case_id="case3", hospital_id="H2").reason == "case_busy", "같은 사건에 동시에 두 통화는 없다"
    assert _invite(m, "c3", case_id="case3").ok, "같은 초대 재전송은 새 통화를 만들지 않는다"
    assert _invite(m, "c3", case_id="other").reason == "duplicate_call_id"
    print("  [확인] unavailable(병원엔 안 울림), busy, case_busy, 초대 재전송 멱등")

    print("=== 거절 · 발신 취소 · 시간 초과 ===")
    m2 = _manager(clock)
    _invite(m2, "r1")
    assert m2.hangup("r1", "hospital", "H1", "hosp-ws").reason == "use_reject", "수신 대기 중 병원의 거부는 reject로"
    out = m2.reject("r1", "hospital", "H1", "hosp-ws")
    assert m2.get("r1").end_reason == "rejected" and out.changed
    _invite(m2, "r2")
    out = m2.hangup("r2", "ambulance", "A1", "amb-ws")
    assert m2.get("r2").end_reason == "caller_cancelled" and ("hospital:H1", "call_state:ended") in _types(out), "취소하면 병원 수신 화면이 닫힌다"
    late = m2.accept("r2", "hospital", "H1", "hosp-ws")
    assert not late.ok and late.reason == "not_ringing", "취소 뒤 늦은 받기는 무시"
    _invite(m2, "r3")
    clock.t += 31
    done = m2.tick()
    assert [d.session.call_id for d in done] == ["r3"] and m2.get("r3").end_reason == "no_answer"
    _connect(m2, "r4")
    clock.t += 16
    assert m2.tick()[0].session.end_reason == "connection_failed", "연결 협상 15초 초과"
    print("  [확인] rejected, caller_cancelled(병원 화면 닫힘), 늦은 받기 무시, no_answer 30초, connection_failed 15초")

    print("=== 권한 · 협상 세대 · 순서 ===")
    m3 = _manager(clock)
    _invite(m3, "p1")
    assert m3.accept("p1", "hospital", "H2", "x").reason == "forbidden", "지정되지 않은 병원은 받을 수 없다"
    assert m3.accept("p1", "ambulance", "A1", "x").reason == "forbidden"
    assert m3.media_ready("p1", "ambulance", "A1", "amb-ws").reason == "not_connecting", "받기 전 media_ready는 무시"
    assert m3.accept("p1", "hospital", "H1", "hosp-ws").ok
    assert m3.offer("p1", "hospital", "H1", "hosp-ws", "sdp", 1).reason == "forbidden", "offer는 발신 쪽만"
    assert m3.answer("p1", "ambulance", "A1", "amb-ws", "sdp", 1).reason == "forbidden", "answer는 수신 쪽만"
    assert m3.ice("p1", "ambulance", "A9", "amb-ws", {"c": 1}, 1).reason == "forbidden"
    assert m3.ice("p1", "hospital", "H1", "other-ws", {"c": 1}, 1).reason == "forbidden", "같은 병원 코드라도 자리에 묶이지 않은 소켓은 끼어들 수 없다"
    assert m3.media_ready("p1", "hospital", "H1", "other-ws").reason == "forbidden"
    assert m3.offer("p1", "ambulance", "A1", "amb-ws", "sdp1", 2).ok
    assert m3.ice("p1", "ambulance", "A1", "amb-ws", {"c": 1}, 1).reason == "stale", "지난 협상 세대의 ICE는 버린다"
    assert m3.answer("p1", "hospital", "H1", "hosp-ws", "sdp", 1).reason == "stale"
    assert m3.offer("p1", "ambulance", "A1", "amb-ws", "sdp0", 1).reason == "stale", "협상 세대는 거꾸로 가지 않는다"
    assert m3.hangup("p1", "ambulance", "A9", "x").reason == "forbidden", "제3자는 종료할 수 없다"
    print("  [확인] 역할·병원·기기 권한, 협상 세대(stale) 처리, 순서 위반 거부")

    print("=== 새 통화는 이전 통화의 늦은 신호에 영향받지 않는다 ===")
    m4 = _manager(clock)
    _connect(m4, "old")
    m4.hangup("old", "ambulance", "A1", "amb-ws")
    _connect(m4, "new")  # 같은 사건·병원에 재전화
    stale = m4.hangup("old", "hospital", "H1", "hosp-ws")  # 이전 통화의 종료 신호가 뒤늦게 도착
    assert stale.reason == "already_ended" and m4.get("new").state == "connecting", "이전 callId 종료가 새 통화를 끊으면 안 된다"
    print("  [확인] callId로 분리 — 이전 통화의 늦은 hangup이 새 통화에 영향 없음")

    print("=== 신호 끊김 · 재접속(call_state_sync) ===")
    m5 = _manager(clock)
    _connect(m5, "s1")
    m5.media_ready("s1", "ambulance", "A1", "amb-ws")
    m5.media_ready("s1", "hospital", "H1", "hosp-ws")
    m5.socket_closed("hosp-ws")
    assert m5.get("s1").state == "active" and m5.tick() == [], "신호가 끊겨도 곧바로 통화를 끝내지 않는다"
    clock.t += 5
    out = m5.sync("hospital", "H1", "hosp-ws-new", "s1")
    assert out.sends[0][1]["state"] == "active" and m5.get("s1").callee_ws == "hosp-ws-new"
    clock.t += 30
    assert m5.tick() == [], "유예 안에 돌아오면 이어진다"
    m5.socket_closed("hosp-ws-new")
    clock.t += 11
    done = m5.tick()
    assert done and done[0].session.end_reason == "network_timeout", "유예(10초) 안에 못 돌아오면 network_timeout"
    out = m5.sync("hospital", "H1", "hosp-ws-3", "s1")
    assert out.sends[0][1]["state"] == "ended" and out.sends[0][1]["reason"] == "network_timeout", "재접속 앱은 종료 사실을 받는다"
    assert m5.sync("hospital", "H1", "x", "없는-callId").sends[0][1]["state"] == "ended"
    m5b = _manager(clock)
    _invite(m5b, "s2")
    out = m5b.sync("hospital", "H1", "late-hosp-ws")  # 수신 대기 중에 병원 앱이 (재)접속 → 울리는 중인 전화를 받는다
    assert any(msg["type"] == "call_incoming" for _, msg in out.sends), out.sends
    assert m5b.get("s2").callee_ws is None, "받기 전엔 자리를 묶지 않는다(웹 대시보드가 가로채지 못하게)"
    print("  [확인] 끊겨도 유지·유예 안 복구·유예 초과 network_timeout·종료 사실 전달·수신 대기 중 재접속 시 다시 울림")

    print("=== 사건 닫힘 · ICE 서버 ===")
    m6 = _manager(clock)
    _connect(m6, "k1")
    out = m6.end_for_case("case1", "case_closed")
    assert out is not None and m6.get("k1").end_reason == "case_closed"
    assert m6.end_for_case("case1") is None
    assert ice_servers_for("cx", now=100, env={}) == [{"urls": ["stun:stun.l.google.com:19302"]}], "기본은 공개 STUN만"
    servers = ice_servers_for("cx", now=100, env={"HUB_TURN_URLS": "turn:t.example:3478,turns:t.example:5349", "HUB_TURN_SECRET": "s3cret",
                                                  "HUB_TURN_TTL_SEC": "600"})
    turn = servers[1]
    assert turn["urls"] == ["turn:t.example:3478", "turns:t.example:5349"] and turn["username"] == "700:cx"
    expected = base64.b64encode(hmac.new(b"s3cret", b"700:cx", hashlib.sha1).digest()).decode()
    assert turn["credential"] == expected, "coturn REST 방식(만료시각:callId, HMAC-SHA1)"
    assert "s3cret" not in str(servers), "비밀값은 응답에 실리지 않는다"
    print("  [확인] 사건 닫힘 시 통화 종료, 기본 STUN, TURN 만료형 자격 증명(비밀값 비노출)")


def part2_app_wiring() -> None:
    import app
    from ambulance_sim import DispatchSim
    from schema import AmbulanceInfo, DashboardIdentify, GpsPoint
    from test_app_background import _FakeSocket, _hospital

    class _SyncExecutor:
        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)

    print("=== 2부: app 연결 — 수신은 병원 앱에만, 통화 상태 연동, 시연 연출과의 충돌 방지 ===")
    app._match_executor = _SyncExecutor()
    sim_clock = [9000.0]
    app.sim = DispatchSim(None, random.Random(11), lambda: sim_clock[0], Path(_TMP.name) / "sim")
    clock = _Clock()
    app._call_manager = CallSessionManager(clock=clock, ringing_sec=30, connecting_sec=15, grace_sec=10)
    hospital = _hospital(beds=5)
    app.engine.update_hospital_info(hospital)
    app.app.test_client().post("/info/ambulances", json=AmbulanceInfo(
        apid="A_W", name="[테스트] 통화 구급차", gps=GpsPoint(lat=37.5665, lng=126.9780), voicePort=6000,
        updatedAt="2026-11-04T00:00:00Z").model_dump())
    amb, android, web = _FakeSocket(), _FakeSocket(), _FakeSocket()
    for sock in (amb, android, web):
        app._dashboard_sockets.add(sock)
    app._handle_identify(amb, DashboardIdentify(role="ambulance", id="A_W"))
    app._handle_identify(android, DashboardIdentify(role="hospital", id=hospital.hospitalId, callCapable=True))
    app._handle_identify(web, DashboardIdentify(role="hospital", id=hospital.hospitalId))

    case_id = "case-webrtc"
    app._handle_sim_command({"type": "dispatch", "apid": "A_W", "caseId": case_id, "timestamp": "t",
                             "target": {"lat": 37.5670, "lng": 126.9785}, "targetMode": "map"})
    sim_clock[0] += 10
    app._sim_tick()
    assert app.sim.phase_of("A_W") == "on_scene"

    def kinds(sock, type_):
        return [m for m in sock.sent if m.get("type") == type_]

    send = app._handle_call_session_message
    call_id = "call-1"
    send(amb, {"type": "call_invite", "callId": call_id, "caseId": case_id, "hospitalId": hospital.hospitalId})
    assert kinds(amb, "call_state")[-1]["state"] == "ringing" and kinds(amb, "call_state")[-1]["iceServers"]
    assert kinds(android, "call_incoming")[-1]["callId"] == call_id and kinds(android, "call_incoming")[-1]["ambulanceName"]
    assert not kinds(web, "call_incoming"), "같은 병원 코드의 웹 대시보드는 수신 기기가 아니다"
    assert app._case_call.get(case_id, {}).get("state") != "ringing", "ringing은 시연 연출 통화 상태(call_status)로 내보내지 않는다"

    print("=== 시연 연출 통화(call_connection)는 실제 통화 중인 사건에 걸리지 않는다 ===")
    app._handle_call_connection(amb, {"operation": "request", "caseId": case_id, "hospitalId": hospital.hospitalId, "requestId": "legacy-1"})
    assert app._case_call.get(case_id, {}).get("requestId") != "legacy-1"

    send(android, {"type": "call_accept", "callId": call_id})
    assert kinds(amb, "call_state")[-1]["state"] == "connecting" and kinds(android, "call_state")[-1]["state"] == "connecting"
    send(amb, {"type": "rtc_offer", "callId": call_id, "negotiationRevision": 1, "sdp": "offer-sdp"})
    assert kinds(android, "rtc_offer")[-1]["sdp"] == "offer-sdp"
    send(android, {"type": "rtc_answer", "callId": call_id, "negotiationRevision": 1, "sdp": "answer-sdp"})
    assert kinds(amb, "rtc_answer")[-1]["sdp"] == "answer-sdp"
    send(amb, {"type": "rtc_ice", "callId": call_id, "negotiationRevision": 1, "candidate": {"candidate": "c1", "sdpMid": "0"}})
    assert kinds(android, "rtc_ice")[-1]["candidate"]["candidate"] == "c1"
    ice_before = len(kinds(amb, "rtc_ice"))
    send(web, {"type": "rtc_ice", "callId": call_id, "negotiationRevision": 1, "candidate": {"candidate": "evil"}})
    send(web, {"type": "call_hangup", "callId": call_id})
    assert len(kinds(amb, "rtc_ice")) == ice_before and app._call_manager.get(call_id).state == "connecting",         "같은 병원 코드의 웹 대시보드는 통화에 끼어들 수 없다(ICE·종료 모두 무시)"
    send(amb, {"type": "media_ready", "callId": call_id})
    send(android, {"type": "media_ready", "callId": call_id})
    assert kinds(amb, "call_state")[-1]["state"] == "active" and kinds(amb, "call_state")[-1]["startedAt"]
    assert app._case_call[case_id]["state"] == "calling" and app._case_call[case_id]["webrtc"] is True, "병원 대시보드·관제 지도의 '통화 중' 표시"
    print("  [확인] 수신은 병원 앱에만, 협상 중계, 양쪽 준비 후 통화 중 + 기존 call_status(calling) 연동")

    clock.t += 42
    send(amb, {"type": "call_hangup", "callId": call_id})
    assert kinds(android, "call_state")[-1]["reason"] == "remote_hangup" and kinds(amb, "call_state")[-1]["reason"] == "local_hangup"
    assert app._case_call[case_id]["state"] == "ended"
    send(android, {"type": "call_hangup", "callId": call_id})  # 중복 종료
    assert "call_error" not in [m.get("type") for m in android.sent], "중복 종료는 오류가 아니다"
    send(android, {"type": "call_accept", "callId": call_id})
    assert kinds(android, "call_error")[-1]["reason"] == "not_ringing", "종료된 통화에 늦은 받기 — 앱이 수신 화면을 닫도록 오류를 돌려준다"
    print("  [확인] 종료 사유 쪽별, 통화 상태 ended, 중복 종료 무시, 늦은 받기 오류 통지")

    print("=== 권한: 남의 사건·모르는 병원·병원 기기 없음 ===")
    intruder = _FakeSocket()
    app._dashboard_sockets.add(intruder)
    app._handle_identify(intruder, DashboardIdentify(role="ambulance", id="OTHER"))
    send(intruder, {"type": "call_invite", "callId": "x1", "caseId": case_id, "hospitalId": hospital.hospitalId})
    assert kinds(intruder, "call_state")[-1]["detail"] == "not_owner"
    send(amb, {"type": "call_invite", "callId": "x2", "caseId": case_id, "hospitalId": "NO-SUCH"})
    assert kinds(amb, "call_state")[-1]["detail"] == "unknown_hospital"
    app._call_capable.discard(android)
    send(amb, {"type": "call_invite", "callId": "x3", "caseId": case_id, "hospitalId": hospital.hospitalId})
    assert kinds(amb, "call_state")[-1]["reason"] == "unavailable", "수신 가능한 병원 앱이 없으면 바로 알린다"
    app._call_capable.add(android)
    print("  [확인] not_owner·unknown_hospital 거부, 병원 앱 없으면 unavailable")

    print("=== 사건이 닫히면 실제 통화도 끝난다 ===")
    send(amb, {"type": "call_invite", "callId": "call-2", "caseId": case_id, "hospitalId": hospital.hospitalId})
    send(android, {"type": "call_accept", "callId": "call-2"})
    app._handle_sim_command({"type": "sim_reset", "apid": "A_W", "timestamp": "t"})
    assert app._call_manager.get("call-2").state == "ended" and app._call_manager.get("call-2").end_reason == "case_closed"
    assert kinds(android, "call_state")[-1]["reason"] == "case_closed"
    print("  [확인] 시연 초기화 → 통화 종료(case_closed)")

    print("=== 신호 소켓이 끊기면 유예 뒤 종료 ===")
    app._handle_sim_command({"type": "dispatch", "apid": "A_W", "caseId": "case-2", "timestamp": "t",
                             "target": {"lat": 37.5670, "lng": 126.9785}, "targetMode": "map"})
    sim_clock[0] += 10
    app._sim_tick()
    send(amb, {"type": "call_invite", "callId": "call-3", "caseId": "case-2", "hospitalId": hospital.hospitalId})
    send(android, {"type": "call_accept", "callId": "call-3"})
    app._call_manager.socket_closed(android)
    clock.t += 11
    for outcome in app._call_manager.tick():
        app._deliver_call(outcome)
    assert kinds(amb, "call_state")[-1]["reason"] == "network_timeout"
    print("  [확인] 병원 소켓 끊김 → 유예 초과 시 발신 앱에 network_timeout")
    print("\n모든 검사 통과")


if __name__ == "__main__":
    part1_state_machine()
    part2_app_wiring()
