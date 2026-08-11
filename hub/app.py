"""hub_engine.py 위에 얹는 HTTP/WebSocket 레이어. 매칭 로직(hub_engine.py)과
승인 처리(decision_log.py, delivery.py)는 손대지 않고 그대로 재사용한다 — 이
파일은 요청을 받아 파싱하고 엔진을 호출한 뒤 결과를 돌려주는 역할만 한다
(CLAUDE.md "모델/API 호출부와 비즈니스 로직은 분리해서 구현한다" 원칙).

여러 사건(구급차)이 동시에 진행될 수 있다. dashboard 연결은 여러 개(구급차
대시보드 여러 개 + 병원 대시보드 여러 개)를 동시에 유지하고 전체에
브로드캐스트하며, voice는 구급차마다 별도 장비에서 뜨므로 apid로 구분해
주소를 따로 관리한다. 사건별 상태 분리는 hub_engine.py의 caseId 키 구조를
그대로 따른다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, request
from flask_sock import Sock
from pydantic import ValidationError

from delivery import deliver, deliver_bed_update
from hub_engine import HubEngine
from schema import (
    AmbulanceInfo,
    ApprovalAction,
    CallSignal,
    GpsPoint,
    HospitalInfo,
    VoiceCallSummaryMessage,
    VoiceRegistration,
)

app = Flask(__name__)
app.json.ensure_ascii = False  # 한글 필드를 유니코드 이스케이프 없이 그대로 응답
sock = Sock(app)
engine = HubEngine()

# dashboard는 순수 WebSocket 클라이언트(new WebSocket(), socket.io 아님)라
# flask-sock(순수 WS)으로 받는다. 구급차 대시보드 여러 개 + 병원 대시보드
# 여러 개가 동시에 붙을 수 있어 연결을 집합으로 관리하고 전체에 브로드캐스트한다
# (예전엔 전역 변수 하나라 마지막 연결만 갱신을 받는 버그가 있었다).
_dashboard_sockets: set = set()

# apid별 voice 주소. voice가 뜰 때 자기 IP를 자동 탐지해 /voice/register로
# 알려주면 여기 저장해두고(포트는 AmbulanceInfo.voicePort로 이미 앎), 통화
# 시작/종료 신호를 그 구급차의 voice로 중계할 때 쓴다. 구급차 노트북마다
# 네트워크(와이파이/핫스팟)가 달라 IP가 자주 바뀔 수 있어, Supabase 등에
# 고정 저장하지 않고 이렇게 런타임에만 들고 있는다.
_voice_addresses: dict[str, str] = {}

# 사건이 apid로 등록되지 않은 채(테스트 등으로 CallSignal 없이 직접
# /voice/summary가 오는 경우) 도착하면 이 좌표로 대체한다. 병원이 전부
# 서울이라 존(zone) 밖으로 걸러지지 않게 서울시청 부근으로 맞춰뒀다.
FALLBACK_AMBULANCE_GPS = GpsPoint(lat=37.5665, lng=126.9780)
# 시작 zone(1)과 거절 비율 기반 확장은 HubEngine이 사건별로 관리한다
# (resolve_start_zone()/maybe_expand_zone() 참고) — 여기 고정 상수로
# MAX_ZONE=1을 박아두면 서울 전역에 흩어진 실제 병원 데이터에서 zone 1 안에
# 후보가 하나도 없는 사건은 영원히 0건으로 남는다(2026-08-11 실제로 재현됨).


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_ambulance_gps(case_id: str) -> GpsPoint:
    """caseId로 그 사건의 구급차를 찾아 GPS를 돌려준다. apid를 모르거나(통화
    시작 신호 없이 직접 테스트) 아직 AmbulanceInfo가 안 왔으면 폴백 좌표를
    쓴다. /voice/summary와 승인 액션 처리(존 확장 재계산) 양쪽에서 같은
    구급차의 GPS가 필요해 공통 헬퍼로 뺐다."""
    apid = engine.get_case_apid(case_id)
    ambulance = engine.get_ambulance(apid) if apid else None
    if ambulance is None:
        print(f"  [통신] caseId={case_id}의 구급차 GPS를 못 찾아 기본 좌표로 대체")
        return FALLBACK_AMBULANCE_GPS
    return ambulance.gps


@app.post("/info/hospitals")
def receive_hospital_info():
    """feature/info로부터 병원 정보(HospitalInfo)를 받아 등록/갱신한다."""
    try:
        info = HospitalInfo.model_validate(request.get_json(force=True))
    except ValidationError as exc:
        return jsonify({"error": "invalid HospitalInfo", "detail": exc.errors()}), 400

    engine.update_hospital_info(info)
    return jsonify({"status": "ok", "hospitalId": info.hospitalId}), 200


@app.post("/info/ambulances")
def receive_ambulance_info():
    """feature/info로부터 구급차 정보(AmbulanceInfo, Supabase ambulances
    테이블 미러)를 받아 등록/갱신한다. /info/hospitals와 같은 패턴이다."""
    try:
        info = AmbulanceInfo.model_validate(request.get_json(force=True))
    except ValidationError as exc:
        return jsonify({"error": "invalid AmbulanceInfo", "detail": exc.errors()}), 400

    engine.update_ambulance_info(info)
    return jsonify({"status": "ok", "apid": info.apid}), 200


@app.post("/voice/register")
def receive_voice_registration():
    """feature/voice가 뜰 때 자기 IP를 자동 탐지해 보내는 자가 등록.
    포트는 AmbulanceInfo.voicePort로 이미 알고 있으므로 IP만 받아서
    합친 주소를 저장해둔다. 이 apid의 AmbulanceInfo가 아직 등록 전이면
    (info가 아직 이 구급차를 안 보냈으면) 포트를 모르니 등록을 보류한다.
    """
    try:
        registration = VoiceRegistration.model_validate(request.get_json(force=True))
    except ValidationError as exc:
        return jsonify({"error": "invalid VoiceRegistration", "detail": exc.errors()}), 400

    ambulance = engine.get_ambulance(registration.apid)
    if ambulance is None:
        return jsonify({"error": f"unknown apid: {registration.apid} (아직 ambulances 정보 미수신)"}), 409

    _voice_addresses[registration.apid] = f"http://{registration.ip}:{ambulance.voicePort}"
    print(f"  [통신] voice 자가등록 완료 — {registration.apid} -> {_voice_addresses[registration.apid]}")
    return jsonify({"status": "ok", "apid": registration.apid}), 200


@app.post("/voice/summary")
def receive_voice_summary():
    """feature/voice로부터 통화 요약(VoiceCallSummaryMessage)을 받아 2단계
    매칭(존 후보 + 진료과·거리 스코어링)을 실행하고 결과를 반환한다.
    """
    try:
        voice = VoiceCallSummaryMessage.model_validate(request.get_json(force=True))
    except ValidationError as exc:
        return jsonify({"error": "invalid VoiceCallSummaryMessage", "detail": exc.errors()}), 400

    ambulance_gps = _resolve_ambulance_gps(voice.caseId)
    start_zone = engine.resolve_start_zone(ambulance_gps)
    result = engine.process_voice_summary(voice, ambulance_gps, max_zone=start_zone)

    # run_match.py와 동일하게 로컬 저장(감사용 사본)도 같이 남긴다. 실제
    # voice 요약 파일명이 없는 HTTP 경로라 타임스탬프로 이름을 대신한다.
    synthetic_path = Path(f"live_{_utcnow_iso().replace(':', '')}_call_summary.json")
    deliver(result, synthetic_path)

    _send_to_dashboard(result.model_dump())

    return jsonify(result.model_dump()), 200


def _send_to_dashboard(payload: dict) -> None:
    """연결된 모든 dashboard(구급차 여러 개 + 병원 여러 개)에 브로드캐스트한다.
    delivery.py의 send_to_dashboard()는 로컬 저장 스텁 그대로 두고, 실제
    실시간 전송은 WebSocket 연결을 쥐고 있는 여기서 처리한다. 전송 실패한
    소켓은 죽은 것으로 보고 집합에서 뺀다 (voice의 send_to_hub()와 동일한
    방어 패턴 — 연결이 없거나 끊겼어도 본 요청은 계속돼야 함)."""
    dead = set()
    for ws in _dashboard_sockets:
        try:
            ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            print(f"  [통신] dashboard WebSocket 전송 실패, 연결 제거: {e}")
            dead.add(ws)
    _dashboard_sockets.difference_update(dead)


def _relay_call_signal(signal: CallSignal) -> None:
    """dashboard의 통화 시작/종료 신호를 그 apid로 등록된 feature/voice
    인스턴스로 중계한다. call_started 시점에 (caseId -> apid)를 hub_engine에
    등록해둬야, 나중에 그 caseId로 도착하는 /voice/summary가 이 구급차의
    GPS를 찾을 수 있다. voice가 아직 자가등록 전이거나 안 떠 있어도
    dashboard 쪽 흐름은 끊기면 안 되므로 예외를 흡수한다."""
    if signal.signal == "call_started":
        engine.register_case(signal.caseId, signal.apid)

    voice_base_url = _voice_addresses.get(signal.apid)
    if voice_base_url is None:
        print(f"  [통신] {signal.apid}의 voice 주소가 아직 등록되지 않아 신호 중계를 건너뜀")
        return

    path = "/call/start" if signal.signal == "call_started" else "/call/end"
    try:
        requests.post(
            f"{voice_base_url}{path}",
            json={"timestamp": signal.timestamp, "caseId": signal.caseId},
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"  [통신] {signal.apid}의 feature/voice로 통화 신호 중계 실패 ({path}): {e}")


def _handle_dashboard_action(payload: dict) -> None:
    """ApprovalAction 처리. HubEngine.apply_approval_action()은 이미
    구현·테스트되어 있으므로 그대로 호출만 한다. 처리 후 존 확장이 필요한지
    확인하고(maybe_expand_zone — 후보 0개 사각지대 보정 + 거절 비율 기반
    확장), 최신 사건 결과를 꺼내 전체 dashboard에 재브로드캐스트한다 —
    예전엔 재브로드캐스트 자체가 없어서 승인 버튼을 눌러도 화면에 반영이
    안 됐다."""
    try:
        action = ApprovalAction.model_validate(payload)
    except ValidationError as exc:
        print(f"  [통신] 잘못된 ApprovalAction 수신: {exc.errors()}")
        return

    bed_update = engine.apply_approval_action(action)
    if bed_update is not None:
        deliver_bed_update(bed_update)

    # maybe_expand_zone()은 거절 액션에만 부른다 — reject_ratio가 누적 계산이라
    # 승인/최종승인 뒤에도 부르면 새 거절이 없는데도 계속 확장돼버린다
    # (HubEngine.maybe_expand_zone 문서 참고, 실제로 재현·검증됨).
    expanded_result = None
    if action.action == "hospital_reject":
        ambulance_gps = _resolve_ambulance_gps(action.caseId)
        expanded_result = engine.maybe_expand_zone(action.caseId, ambulance_gps)

    updated_result = expanded_result or engine.get_case_result(action.caseId)
    if updated_result is not None:
        _send_to_dashboard(updated_result.model_dump())


@sock.route("/ws/dashboard")
def dashboard_socket(ws):
    """dashboard와의 WebSocket 연결. 구급차 대시보드 여러 개 + 병원 대시보드
    여러 개가 동시에 붙을 수 있어 연결마다 집합에 추가/제거한다. 승인
    액션(JSON)과 통화 시작/종료 신호(JSON)를 받고, 매칭 결과는 /voice/summary
    처리 후 전체 연결에 밀어준다. 브라우저 마이크 오디오(바이너리 프레임)는
    화면 시각화 용도로만 쓰기로 했으므로 여기서는 받기만 하고 버린다.
    """
    _dashboard_sockets.add(ws)
    try:
        while True:
            message = ws.receive()
            if message is None:  # 연결 종료
                break
            if isinstance(message, (bytes, bytearray)):
                continue  # 오디오 청크 — 실제 STT는 voice 로컬 마이크를 쓰므로 무시

            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                continue

            if payload.get("type") == "call_signal":
                try:
                    signal = CallSignal.model_validate(payload)
                except ValidationError as exc:
                    print(f"  [통신] 잘못된 CallSignal 수신: {exc.errors()}")
                    continue
                _relay_call_signal(signal)
            elif "action" in payload:
                _handle_dashboard_action(payload)
    finally:
        _dashboard_sockets.discard(ws)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
