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

import atexit
import json
import os
import signal
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, request
from flask_sock import Sock
from pydantic import ValidationError

from delivery import LIVE_OUTPUT_DIR, deliver, send_rejection_to_info
from routing import KakaoRouting
from hub_engine import HubEngine
from schema import (
    AmbulanceInfo,
    ApprovalAction,
    CallSignal,
    DashboardIdentify,
    DashboardIdentityInfo,
    GpsPoint,
    HospitalInfo,
    VoiceCallSummaryMessage,
    VoiceRegistration,
)

app = Flask(__name__)
app.json.ensure_ascii = False  # 한글 필드를 유니코드 이스케이프 없이 그대로 응답
# dashboard WebSocket에 25초마다 ping을 보낸다(브라우저가 pong으로 자동 응답). Cloudflare
# 터널 등 프록시를 거치면 아무 프레임도 오가지 않는 연결을 약 125초 만에 끊는데(2026-09-24
# 도메인 경유 실측), 통화 → 음성 처리를 기다리는 동안이 딱 그 구간이라 매칭 결과를 보낼
# 때쯤이면 이미 끊겨 있었다. 25초는 그 한도보다 충분히 짧고, 로컬 연결엔 영향이 없다.
app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25}
sock = Sock(app)
# 카카오모빌리티 길찾기(도로 기준 ETA·경로). KAKAO_REST_API_KEY(환경변수 또는 hub/.env)가
# 없으면 None — 그 경우 ETA·도로 경로 없이 지금처럼 직선거리로만 동작한다.
router = KakaoRouting.from_env()
engine = HubEngine(router=router)

# dashboard는 순수 WebSocket 클라이언트(new WebSocket(), socket.io 아님)라
# flask-sock(순수 WS)으로 받는다. 구급차 대시보드 여러 개 + 병원 대시보드
# 여러 개가 동시에 붙을 수 있어 연결을 집합으로 관리하고 전체에 브로드캐스트한다
# (예전엔 전역 변수 하나라 마지막 연결만 갱신을 받는 버그가 있었다).
_dashboard_sockets: set = set()
# 연결 집합은 소켓 스레드들(추가·제거)과 매칭 작업 스레드(브로드캐스트)가 같이 건드린다.
# 한 소켓에 두 스레드가 동시에 send하면 프레임이 섞일 수 있어 전송도 같은 락으로 묶는다.
_sockets_lock = threading.RLock()

# apid별 voice 주소. voice가 뜰 때 자기 IP를 자동 탐지해 /voice/register로
# 알려주면 여기 저장해두고(포트는 AmbulanceInfo.voicePort로 이미 앎), 통화
# 시작/종료 신호를 그 구급차의 voice로 중계할 때 쓴다. 구급차 노트북마다
# 네트워크(와이파이/핫스팟)가 달라 IP가 자주 바뀔 수 있어, Supabase 등에
# 고정 저장하지 않고 이렇게 런타임에만 들고 있는다.
_voice_addresses: dict[str, str] = {}
_voice_addresses_lock = threading.Lock()

# 매칭(임베딩 + 카카오 호출)은 수 초가 걸릴 수 있어 /voice/summary 요청 안에서 돌리지 않고
# 이 작업 스레드로 넘긴다(2026-09-28). voice의 hub 전송 타임아웃이 10초라, 후보가 많아
# 카카오 호출(3초 × 30곳 묶음 수)이 겹치면 voice 쪽에서 실패로 찍히던 여지를 없앤다.
# 작업자 1개 — 같은 사건의 요약·주기적 재계산이 순서대로 처리되게 한다.
_match_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hub-match")

# 진행 중인 사건을 다시 계산하는 주기(초, 2026-09-28). 매칭 시점에 고정돼 있던 병상 수·
# ETA·병상 신뢰도를 이송 중에도 갱신한다. 대시보드엔 달라졌을 때만 다시 보낸다. 0이면 끈다.
# 카카오 ETA는 routing.py가 5분간 캐시하므로 이 주기가 짧아도 호출이 그만큼 늘지는 않는다.
REFRESH_INTERVAL_SEC = float(os.environ.get("HUB_REFRESH_INTERVAL_SEC", "60"))
# 상태를 디스크에 저장해 hub 재시작 뒤 복구한다(2026-09-28). 예전엔 재시작하면 병원 목록이
# 비어 info의 다음 전송(최대 30분)까지 후보가 0곳이었고, 진행 중 사건·승인 상태·병상
# 차감도 사라졌다. 통화 원문은 저장하지 않는다(hub_engine.export_state 참고).
PERSIST_STATE = os.environ.get("HUB_PERSIST_STATE", "1") != "0"
STATE_PATH = Path(
    os.environ.get("HUB_STATE_PATH", str(Path(__file__).resolve().parent / "data" / "state" / "hub_state.json"))
)
# 백그라운드 루프가 깨어나는 간격(초). 변경이 있었을 때만 저장한다.
MAINTENANCE_TICK_SEC = 5.0

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


def _resolve_ambulance_gps(case_id: str) -> tuple[GpsPoint, bool]:
    """caseId로 그 사건의 구급차를 찾아 (GPS, 기본 좌표로 대체했는지)를 돌려준다. apid를
    모르거나(통화 시작 신호 없이 직접 테스트) 아직 AmbulanceInfo가 안 왔으면 폴백 좌표를
    쓴다. 대체 여부는 매칭 결과(ambulanceGpsFallback)에 실어 보낸다 — 예전엔 콘솔에만
    남아서, 엉뚱한 위치 기준 순위가 정상 결과처럼 나갔다(2026-09-28)."""
    apid = engine.get_case_apid(case_id)
    ambulance = engine.get_ambulance(apid) if apid else None
    if ambulance is None:
        print(f"  [통신] caseId={case_id}의 구급차 GPS를 못 찾아 기본 좌표로 대체")
        return FALLBACK_AMBULANCE_GPS, True
    return ambulance.gps, False


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

    address = f"http://{registration.ip}:{ambulance.voicePort}"
    with _voice_addresses_lock:
        _voice_addresses[registration.apid] = address
    _mark_voice_addresses_dirty()
    print(f"  [통신] voice 자가등록 완료 — {registration.apid} -> {address}")
    return jsonify({"status": "ok", "apid": registration.apid}), 200


@app.post("/voice/summary")
def receive_voice_summary():
    """feature/voice로부터 통화 요약(VoiceCallSummaryMessage)을 받아 2단계
    매칭(존 후보 + 진료과·이동 시간 스코어링)을 작업 스레드에 맡기고 바로 202로 답한다.
    결과는 끝나는 대로 WebSocket으로 대시보드에 밀어준다(2026-09-28 — 예전엔 매칭이 끝날
    때까지 응답을 붙잡고 결과 전체를 본문으로 돌려줬다. voice는 본문을 쓰지 않고 성공 여부만
    본다).
    """
    try:
        voice = VoiceCallSummaryMessage.model_validate(request.get_json(force=True))
    except ValidationError as exc:
        return jsonify({"error": "invalid VoiceCallSummaryMessage", "detail": exc.errors()}), 400

    _match_executor.submit(_run_match_job, voice)
    return jsonify({"status": "accepted", "caseId": voice.caseId}), 202


def _run_match_job(voice: VoiceCallSummaryMessage) -> None:
    """작업 스레드에서 도는 매칭 본체. 예외가 나도 작업 스레드가 죽지 않게 삼키고 남긴다."""
    try:
        ambulance_gps, gps_fallback = _resolve_ambulance_gps(voice.caseId)
        start_zone = engine.resolve_start_zone(ambulance_gps)
        result = engine.process_voice_summary(
            voice, ambulance_gps, max_zone=start_zone, gps_fallback=gps_fallback
        )

        # run_match.py와 동일하게 로컬 저장(감사용 사본)도 같이 남긴다. 실제
        # voice 요약 파일명이 없는 HTTP 경로라 타임스탬프로 이름을 대신한다.
        synthetic_path = Path(f"live_{_utcnow_iso().replace(':', '')}_call_summary.json")
        deliver(result, synthetic_path, LIVE_OUTPUT_DIR)

        _send_to_dashboard(result.model_dump())
    except Exception as e:  # noqa: BLE001
        print(f"  [매칭] caseId={voice.caseId} 매칭 실패: {e!r}")


@app.get("/route")
def get_route():
    """대시보드 지도용 도로 경로(2026-09-24). caseId의 구급차 위치 → hospitalId 병원까지
    카카오모빌리티 자동차 길찾기 결과를 [[lat, lng], ...]로 돌려준다. 좌표를 클라이언트에서
    받지 않고 hub가 가진 값으로 정한다 — 이 엔드포인트가 아무 좌표나 길찾기해 주는 공개
    프록시가 되어 API 호출 한도를 소모하지 않게 하려는 것이다. 키가 없거나 조회에 실패하면
    path=null로 답하고, 대시보드는 지금처럼 직선을 그린다. 다른 origin(로컬 모드
    dashboard:3000 ↔ hub:5001)에서 부르므로 /identity와 같이 CORS를 연다.
    """
    case_id = request.args.get("caseId")
    hospital_id = request.args.get("hospitalId")
    hospital = engine.get_hospital(hospital_id) if hospital_id else None
    body: dict = {"caseId": case_id, "hospitalId": hospital_id, "path": None, "source": "rule"}
    if case_id and hospital is not None and router is not None:
        route = router.route(_resolve_ambulance_gps(case_id)[0], hospital.gps)
        if route is not None:
            body.update(route)
    response = jsonify(body)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response, 200


@app.get("/identity")
def get_identity():
    """dashboard 랜딩 페이지(코드 입력 화면)가 `/hospital`, `/ambulance`로
    넘어가기 **전에** 그 hpid/apid가 실제로 존재하는지 미리 확인하는 용도
    (2026-08-11). WebSocket `identify`와 같은 조회 로직(_resolve_identity)을
    그대로 쓴다 — REST로 따로 노출한 이유는, 랜딩 페이지는 아직 어느 사건에도
    속하지 않은 "1회성 확인"만 하면 되니 지속 연결(WebSocket)을 열었다 바로
    닫는 것보다 단순 요청-응답이 더 잘 맞기 때문이다.

    dashboard(포트 3000)와 hub(포트 5001)는 다른 origin이라 브라우저 fetch가
    CORS로 막힌다 — 이 엔드포인트는 인증 없는 단순 조회라 전체 허용해도
    안전하므로 `Access-Control-Allow-Origin: *`을 직접 붙인다.
    """
    role = request.args.get("role")
    id_ = request.args.get("id")
    if role not in ("hospital", "ambulance") or not id_:
        return jsonify({"error": "role(hospital|ambulance)과 id 쿼리 파라미터가 필요하다"}), 400

    name, known = _resolve_identity(role, id_)
    response = jsonify({"role": role, "id": id_, "name": name, "known": known})
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response, 200


def _send_to_dashboard(payload: dict) -> None:
    """연결된 모든 dashboard(구급차 여러 개 + 병원 여러 개)에 브로드캐스트한다.
    delivery.py의 send_to_dashboard()는 로컬 저장 스텁 그대로 두고, 실제
    실시간 전송은 WebSocket 연결을 쥐고 있는 여기서 처리한다. 전송 실패한
    소켓은 죽은 것으로 보고 집합에서 뺀다 (voice의 send_to_hub()와 동일한
    방어 패턴 — 연결이 없거나 끊겼어도 본 요청은 계속돼야 함)."""
    message = json.dumps(payload, ensure_ascii=False)
    with _sockets_lock:
        dead = set()
        for ws in _dashboard_sockets:
            try:
                ws.send(message)
            except Exception as e:  # noqa: BLE001
                print(f"  [통신] dashboard WebSocket 전송 실패, 연결 제거: {e}")
                dead.add(ws)
        _dashboard_sockets.difference_update(dead)


def _send_to_socket(ws, payload: dict, label: str) -> None:
    """소켓 하나에만 보낸다(따라잡기·신원 확인 응답). 브로드캐스트와 같은 락을 쓴다."""
    with _sockets_lock:
        try:
            ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            print(f"  [통신] {label} 전송 실패: {e}")


def _relay_call_signal(signal: CallSignal) -> None:
    """dashboard의 통화 시작/종료 신호를 그 apid로 등록된 feature/voice
    인스턴스로 중계한다. call_started 시점에 (caseId -> apid)를 hub_engine에
    등록해둬야, 나중에 그 caseId로 도착하는 /voice/summary가 이 구급차의
    GPS를 찾을 수 있다. voice가 아직 자가등록 전이거나 안 떠 있어도
    dashboard 쪽 흐름은 끊기면 안 되므로 예외를 흡수한다."""
    if signal.signal == "call_started":
        engine.register_case(signal.caseId, signal.apid)

    with _voice_addresses_lock:
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


def _send_catchup(ws, identify: DashboardIdentify) -> None:
    """소켓이 연결 직후 보낸 자기소개(DashboardIdentify)에 답한다. hub는
    보통 새 매칭 결과가 생길 때만 그 순간 연결된 소켓들에 브로드캐스트하는데,
    이미 진행 중인 사건이 있는 상태에서 새 탭이 뒤늦게 연결되면 그 브로드캐스트를
    놓쳐서 화면에 아무것도 안 뜨는 문제가 있었다(schema.py의 DashboardIdentify
    문서 참고, 2026-08-11 실제 재현됨). 이 소켓과 관련된 사건들만 골라 지금
    즉시 이 소켓에만 한 번씩 보내준다 — 형식은 평소 브로드캐스트와 같은
    HubMatchResult라 dashboard는 "따라잡기 메시지"인지 구분할 필요 없이
    받은 대로 처리하면 된다."""
    cases = (
        engine.get_cases_for_hospital(identify.id)
        if identify.role == "hospital"
        else engine.get_cases_for_apid(identify.id)
    )
    print(f"  [통신] {identify.role} {identify.id} 연결 — 진행 중인 사건 {len(cases)}건 따라잡기 전송")
    for result in cases:
        _send_to_socket(ws, result.model_dump(), "따라잡기")


def _resolve_identity(role: str, id_: str) -> tuple[str | None, bool]:
    """role(hospital/ambulance)과 id(hpid/apid)로 hub가 아는 실제 이름과
    존재 여부를 찾는다. WebSocket의 identify 응답과 HTTP `GET /identity`
    양쪽이 같은 로직을 쓴다."""
    if role == "hospital":
        hospital = engine.get_hospital(id_)
        return (hospital.name if hospital is not None else None), hospital is not None
    ambulance = engine.get_ambulance(id_)
    return (ambulance.name if ambulance is not None else None), ambulance is not None


def _send_identity_info(ws, identify: DashboardIdentify) -> None:
    """자기소개(DashboardIdentify)에 대해, 사건 유무와 무관하게 그 hpid/apid의
    실제 이름을 즉시 알려준다. _send_catchup()은 "진행 중인 사건"이 있어야만
    뭔가를 보내는데, 사건이 하나도 없는 상태(대시보드를 막 열어서 아직 통화가
    없는 상태)에서도 상단바에 실명이 뜨게 하려면 이 응답이 따로 필요하다
    (2026-08-11 — 병원/구급차 대시보드가 항상 이름으로 뜨길 원한다는 요청).
    hub가 그 hpid/apid를 아예 모르면(`known=False`) dashboard는 이걸
    "존재하지 않는 접근 코드"로 판단하는 데 쓸 수 있다 — 다만 랜딩
    페이지에서 미리 걸러지므로(GET /identity), 이 소켓 경로는 직접 URL로
    들어온 경우의 이름 표시용으로만 주로 쓰인다."""
    name, known = _resolve_identity(identify.role, identify.id)
    info = DashboardIdentityInfo(role=identify.role, id=identify.id, name=name, known=known)
    print(f"  [통신] {identify.role} {identify.id} 신원 확인 응답 — known={known}, name={name}")
    _send_to_socket(ws, info.model_dump(), "identity_info")


# hospital_score 신뢰도 tier(문자열 라벨) -> "물어볼 당시 병원이 뭐라고 신고했나".
# declaredAtRequest로 넘기면 info가 "가능이라 신고했는데 거절"을 셀 수 있어
# 신고 정확도를 운영 데이터로 직접 측정한다(CLAUDE.md "거절 로그" 절). 미상
# tier(unknown_*)는 신고 자체가 없었다는 뜻이라 필드를 아예 넣지 않는다.
_TIER_TO_DECLARED = {"declared_yes": "Y", "declared_no": "불가능"}


def _build_rejection_payload(action: ApprovalAction) -> dict:
    """dashboard의 hospital_reject 액션을 feature/info 거절 로그 수신구가 받는
    형태로 조립한다. 필수는 hospitalId 하나뿐이고(수신구가 관대하게 받는다),
    나머지는 사건 캐시에서 best-effort로 채운다 — 조회가 실패하면 그 필드만
    빠지고 전달 자체는 계속된다(거절 로그는 소급 생성이 안 되므로 부분 정보라도
    남기는 게 낫다).
    """
    payload: dict = {
        "hospitalId": action.hospital_id,
        "caseId": action.caseId,
        "timestamp": action.timestamp,
        "reasonCode": action.reason or "UNSPECIFIED",
    }

    result = engine.get_case_result(action.caseId)
    if result is not None:
        payload["severity"] = result.patientInfo.severityTag
        match = next(
            (h for h in result.hospitals if h.hospitalId == action.hospital_id), None
        )
        if match is not None and match.reliability is not None:
            group = match.reliability.group
            payload["diseaseGroup"] = group
            info = engine.get_hospital(action.hospital_id)
            group_score = (
                info.assessment.groups.get(group)
                if info is not None and info.assessment is not None
                else None
            )
            declared = _TIER_TO_DECLARED.get(getattr(group_score, "tier", None))
            if declared is not None:
                payload["declaredAtRequest"] = declared

    return payload


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

    engine.apply_approval_action(action)

    # maybe_expand_zone()은 거절 액션에만 부른다 — reject_ratio가 누적 계산이라
    # 승인/최종승인 뒤에도 부르면 새 거절이 없는데도 계속 확장돼버린다
    # (HubEngine.maybe_expand_zone 문서 참고, 실제로 재현·검증됨).
    expanded_result = None
    if action.action == "hospital_reject":
        # 거절 사유를 feature/info 거절 로그로 중계한다. 점수의 진짜 정답
        # ("병원이 실제로 받았는가")은 이 로그가 쌓여야 나오고 소급 생성이
        # 안 되므로, 수신구가 안 떠 있어도(fire-and-forget) 매번 보낸다.
        send_rejection_to_info(_build_rejection_payload(action))

        ambulance_gps, _ = _resolve_ambulance_gps(action.caseId)
        expanded_result = engine.maybe_expand_zone(action.caseId, ambulance_gps)

    updated_result = expanded_result or engine.get_case_result(action.caseId)
    if updated_result is not None:
        _send_to_dashboard(updated_result.model_dump())


@sock.route("/ws/dashboard")
def dashboard_socket(ws):
    """dashboard와의 WebSocket 연결. 구급차 대시보드 여러 개 + 병원 대시보드
    여러 개가 동시에 붙을 수 있어 연결마다 집합에 추가/제거한다. 연결 직후
    자기소개(DashboardIdentify)를 보내면 두 가지를 순서대로 응답한다:
    (1) 사건 유무와 무관한 즉시 신원 확인(_send_identity_info — 실명·존재
    여부), (2) 그 소켓과 관련된 진행 중인 사건 따라잡기(_send_catchup — 새
    탭이 뒤늦게 연결돼서 이전 브로드캐스트를 놓치는 문제 보정). 승인
    액션(JSON)과 통화 시작/종료 신호(JSON)도 받는다. 매칭 결과는
    /voice/summary 처리 후 전체 연결에 밀어준다. 브라우저 마이크 오디오
    (바이너리 프레임)는 화면 시각화 용도로만 쓰기로 했으므로 여기서는
    받기만 하고 버린다.
    """
    with _sockets_lock:
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
            elif payload.get("type") == "identify":
                try:
                    identify = DashboardIdentify.model_validate(payload)
                except ValidationError as exc:
                    print(f"  [통신] 잘못된 DashboardIdentify 수신: {exc.errors()}")
                    continue
                _send_identity_info(ws, identify)
                _send_catchup(ws, identify)
            elif "action" in payload:
                _handle_dashboard_action(payload)
    finally:
        with _sockets_lock:
            _dashboard_sockets.discard(ws)


# ── 백그라운드: 주기적 재계산 · 상태 저장 (2026-09-28) ───────────────────────

_voice_addresses_dirty = False
_refresh_future: Future | None = None


def _mark_voice_addresses_dirty() -> None:
    global _voice_addresses_dirty
    _voice_addresses_dirty = True


def _refresh_active_cases() -> None:
    """진행 중인 사건을 다시 계산하고, 달라진 사건만 대시보드에 다시 보낸다(작업 스레드에서 돈다)."""
    for case_id in engine.get_active_case_ids():
        try:
            ambulance_gps, _ = _resolve_ambulance_gps(case_id)
            updated = engine.refresh_case(case_id, ambulance_gps)
        except Exception as e:  # noqa: BLE001
            print(f"  [재계산] caseId={case_id} 실패: {e!r}")
            continue
        if updated is not None:
            _send_to_dashboard(updated.model_dump())


def save_state() -> None:
    """엔진 상태 + voice 주소를 원자적으로(임시 파일 → 교체) 저장한다."""
    global _voice_addresses_dirty
    state = engine.export_state()
    with _voice_addresses_lock:
        state["voiceAddresses"] = dict(_voice_addresses)
        _voice_addresses_dirty = False
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, STATE_PATH)


def load_state() -> None:
    """저장된 상태가 있으면 복구한다. 파일이 깨졌어도 hub는 빈 상태로 뜬다."""
    if not STATE_PATH.exists():
        return
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  [상태 복구] 상태 파일을 읽지 못해 빈 상태로 시작: {e}")
        return
    counts = engine.import_state(state)
    with _voice_addresses_lock:
        _voice_addresses.update(state.get("voiceAddresses") or {})
    print(
        f"  [상태 복구] {STATE_PATH.name} (저장 {state.get('savedAt')}) — 병원 {counts.get('hospitals', 0)}곳, "
        f"구급차 {counts.get('ambulances', 0)}대, 사건 {counts.get('cases', 0)}건, voice 주소 {len(_voice_addresses)}곳"
    )


def _maintenance_loop() -> None:
    global _refresh_future
    last_refresh = time.monotonic()
    while True:
        time.sleep(MAINTENANCE_TICK_SEC)
        try:
            due = REFRESH_INTERVAL_SEC > 0 and time.monotonic() - last_refresh >= REFRESH_INTERVAL_SEC
            # 앞선 재계산이 아직 안 끝났으면 쌓지 않는다.
            if due and (_refresh_future is None or _refresh_future.done()):
                last_refresh = time.monotonic()
                _refresh_future = _match_executor.submit(_refresh_active_cases)
            if PERSIST_STATE and (engine.take_dirty() or _voice_addresses_dirty):
                save_state()
        except Exception as e:  # noqa: BLE001
            print(f"  [백그라운드] 오류(계속 진행): {e!r}")


def start_background() -> None:
    """상태 복구 + 재계산·저장 루프 시작. `python app.py`로 띄울 때만 부른다 — 테스트
    (test_rejection_forward.py)가 app을 import해도 디스크 상태를 건드리지 않게."""
    if PERSIST_STATE:
        load_state()
        atexit.register(save_state)
        # 프로세스 관리자·kill이 보내는 SIGTERM은 기본 동작이 즉시 종료라 atexit이 안 돈다.
        # 정상 종료(sys.exit)로 바꿔 마지막 상태를 저장하게 한다. 저장 루프가 5초마다 돌므로
        # 이게 없어도 잃는 건 최대 몇 초분이다.
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    threading.Thread(target=_maintenance_loop, name="hub-maintenance", daemon=True).start()


if __name__ == "__main__":
    # debug=True면 코드 리로더가 켜져 파일이 바뀔 때마다 재시작되고(인메모리 상태 유실),
    # 예외 화면이 외부에 노출된다(2026-09-28 기본값 변경). 개발 중에만 HUB_DEBUG=1로 켠다.
    debug = os.environ.get("HUB_DEBUG") == "1"
    # 리로더가 켜지면 이 블록이 감시용 부모 프로세스에서도 한 번 더 돈다 — 실제 서버(자식)
    # 에서만 백그라운드를 시작해야 상태 파일을 두 프로세스가 같이 쓰지 않는다.
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_background()
    app.run(host="0.0.0.0", port=5001, debug=debug)
