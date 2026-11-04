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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, request
from flask_sock import Sock
from pydantic import ValidationError

import bed_reliability
from ambulance_sim import TRANSPORT_SEC as SIM_TRANSPORT_SEC, TRIP_SEC as SIM_TRIP_SEC, DispatchSim
import decision_log
from hospital_dispatch import dashboard_payload
from delivery import HUB_REJECTION_URL, LIVE_OUTPUT_DIR, deliver, send_rejection_to_info
from routing import KakaoRouting
from geo import ZONE_BAND_KM, haversine_km, zone_of
from scoring import DEFAULT_MIN_PER_KM
import assignment_agent
from hub_engine import HubEngine, _is_bed_count_unknown, _is_bed_data_stale
from case_history import CaseTracker, query_archive
from record_archive import RecordArchive
from schema import (
    AcceptanceMessage,
    AmbulanceInfo,
    ApprovalAction,
    CallSignal,
    DashboardIdentify,
    DashboardIdentityInfo,
    DispatchRequest,
    GpsPoint,
    HospitalInfo,
    HospitalInfoConfirm,
    HospitalSelfInfo,
    MapAmbulance,
    MapHospital,
    MapOverview,
    MonitorCase,
    CaseHistory,
    CaseMeta,
    ZoneExpandNow,
    MciAllocate,
    MciPreview,
    MonitorCaseHospital,
    PatientOverride,
    SceneEnd,
    SimControl,
    SimReset,
    TransportAlternative,
    TransportAssessmentMessage,
    TransportVitals,
    VitalObservationIn,
    VoiceCallSummaryMessage,
    VoiceRegistration,
    VoiceUtterance,
)
from transport_triage import TransportTriage, VitalObservation

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
record_archive = RecordArchive()


def _archive_call(method, *args):
    # 기록 저장 실패는 숨기지 않되 응급이송의 실시간 처리를 중단시키지 않는다.
    try:
        result = getattr(record_archive, method)(*args)
        if result and result.get("apid"):
            _notify_record_clients(result["apid"])
        return result
    except Exception as exc:
        print(f"  [기록 동기화] {method} 실패 ({type(exc).__name__}) — 로컬 기록 보존, 서버 저장소 점검 필요")


def _notify_record_clients(apid):
    # 내용은 동기화 키를 검증하는 record_sync에서만 반환한다. 이 메시지는 재조회 알림뿐이다.
    message = json.dumps({"type": "records_changed"})
    with _sockets_lock:
        for ws in list(_dashboard_sockets):
            if _socket_identity.get(ws) == ("ambulance", apid):
                try:
                    ws.send(message)
                except Exception:
                    pass


def _handle_live_case_edit(ws, payload):
    """현재 사건의 대원 기기끼리만 수정 칸을 공유한다. 과거 기록 조회 권한은 열지 않는다."""
    role, apid = _socket_identity.get(ws, (None, None))
    cid = payload.get("caseId")
    error = None
    owner = engine.get_case_apid(cid) if isinstance(cid, str) else None
    # 진행 중에 받은 사건별 증표가 있으면, 사건 종료 직전 오프라인에 쌓인 수정도 재전송할 수 있다.
    retained = False
    if role == "ambulance" and owner is None and isinstance(cid, str):
        try:
            retained = record_archive.authorized_live(apid, cid, payload.get("ticket"))
        except Exception:
            _send_to_socket(ws, {"type": "live_case_error", "caseId": cid, "requestId": payload.get("requestId"), "error": "storage_unavailable"}, "기기 수정 동기화")
            return
    if role != "ambulance" or not isinstance(cid, str) or not (owner == apid and apid is not None or retained):
        error = "not_owner"
    elif payload.get("type") == "live_case_patch" and _case_paused(cid):
        error = "paused"
    if error:
        _send_to_socket(ws, {"type": "live_case_error", "caseId": cid, "requestId": payload.get("requestId"), "error": error}, "기기 수정 동기화")
        return
    try:
        if len(json.dumps(payload)) > 1000000: raise ValueError("too_large")
        state = record_archive.live_get(apid, cid) if payload["type"] == "live_case_get" else record_archive.live_patch(apid, payload)
    except (ValueError, TypeError):
        _send_to_socket(ws, {"type": "live_case_error", "caseId": cid, "requestId": payload.get("requestId"), "error": "invalid_patch"}, "기기 수정 동기화")
        return
    except Exception:
        _send_to_socket(ws, {"type": "live_case_error", "caseId": cid, "requestId": payload.get("requestId"), "error": "storage_unavailable"}, "기기 수정 동기화")
        return
    _send_to_socket(ws, state, "기기 수정 동기화")
    if payload["type"] == "live_case_patch" and not state.get("conflicts"):
        broadcast = {k: v for k,v in state.items() if k not in ("requestId", "conflicts")}
        with _sockets_lock:
            targets = [s for s in _dashboard_sockets if owner == apid and s != ws and _socket_identity.get(s) == ("ambulance", apid)]
        for target in targets:
            _send_to_socket(target, broadcast, "다른 대원 기기 수정 반영")
        _notify_record_clients(apid)


#: 구급차 출동 시뮬레이션(시연용 가짜 위치, 2026-10-01). HUB_SIM_DISPATCH=1일 때만 켠다.
SIM_DISPATCH = os.environ.get("HUB_SIM_DISPATCH") == "1"
sim: DispatchSim | None = DispatchSim(router) if SIM_DISPATCH else None
#: 구급차 대시보드에서 통화 시작 허용(2026-10-03, start-all.sh --dashboard-call → HUB_DASHBOARD_CALL=1). 기본은
#: 꺼서 통화는 휴대폰 전화 앱(device="phone")으로만 받는다 — 대시보드(device="tablet")의 통화 시작은 거부한다.
DASHBOARD_CALL = os.environ.get("HUB_DASHBOARD_CALL") == "1"
SIM_TICK_SEC = 1.0

# dashboard는 순수 WebSocket 클라이언트(new WebSocket(), socket.io 아님)라
# flask-sock(순수 WS)으로 받는다. 구급차 대시보드 여러 개 + 병원 대시보드
# 여러 개가 동시에 붙을 수 있어 연결을 집합으로 관리하고 전체에 브로드캐스트한다
# (예전엔 전역 변수 하나라 마지막 연결만 갱신을 받는 버그가 있었다).
_dashboard_sockets: set = set()
# 소켓 -> (role, id). identify를 보낸 소켓만 등록된다. 거절 로그의 무응답
# (NO_RESPONSE) 기록에서 "요청을 보고도 무시"와 "대시보드 미접속(미도달)"을
# 구분하는 데 쓴다 — 둘을 섞으면 원인 축 분리라는 거절 로그 설계가 깨진다.
_socket_identity: dict = {}
# caseId -> 그 사건의 매칭 결과가 실제로 병원 대시보드에 도달했던 hpid 집합.
# 브로드캐스트·따라잡기 시점마다 누적한다. 무응답 기록의 "당시 요청을 받았는가"
# (reachedAtBroadcast)를 확정 순간의 연결 여부가 아니라 **도달 이력**으로 판정하기
# 위함 — 확정 순간 기준만 쓰면 그 사이 끊긴 병원이 미도달로 오분류된다(2026-09-29).
_case_reach: dict[str, set[str]] = {}
# 사건별 마지막 활동(매칭 전송·승인 액션) 시각. 확정 없이 방치된 사건의
# 무응답 정리(sweep) 판단에 쓴다.
_case_last_activity: dict[str, datetime] = {}
# 무응답 기록을 이미 마친 사건 — 중복 기록 방지(중복 final_approval·sweep 재방문).
_case_swept: set[str] = set()
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
    # 그 병원 대시보드가 연결돼 있으면 "귀원 정보 현황"을 갱신해준다 —
    # 주기 재전송(기본 5분)을 그대로 자기 화면 신선도 갱신으로 재사용.
    _send_self_info_to_hospital(info.hospitalId)
    return jsonify({"status": "ok", "hospitalId": info.hospitalId}), 200


@app.post("/info/hospitals/roster")
def receive_hospital_roster():
    """feature/info가 한 주기에 보낸 병원 전체 목록(2026-10-01). 여기 없는 병원을 레지스트리에서
    뺀다 — 진행 중 사건 후보는 남기고, 목록이 급감하면 아무것도 안 뺀다(HubEngine.apply_hospital_roster)."""
    body = request.get_json(force=True, silent=True) or {}
    ids = body.get("hospitalIds")
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        return jsonify({"error": "hospitalIds(list[str])가 필요합니다"}), 400
    removed, kept = engine.apply_hospital_roster(ids)
    if removed or kept:
        decision_log.log_decision("hospital_roster_applied", {"removed": removed, "kept": kept, "rosterSize": len(ids)})
        print(f"  [통신] 병원 목록 반영 — 피드에서 빠진 병원 {len(removed)}곳 제거, {len(kept)}곳 보류(진행 중 사건 후보이거나 목록 급감)")
    # info가 한 주기 병원을 다 보낸 뒤 오는 신호라, 관제 지도의 병원 마커를 여기서 한 번에 갱신한다
    # (병원 하나 받을 때마다 보내면 주기마다 400여 번 보내게 된다).
    _send_map_overview()
    return jsonify({"status": "ok", "removed": removed, "kept": kept}), 200


@app.post("/info/ambulances")
def receive_ambulance_info():
    """feature/info로부터 구급차 정보(AmbulanceInfo, Supabase ambulances
    테이블 미러)를 받아 등록/갱신한다. /info/hospitals와 같은 패턴이다."""
    try:
        info = AmbulanceInfo.model_validate(request.get_json(force=True))
    except ValidationError as exc:
        return jsonify({"error": "invalid AmbulanceInfo", "detail": exc.errors()}), 400

    engine.update_ambulance_info(info)
    if sim is not None:
        sim.ensure_unit(info.apid, info.gps)
    _send_map_overview()
    return jsonify({"status": "ok", "apid": info.apid}), 200


@app.post("/info/ambulances/batch")
def receive_ambulance_batch():
    """구급차 여러 대를 한 번에 받는다(2026-10-04). 서울 119 구급차(160여 대)로 바꾸면서 한 대씩 받으면
    주기마다 관제 지도 전송이 대수만큼 나가서, 묶어 받고 관제 지도는 끝에 한 번만 보낸다.
    형식이 틀린 한 대는 건너뛰고(rejected에 이유) 나머지는 그대로 반영한다."""
    body = request.get_json(force=True, silent=True) or {}
    items = body.get("ambulances")
    if not isinstance(items, list):
        return jsonify({"error": "ambulances(list[AmbulanceInfo])가 필요합니다"}), 400
    accepted, rejected = [], []
    for item in items:
        try:
            info = AmbulanceInfo.model_validate(item)
        except ValidationError as exc:
            rejected.append({"apid": (item or {}).get("apid") if isinstance(item, dict) else None,
                             "detail": exc.errors(include_url=False, include_context=False)})
            continue
        engine.update_ambulance_info(info)
        if sim is not None:
            sim.ensure_unit(info.apid, info.gps)
        accepted.append(info.apid)
    _send_map_overview()
    return jsonify({"status": "ok", "accepted": len(accepted), "rejected": rejected}), 200


@app.post("/info/ambulances/roster")
def receive_ambulance_roster():
    """feature/info가 한 주기에 보낸 구급차 전체 목록(2026-10-04). 여기 없는 구급차를 레지스트리에서 뺀다 —
    병원 목록 동기화와 같은 규칙(진행 중 사건·출동 중 구급차는 남기고, 목록이 급감하면 안 뺀다)."""
    body = request.get_json(force=True, silent=True) or {}
    ids = body.get("apids")
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        return jsonify({"error": "apids(list[str])가 필요합니다"}), 400
    busy: set[str] = set()
    if sim is not None:
        busy = {a.apid for a in engine.list_ambulances() if sim.phase_of(a.apid) not in (None, "idle")}
    removed, kept = engine.apply_ambulance_roster(ids, busy=busy)
    if sim is not None:
        for apid in removed:
            sim.remove_unit(apid)
    if removed:
        with _voice_addresses_lock:
            for apid in removed:
                _voice_addresses.pop(apid, None)
        _mark_voice_addresses_dirty()
    if removed or kept:
        decision_log.log_decision("ambulance_roster_applied", {"removed": removed, "kept": kept, "rosterSize": len(ids)})
        print(f"  [통신] 구급차 목록 반영 — 빠진 구급차 {len(removed)}대 제거, {len(kept)}대 보류(진행 중 사건·출동 중이거나 목록 급감)")
    if removed:
        _send_map_overview()
    return jsonify({"status": "ok", "removed": removed, "kept": kept}), 200


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

    if registration.central:
        # 중앙 voice(2026-10-03) — 모든 구급차의 통화를 여기로 보낸다. 30초마다 다시 오므로 저장하지 않는다(재시작하면
        # 다음 등록 때 다시 붙는다). 마지막 등록이 CENTRAL_VOICE_STALE_SEC보다 오래되면 꺼진 것으로 본다.
        address = f"http://{registration.ip}:{registration.port or 6000}"
        with _voice_addresses_lock:
            first = _central_voice.get("url") != address
            _central_voice.update(url=address, seenAt=time.monotonic())
        if first:
            print(f"  [통신] 중앙 voice 등록 — {address} (모든 구급차 통화를 여기로)")
        return jsonify({"status": "ok", "central": True}), 200
    if not registration.apid:
        return jsonify({"error": "apid가 필요합니다(구급차별 voice) — 중앙 voice면 central=true"}), 400

    ambulance = engine.get_ambulance(registration.apid)
    if ambulance is None:
        return jsonify({"error": f"unknown apid: {registration.apid} (아직 ambulances 정보 미수신)"}), 409

    address = f"http://{registration.ip}:{ambulance.voicePort}"
    with _voice_addresses_lock:
        _voice_addresses[registration.apid] = address
    _mark_voice_addresses_dirty()
    print(f"  [통신] voice 자가등록 완료 — {registration.apid} -> {address}")
    return jsonify({"status": "ok", "apid": registration.apid}), 200


@app.post("/voice/utterance")
def receive_voice_utterance():
    """통화 중 voice가 발화 하나를 인식할 때마다 보낸다(2026-10-03). 그 구급차 대시보드 탭에만 call_transcript로
    넘긴다 — 병원·관제 지도로는 보내지 않고, 상태 파일·의사결정 로그에도 남기지 않는다(통화 원문은 voice 로컬
    파일과 통화 요약에만). 탭이 없으면 그냥 버린다."""
    try:
        utterance = VoiceUtterance.model_validate(request.get_json(force=True))
    except ValidationError as exc:
        return jsonify({"error": "invalid VoiceUtterance", "detail": exc.errors()}), 400
    payload = {"type": "call_transcript", **utterance.model_dump()}
    with _sockets_lock:
        targets = [ws for ws, (role, id_) in _socket_identity.items() if role == "ambulance" and id_ == utterance.apid]
    for ws in targets:
        _send_to_socket(ws, payload, "실시간 발화")
    return jsonify({"status": "ok", "delivered": len(targets)}), 202


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
        # 같은 사건의 추가 통화(환자 상태 변화, 2026-10-05)는 add_call_summary가 덧붙인다 — 첫 통화면 기존과 같다
        result = engine.add_call_summary(
            voice, ambulance_gps, max_zone=start_zone, gps_fallback=gps_fallback
        )

        # run_match.py와 동일하게 로컬 저장(감사용 사본)도 같이 남긴다. 실제
        # voice 요약 파일명이 없는 HTTP 경로라 타임스탬프로 이름을 대신한다.
        synthetic_path = Path(f"live_{_utcnow_iso().replace(':', '')}_call_summary.json")
        deliver(result, synthetic_path, LIVE_OUTPUT_DIR)

        _send_to_dashboard(result.model_dump())
        _feed_followup_vitals(voice, result)
        _release_call_hold(voice.caseId, "summary_applied")
        # spider 매칭 규칙(2026-10-15): 새 사건이 줄을 잡으면 같은 τ 창의 덜 우선하는 사건이 양보해야 한다 — 나머지를 다시 계산
        _match_executor.submit(_refresh_active_cases)
    except Exception as e:  # noqa: BLE001
        print(f"  [매칭] caseId={voice.caseId} 매칭 실패: {e!r}")


def _run_override_job(override: PatientOverride, ws=None) -> None:
    """구급대원의 통화 요약 확인·수정(2026-10-13, Override)을 반영하고 갱신본을 그 구급차 탭과 후보 병원 탭에 다시
    보낸다. 순위 칸이 바뀌면 재매칭(임베딩·카카오 호출)이 있어 통화 요약과 같은 작업 스레드에서 돈다."""
    try:
        ambulance_gps, _ = _resolve_ambulance_gps(override.caseId)
        applied = engine.apply_patient_override(override, ambulance_gps)
        if applied is None:
            _notify_refused(ws, override.caseId, "no_case")
            return
        result, log = applied
        _send_to_dashboard(result.model_dump())
        changed = ", ".join(c["field"] for c in log["changes"]) or "수정 없음"
        print(f"  [Override] case={override.caseId} 구급대원 확인 — {changed}"
              f"{' · 재매칭' if log['rematched'] else ''}")
    except Exception as e:  # noqa: BLE001
        print(f"  [Override] caseId={override.caseId} 반영 실패: {e!r}")


def _mci_allocate(case_ids: list[str], ws=None) -> list[dict]:
    """대량사고 [분배 확정](2026-10-05): 콘솔 ③에 미리 보여준 자동 분배 계획(engine.plan_mci — 중증부터, 승인 병원 중
    finalScore 최고, 앞 배정마다 부하 페널티)대로 사건마다 이송 확정한다(구급대원의 이송 승인과 같은 final_approval).
    보이는 대로 확정된다. 승인 병원이 없거나(제외 포함) 일시정지 중인 사건은 건너뛴다. 결과를 콘솔 소켓에
    mci_allocated로 돌려준다."""
    results = []
    plan = engine.plan_mci(case_ids)
    planned = {item["caseId"] for item in plan}
    for case_id in dict.fromkeys(case_ids):
        if case_id not in planned:
            results.append({"caseId": case_id, "hospitalId": None, "reason": "no_result"})
    for item in plan:
        case_id = item["caseId"]
        if _case_paused(case_id):
            results.append({"caseId": case_id, "hospitalId": None, "reason": "paused"})
            continue
        current = engine.get_case_result(case_id)
        if current is None or any(h.status == "confirmed" for h in current.hospitals):
            results.append({"caseId": case_id, "hospitalId": None, "reason": "already_confirmed"})
            continue
        if item["hospitalId"] is None:
            results.append({"caseId": case_id, "hospitalId": None, "reason": "no_approved_hospital"})
            continue
        _handle_dashboard_action({
            "caseId": case_id, "action": "final_approval", "hospital_id": item["hospitalId"], "actor": "paramedic",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, ws, allocated=True)
        results.append({"caseId": case_id, "hospitalId": item["hospitalId"], "hospitalName": item.get("hospitalName"),
                        "loadPenaltyMin": item.get("loadPenaltyMin"), "reason": "confirmed"})
    decision_log.log_decision("mci_allocated", {"results": results})
    confirmed = sum(1 for r in results if r["reason"] == "confirmed")
    print(f"  [대량사고] 분배 확정 — {confirmed}/{len(results)}건 이송 확정(중증부터, hub 순위·부하 페널티)")
    if ws is not None:
        _send_to_socket(ws, {"type": "mci_allocated", "results": results}, "대량사고 분배")
    return results


def _feed_followup_vitals(voice: VoiceCallSummaryMessage, result) -> None:
    """이송 중 2차 통화(2026-10-05)에서 읽은 활력징후를 이송 중 모니터링(규칙 엔진, NEWS2)에 측정 1회로 넣는다
    (source "voice"). 구급차의 이송 중 모니터링 패널에 판정이 쌓이고, 상태 변화가 지속되면(notify 이상) 목적지 병원
    화면에도 상태 변화 배너가 뜬다. 첫 통화(현장)나 이송 확정 전 사건은 건드리지 않는다."""
    if result.patientInfo.callRound < 2 or not any(h.status == "confirmed" for h in result.hospitals):
        return
    vital = voice.summary.vitals[-1] if voice.summary.vitals else None
    avpu = (voice.summary.consciousness or "").strip().upper()[:1] or None
    avpu = avpu if avpu in ("A", "V", "P", "U") else None

    def as_int(value):
        return int(round(value)) if value is not None else None

    observation = VitalObservationIn(
        measuredAt=datetime.now(timezone.utc).isoformat(timespec="seconds"), source="voice",
        rr=as_int(vital.rr) if vital else None, spo2=as_int(vital.spo2) if vital else None,
        sbp=as_int(vital.sbp) if vital else None, dbp=as_int(vital.dbp) if vital else None,
        hr=as_int(vital.hr) if vital else None, bt=vital.bt if vital else None, avpu=avpu,
    )
    if all(getattr(observation, k) is None for k in ("rr", "spo2", "sbp", "hr", "bt", "avpu")):
        return
    demo = (voice.model_used or {}).get("stt") == "scenario-template"
    _handle_transport_vitals(TransportVitals(
        caseId=voice.caseId, apid=engine.get_case_apid(voice.caseId), demo=demo,
        scenario="followup_call" if demo else None, observation=observation,
    ))


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


#: /geocode 호출 제한(2026-10-01). 도메인이 공개라 누구나 부를 수 있어서, 카카오 무료 한도가 소진되지 않게
#: 서버 전체로 1분에 이만큼만 받는다(같은 검색어는 routing.py가 5분 캐시).
GEOCODE_PER_MIN = int(os.environ.get("HUB_GEOCODE_PER_MIN", "30"))
_geocode_calls: list[float] = []
_geocode_lock = threading.Lock()


@app.get("/verification")
def get_verification():
    """시연용 신뢰도 검증 화면(2026-10-02). 집계는 info 거절 로그 수신구(5003)가 만들고 hub는 그대로 중계한다
    — dashboard는 hub와만 통신한다. 수신구가 안 떠 있으면 503."""
    url = HUB_REJECTION_URL.rsplit("/hub/rejection", 1)[0] + "/verification/summary"
    hpid = (request.args.get("hpid") or "").strip()
    try:
        # 집계 자체가 무거울 수 있어 여유를 둔다(90초). 수신구의 1시간 재생성은 2026-10-03부터
        # 백그라운드라 평시엔 수 초지만, 첫 생성(파일 없음)은 여전히 동기다.
        upstream = requests.get(url, params={"hpid": hpid} if hpid else None, timeout=90)
        upstream.raise_for_status()
        body = upstream.json()
        if hpid:
            self_info = _build_self_info(hpid)
            body["hospitalHub"] = {
                "selfInfo": self_info.model_dump() if self_info else None,
                "activity": _hospital_activity(hpid),
            }
        response, status = jsonify(body), 200
    except (requests.RequestException, ValueError) as e:
        response, status = jsonify({"error": f"검증 집계를 가져오지 못했습니다(거절 로그 수신구 5003): {e}"}), 503
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response, status


@app.get("/case-archive")
def get_case_archive():
    """관제 '지난 사건' 모달의 날짜·검색 조회(2026-11-01). 계약은 dashboard/src/lib/case-archive.ts 머리말."""
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 1000))
    except ValueError:
        limit = 200
    body = query_archive(case_tracker._archive_path, request.args.get("from") or today, request.args.get("to") or today,
                         request.args.get("q", ""), request.args.get("result", "all"), limit)
    response = jsonify(body)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@app.get("/rejection-stats")
def get_rejection_stats():
    """관제 화면용 거절 사유 집계(2026-11-01). info 거절 로그 수신구(5003)의 JSON을 그대로 중계하고, 병원 이름만 붙인다."""
    url = HUB_REJECTION_URL.rsplit("/hub/rejection", 1)[0] + "/hub/rejection/stats"
    try:
        upstream = requests.get(url, params={"days": request.args.get("days", "30")}, timeout=10)
        upstream.raise_for_status()
        body = upstream.json()
        for item in body.get("topHospitals", []):
            info = engine.get_hospital(item["hospitalId"])
            item["name"] = info.name if info else item["hospitalId"]
        response, status = jsonify(body), 200
    except (requests.RequestException, ValueError) as e:
        response, status = jsonify({"error": f"거절 집계를 가져오지 못했습니다(거절 로그 수신구 5003): {e}"}), 503
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response, status


@app.get("/verification/live")
def get_verification_live():
    """라이브 채점 보드(2026-10-03). info 수신구(5003)의 reliability.live_board가 실제 서빙
    엔진으로 창 전체를 재생·채점한 결과를 그대로 중계한다 — dashboard는 hub와만 통신.
    첫 생성이 수십 초라 타임아웃을 넉넉히 둔다(이후는 20분 캐시)."""
    url = HUB_REJECTION_URL.rsplit("/hub/rejection", 1)[0] + "/verification/live"
    try:
        upstream = requests.get(url, timeout=90)
        upstream.raise_for_status()
        response, status = jsonify(upstream.json()), 200
    except (requests.RequestException, ValueError) as e:
        response, status = jsonify({"error": f"라이브 보드를 가져오지 못했습니다(거절 로그 수신구 5003): {e}"}), 503
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response, status


#: 병원 활동 기록에 셀 의사결정 로그 항목 — 승인·거절·이송 확정·도착 결과·정보 확인
_ACTIVITY_LABEL = {
    "hospital_approve": "수용 승인", "hospital_reject": "수용 불가", "final_approval": "이송 확정(구급대)",
    "arrival_accepted": "환자 수용 완료", "arrival_refused": "도착 후 수용 불가", "hospital_info_confirmed": "정보 확인",
}


def _hospital_activity(hospital_id: str) -> dict:
    """의사결정 로그에서 이 병원 관련 기록만 센다(검증 화면 '우리 병원'). 통화 원문은 로그에 지문만 있다."""
    requested: set[str] = set()
    counts: dict[str, int] = {}
    recent: list[dict] = []
    try:
        lines = decision_log.LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        event, payload = entry.get("eventType"), entry.get("payload") or {}
        if event == "hub_match_result":
            if any(h.get("hospitalId") == hospital_id for h in payload.get("hospitals") or []):
                requested.add(payload.get("caseId"))
            continue
        action = payload.get("action") if isinstance(payload.get("action"), dict) else None
        if event in ("approval_action_applied", "arrival_accepted") and action and action.get("hospital_id") == hospital_id:
            kind = action.get("action")
        elif event in ("arrival_refused", "hospital_info_confirmed") and payload.get("hospitalId") == hospital_id:
            kind = event
        else:
            continue
        if kind in _ACTIVITY_LABEL:
            counts[kind] = counts.get(kind, 0) + 1
            recent.append({"timestamp": entry.get("timestamp"), "kind": kind, "label": _ACTIVITY_LABEL[kind]})
    return {
        "requestedCases": len(requested),
        "counts": [{"kind": k, "label": _ACTIVITY_LABEL[k], "count": n} for k, n in counts.items()],
        "recent": recent[-8:],
    }


@app.get("/geocode")
def get_geocode():
    """출동 시뮬레이션의 "주소 지정"(2026-10-01). 카카오 키를 브라우저에 노출하지 않게 hub가 대신 검색한다
    (/route와 같은 방식). apid를 주면 각 결과까지 그 구급차 기지에서의 예상 시간(분)을 붙인다.
    검색어는 저장·로그하지 않는다(집 주소일 수 있음)."""
    query = (request.args.get("query") or "").strip()
    apid = request.args.get("apid")
    body: dict = {"results": [], "source": "rule"}
    status = 200
    if router is None:
        body["error"] = "주소 검색을 쓸 수 없습니다(KAKAO_REST_API_KEY 없음)"
    elif not 2 <= len(query) <= 60:
        body["error"] = "검색어는 2~60자"
        status = 400
    else:
        now = time.time()
        with _geocode_lock:
            _geocode_calls[:] = [t for t in _geocode_calls if now - t < 60]
            limited = len(_geocode_calls) >= GEOCODE_PER_MIN
            if not limited:
                _geocode_calls.append(now)
        if limited:
            body["error"] = "검색이 너무 잦습니다 — 잠시 뒤 다시 시도"
            status = 429
        else:
            results = router.search_places(query)
            base = engine.get_ambulance_base(apid) if apid else None
            if base is not None and results:
                points = {str(i): GpsPoint(lat=r["lat"], lng=r["lng"]) for i, r in enumerate(results)}
                etas = router.etas(base.gps, points)
                for i, r in enumerate(results):
                    eta = etas.get(str(i))
                    km = haversine_km(base.gps.lat, base.gps.lng, r["lat"], r["lng"])
                    r["etaMin"] = max(1, round(eta[0] / 60)) if eta else max(1, round(km * DEFAULT_MIN_PER_KM))
                    r["etaBasis"] = "eta" if eta else "estimate"
            body["results"] = results
    response = jsonify(body)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response, status


@app.get("/geocode/reverse")
def get_geocode_reverse():
    """좌표 → 주소(2026-10-27). 아이패드 인계확인서의 "출발지 주소"가 좌표 대신 실제 주소를 적으려고 부른다.
    /geocode와 같은 이유로 hub가 대신 부르고(카카오 키를 화면에 노출하지 않는다) 같은 분당 한도를 쓴다.
    좌표는 저장·로그하지 않는다(사고 현장 위치)."""
    body: dict = {"address": None, "source": "rule"}
    status = 200
    try:
        lat, lng = float(request.args.get("lat", "")), float(request.args.get("lng", ""))
    except ValueError:
        body["error"] = "lat·lng 쿼리 파라미터가 필요하다"
        status = 400
    else:
        if router is None:
            body["error"] = "주소 변환을 쓸 수 없습니다(KAKAO_REST_API_KEY 없음)"
        else:
            now = time.time()
            with _geocode_lock:
                _geocode_calls[:] = [t for t in _geocode_calls if now - t < 60]
                limited = len(_geocode_calls) >= GEOCODE_PER_MIN
                if not limited:
                    _geocode_calls.append(now)
            if limited:
                body["error"] = "요청이 너무 잦습니다 — 잠시 뒤 다시 시도"
                status = 429
            else:
                body["address"] = router.reverse_geocode(GpsPoint(lat=lat, lng=lng))
    response = jsonify(body)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response, status


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


@app.get("/hospital-backup")
def get_hospital_backup():
    """대시보드 [배후역량] 버튼(2026-10-08) — 한 병원의 배후진료를 보유(심평원)·운영/정원(E-Gen)·지금 가용(E-Gen,
    이송 확정 차감 반영)으로 모아 돌려준다(HubEngine.build_backup_view). 매칭 결과에 싣지 않고 누를 때만 가져와
    카드 데이터가 커지지 않게 했다. 인증 없는 조회라 /identity처럼 CORS를 연다."""
    hospital_id = (request.args.get("id") or "").strip()
    view = engine.build_backup_view(hospital_id) if hospital_id else None
    if view is None:
        response, status = jsonify({"error": f"모르는 병원입니다: {hospital_id or '(id 없음)'}"}), 404
    else:
        response, status = jsonify(view.model_dump()), 200
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response, status


@app.get("/hospital-features")
def get_hospital_features():
    """spider 거미줄 제안용 병원 정보(2026-10-15, HubEngine.spider_features) — hub가 순위에 쓰는 E-Gen·심평원 재료와 병상
    정보 신뢰도 곡선을 병원마다. spider 서버가 같은 맥에서 30초마다 가져간다(공개 터널엔 열지 않는다). 읽기 전용."""
    return jsonify({"hospitals": engine.spider_features(), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}), 200


#: 현재 매칭 결과를 받는 병원들(caseId -> hpid 집합). 재매칭으로 빠진 병원에는
#: 새 환자 정보 대신 요청 철회(case_closed)만 보내 이전 카드를 지운다.
_case_audience: dict[str, set[str]] = {}


def _match_recipients(payload: dict) -> tuple[str | None, set[str]]:
    """매칭 결과를 받을 (구급차 apid, 병원 hpid 집합). _sockets_lock을 쥔 채로 부른다."""
    case_id = payload["caseId"]
    hospital_ids = {h.get("hospitalId") for h in dashboard_payload(payload).get("hospitals") or []}
    audience = _case_audience.setdefault(case_id, set())
    audience.clear(); audience.update(hospital_ids)
    return payload.get("apid") or engine.get_case_apid(case_id), set(hospital_ids)


def _send_to_dashboard(payload: dict) -> None:
    """dashboard 소켓들에 보낸다. 매칭 결과는 **그 사건과 관련된 소켓에만** 보낸다
    (2026-10-01 역할별 전송) — 그 구급차(apid) 탭과, 후보에 오른 적 있는 병원(hpid) 탭.
    예전엔 모든 사건이 모든 탭으로 나가 무관한 병원 탭도 통화 전문까지 받았다. identify를
    아직 안 보낸 소켓은 매칭 결과를 받지 않는다(연결 직후 identify → 따라잡기로 받는다).
    매칭 결과가 아닌 메시지(case_closed 등)는 전부에게 보낸다 — 사건 식별자뿐이다.

    delivery.py의 send_to_dashboard()는 로컬 저장 스텁 그대로 두고, 실제
    실시간 전송은 WebSocket 연결을 쥐고 있는 여기서 처리한다. 전송 실패한
    소켓은 죽은 것으로 보고 집합에서 뺀다 (voice의 send_to_hub()와 동일한
    방어 패턴 — 연결이 없거나 끊겼어도 본 요청은 계속돼야 함)."""
    if payload.get("type") == "case_closed" and payload.get("caseId"):
        _archive_call("close", payload["caseId"])
    is_match = payload.get("type") == "match_result" and bool(payload.get("caseId"))
    if is_match:
        payload = dashboard_payload(payload)
        payload = {**payload, "paused": _case_paused(payload["caseId"])}
        ambulance = engine.get_ambulance(payload.get("apid")) if payload.get("apid") else None
        _archive_call("observe", {**payload, "ambulanceName": ambulance.name if ambulance else None})
        case_tracker.observe(payload)  # 관제 지도 사건 기록(2026-10-04) — 직전 결과와 비교해 이벤트를 남긴다
        _touch_zone_timer(payload)
        # 다음 자동 존 확장 시각(2026-10-16) — 관제 지도만 받던 값을 구급차·병원 탭도(아이패드 병원 리스트의 "Zone 2로 확장까지 N초")
        payload["zoneExpandAt"] = _zone_expand_at(payload)
        payload["zonePausedLeftSec"] = _zone_paused_left(payload)
    message = json.dumps(payload, ensure_ascii=False)
    with _sockets_lock:
        if is_match:
            previous_audience = set(_case_audience.get(payload["caseId"], set()))
            apid, hospital_ids = _match_recipients(payload)
            withdrawn = previous_audience - hospital_ids
        dead = set()
        for ws in _dashboard_sockets:
            if is_match:
                role, id_ = _socket_identity.get(ws, (None, None))
                if role == "hospital" and id_ in withdrawn:
                    # 새 환자 정보는 보내지 않고 이전 요청 카드만 회수한다.
                    try:
                        ws.send(json.dumps({"type": "case_closed", "caseId": payload["caseId"], "reason": "ktas_dispatch_changed"}))
                    except Exception:
                        dead.add(ws)
                    continue
                if not ((role == "ambulance" and id_ == apid) or (role == "hospital" and id_ in hospital_ids)):
                    continue
            try:
                ws.send(message)
            except Exception as e:  # noqa: BLE001
                print(f"  [통신] dashboard WebSocket 전송 실패, 연결 제거: {e}")
                dead.add(ws)
        _dashboard_sockets.difference_update(dead)
        if is_match:
            _send_to_monitors_locked(_monitor_case(payload))

        # 매칭 결과라면 "이 사건이 어느 병원 대시보드에 실제로 도달했나"를
        # 누적 기록한다 (무응답 로그의 reachedAtBroadcast 판정 재료).
        if payload.get("type") == "match_result" and payload.get("caseId"):
            case_id = payload["caseId"]
            hospital_ids = {h.get("hospitalId") for h in payload.get("hospitals") or []}
            connected = {
                hid for sock, (role, hid) in _socket_identity.items()
                if role == "hospital" and sock in _dashboard_sockets
            }
            _case_reach.setdefault(case_id, set()).update(hospital_ids & connected)
            _case_last_activity[case_id] = datetime.now(timezone.utc)
    # 수용 상태·확정이 바뀌면 1순위 겹침도 바뀐다 — 락을 놓은 뒤 다시 판정한다
    if is_match or payload.get("type") == "case_closed":
        _reevaluate_assignment()


# ── 상황실 배정 에이전트(2026-11-04, assignment_agent.py) ──────────────────────
# 평상시엔 구급대원이 1순위 수용 병원으로 바로 이송 승인한다. 여러 사건의 1순위가 같은 병원인데 여력이 모자라면
# 그 사건들을 "관제 판단 대기"로 묶는다 — 구급대 탭엔 dispatcher_pending, 관제엔 assignment_conflicts, 구급대원의
# 이송 승인은 관제가 정할 때까지 막는다(관제는 dispatcher final_approval로 지정). 판정은 매번 엔진 상태에서 다시
# 계산하므로 저장하지 않는다(재시작해도 같은 결과).
_assignment_lock = threading.Lock()
_assignment_groups: list[dict] = []
_assignment_pending: dict[str, str] = {}  # caseId -> 충돌 병원
_assignment_opened: dict[str, str] = {}  # caseId -> 관제 판단 대기가 시작된 시각(관제 화면의 대기 시간 알림 재료)
_assignment_last_sent: dict | None = None
_assignment_stats = {"decided": 0, "followed": 0}  # 관제 지정 수 · 그중 에이전트 제안을 따른 수(hub 재시작 시 0)  # 관제에 마지막으로 보낸 묶음·배분 안 — 같으면 다시 안 보낸다


def _assignment_capacity(hospital_id: str) -> int | None:
    """여력 = 응급실 가용 − 이송 중(effective_bed_count). 미상·1일 넘은 값이면 None(모름)."""
    info = engine.get_hospital(hospital_id)
    if info is None or _is_bed_count_unknown(info) or _is_bed_data_stale(info, datetime.now(timezone.utc)):
        return None
    return engine.effective_bed_count(info)


def _hospital_name(hospital_id: str) -> str | None:
    info = engine.get_hospital(hospital_id)
    return info.name if info is not None else None


def _assignment_snapshot() -> dict:
    """관제로 보내는 충돌 묶음 + 묶음마다 배분 안·근거(2026-11-04 2단계). 엔진의 지금 상태로 매번 만든다."""
    with _assignment_lock:
        groups = [dict(g) for g in _assignment_groups]
    for g in groups:
        g["hospitalName"] = _hospital_name(g["hospitalId"])
        with _assignment_lock:
            opened = [_assignment_opened[c] for c in g["caseIds"] if c in _assignment_opened]
        g["openedAt"] = min(opened) if opened else None
        results = {}
        for case_id in g["caseIds"]:
            result = engine.get_case_result(case_id)
            if result is not None:
                results[case_id] = result.model_dump()
        infos = {}
        for result in results.values():
            for h in result["hospitals"]:
                info = engine.get_hospital(h["hospitalId"])
                if info is not None:
                    infos[h["hospitalId"]] = info.model_dump()
        g["proposal"] = assignment_agent.build_proposal(g, results, infos, _assignment_capacity)
        for c in g["proposal"]["cases"]:
            asked = _confirm_requests.get(c["caseId"], {})
            for h in c["candidates"]:
                h["confirmRequestedAt"] = asked.get(h["hospitalId"])
    return {"type": "assignment_conflicts", "groups": groups, "source": "rule", "rule": assignment_agent.RULE,
            "stats": dict(_assignment_stats)}


def _dispatcher_pending_message(case_id: str, hospital_id: str | None) -> dict:
    return {"type": "dispatcher_pending", "caseId": case_id, "pending": hospital_id is not None,
            "hospitalId": hospital_id, "hospitalName": _hospital_name(hospital_id) if hospital_id else None}


def _send_dispatcher_pending(case_id: str, hospital_id: str | None) -> None:
    apid = engine.get_case_apid(case_id)
    with _sockets_lock:
        targets = [ws for ws, (role, id_) in _socket_identity.items() if role == "ambulance" and apid and id_ == apid]
    for ws in targets:
        _send_to_socket(ws, _dispatcher_pending_message(case_id, hospital_id), "관제 판단 대기")


def _is_dispatcher_pending(case_id: str) -> bool:
    with _assignment_lock:
        return case_id in _assignment_pending


def _log_assignment_decision(case_id: str, hospital_id: str) -> None:
    """관제가 충돌 사건을 지정했을 때 제안을 따랐는지 남긴다(15장 "의료진 자문 채택 지표"의 재료)."""
    with _assignment_lock:
        snapshot = _assignment_last_sent
    proposed = next((c["proposedHospitalId"] for g in (snapshot or {}).get("groups", [])
                     for c in g["proposal"]["cases"] if c["caseId"] == case_id), None)
    _assignment_stats["decided"] += 1
    _assignment_stats["followed"] += int(proposed == hospital_id)
    decision_log.log_decision("assignment_decided", {"caseId": case_id, "hospitalId": hospital_id,
                                                     "proposedHospitalId": proposed,
                                                     "followedProposal": proposed == hospital_id})


def _reevaluate_assignment(force: bool = False) -> None:
    """진행 사건 전체의 1순위 겹침을 다시 판정하고, 묶음이나 배분 안이 바뀌었을 때만 관제·구급대에 알린다.
    묶음이 그대로여도 수용 곤란·새 수용·부하가 바뀌면 배분 안은 다시 계산돼 관제 모달이 따라간다."""
    global _assignment_last_sent
    results = [r for r in (engine.get_case_result(c) for c in engine.get_active_case_ids()) if r is not None]
    groups = assignment_agent.detect_conflicts(results, _assignment_capacity)
    pending = assignment_agent.pending_cases(groups)
    with _assignment_lock:
        groups_changed = groups != _assignment_groups
        before = dict(_assignment_pending)
        _assignment_groups[:] = groups
        _assignment_pending.clear()
        _assignment_pending.update(pending)
        now_iso = _utcnow_iso()
        for c in pending:
            _assignment_opened.setdefault(c, now_iso)
        for c in [c for c in _assignment_opened if c not in pending]:
            _assignment_opened.pop(c)
    snapshot = _assignment_snapshot()
    with _assignment_lock:
        if snapshot == _assignment_last_sent and not force:
            return
        _assignment_last_sent = snapshot
    opened = {c: h for c, h in pending.items() if before.get(c) != h}
    closed = sorted(c for c in before if c not in pending)
    # 무엇을 제안했는지 남긴다 — 관제 결정이 제안을 따랐는지(assignment_decided) 셀 재료
    plans = [{"hospitalId": g["hospitalId"], "plan": {c["caseId"]: c["proposedHospitalId"] for c in g["proposal"]["cases"]}}
             for g in snapshot["groups"]]
    if groups_changed:
        decision_log.log_decision("assignment_conflicts", {"groups": groups, "opened": sorted(opened), "closed": closed,
                                                           "plans": plans})
    else:
        decision_log.log_decision("assignment_proposal", {"plans": plans})
    with _sockets_lock:
        _send_to_monitors_locked(snapshot)
    for case_id, hospital_id in opened.items():
        _send_dispatcher_pending(case_id, hospital_id)
    for case_id in closed:
        _send_dispatcher_pending(case_id, None)


_confirm_requests: dict[str, dict[str, str]] = {}  # caseId -> {hospitalId: 요청 시각} — 배분 안 근거에 "확인 요청함"을 보인다


def _hospital_sockets(hospital_id: str) -> list:
    with _sockets_lock:
        return [w for w, (role, id_) in _socket_identity.items() if role == "hospital" and id_ == hospital_id]


def _case_brief(case_id: str) -> dict:
    """병원 화면 알림에 싣는 사건 개요 — 구급대·Pre-KTAS·주 호소만(통화 전문 없음)."""
    result = engine.get_case_result(case_id)
    if result is None:
        return {}
    p = result.patientInfo
    return {"ambulanceName": result.ambulanceName, "ktasLevel": p.ktasLevel,
            "chiefComplaint": p.chiefComplaint or p.expectedDiagnosis}


def _handle_confirm_request(ws, payload: dict) -> None:
    """관제의 [수용 확인 요청](2026-11-04): 수용 회신이 없는 병원에 상황실이 다시 묻는다. 병원 화면에 dispatcher_request.
    hospitalIds가 없으면 그 사건의 판단 대기·전달 대상 병원 전부. 관제 소켓에서만 받는다."""
    case_id = payload.get("caseId")
    if _socket_identity.get(ws, (None, None))[0] != "monitor":
        _notify_refused(ws, case_id, "not_dispatcher")
        return
    if _case_paused(case_id):
        _notify_result(ws, case_id, "confirm_request", False, "paused")
        return
    result = engine.get_case_result(case_id) if case_id else None
    if result is None:
        _notify_result(ws, case_id, "confirm_request", False, "unknown_case")
        return
    wanted = set(payload.get("hospitalIds") or [])
    targets = [h for h in dashboard_payload(result.model_dump())["hospitals"]
               if h["status"] == "pending" and (not wanted or h["hospitalId"] in wanted)]
    now = _utcnow_iso()
    brief = _case_brief(case_id)
    delivered = []
    for h in targets:
        message = {"type": "dispatcher_request", "caseId": case_id, "hospitalId": h["hospitalId"], "at": now, **brief}
        socks = _hospital_sockets(h["hospitalId"])
        for w in socks:
            _send_to_socket(w, message, "상황실 수용 확인 요청")
        if socks:
            delivered.append(h["hospitalId"])
        _confirm_requests.setdefault(case_id, {})[h["hospitalId"]] = now
    decision_log.log_decision("dispatcher_confirm_request", {
        "caseId": case_id, "hospitalIds": [h["hospitalId"] for h in targets], "delivered": delivered, "timestamp": now})
    _notify_result(ws, case_id, "confirm_request", bool(targets), None if targets else "no_pending_hospital")
    _reevaluate_assignment(force=True)


def _send_dispatcher_designated(case_id: str, hospital_id: str, timestamp: str) -> None:
    """상황실 지정(2026-11-04): 병원이 수용 회신 전인데 상황실이 지정했다 — 그 병원 화면에 알린다(개정법의 지정 통보 자리)."""
    socks = _hospital_sockets(hospital_id)
    message = {"type": "dispatcher_designated", "caseId": case_id, "hospitalId": hospital_id, "at": timestamp,
               **_case_brief(case_id)}
    for w in socks:
        _send_to_socket(w, message, "상황실 지정")
    decision_log.log_decision("dispatcher_designated", {"caseId": case_id, "hospitalId": hospital_id,
                                                        "delivered": len(socks), "timestamp": timestamp})


# ── 관제 시연 상황 부여 · 다수 사상자 신고(2026-11-04) ─────────────────────────
# 시연 콘솔·관제 화면이 버튼 하나로 상황을 만든다. 실제 병원·구급차 레지스트리를 쓰고, 만든 사건은 caseId가 demo-로
# 시작하며 의사결정 로그에 demo: true로 남는다. 병상 값을 바꾸는 연출(충돌)은 info의 다음 전송(5분)이 덮어쓴다.
DEMO_CENTER = GpsPoint(lat=37.5665, lng=126.9780)
_MCI_KTAS = {"중증": (2, "중증"), "중등증": (3, "중등증"), "경증": (4, "경증")}
_mci_incidents: dict[str, dict] = {}  # 다수 사상자 신고 id -> 등록 내용(관제 [출동 지시]가 쓴다)
#: 구급차 1대가 태우는 사상자 수(초안) — 중증·중등증은 1명, 경증은 2명까지 함께 이송
MCI_PER_AMBULANCE = {"중증": 1, "중등증": 1, "경증": 2}


def _mci_needed_ambulances(counts: dict[str, int]) -> int:
    return sum(-(-counts.get(sev, 0) // per) for sev, per in MCI_PER_AMBULANCE.items())


def _ambulance_pos(apid: str) -> GpsPoint | None:
    info = engine.get_ambulance(apid)
    return (sim.gps_for(apid) if sim is not None else None) or (info.gps if info else None)


def _idle_ambulances_near(gps: GpsPoint, n: int) -> list[str]:
    """출동하지 않은(사건 없는) 구급차를 가까운 순으로 n대."""
    rows = []
    for a in engine.list_ambulances():
        state = sim.state(a.apid) if sim is not None else None
        if state and state.get("phase") not in (None, "idle"):
            continue
        if engine.get_case_ids_for_apid(a.apid):
            continue
        pos = _ambulance_pos(a.apid)
        if pos is not None:
            rows.append((haversine_km(gps.lat, gps.lng, pos.lat, pos.lng), a.apid))
    return [apid for _, apid in sorted(rows)[:n]]


def _nearest_center(gps: GpsPoint, levels=("권역응급의료센터",)) -> HospitalInfo | None:
    rows = [(haversine_km(gps.lat, gps.lng, h.gps.lat, h.gps.lng), h) for h in engine.list_hospitals()
            if h.emergencyLevel in levels]
    return min(rows, key=lambda r: r[0])[1] if rows else None


def _demo_case(apid: str, ktas: int, complaint: str) -> str:
    """시연 사건 하나 — 구급대에 묶고 통화 요약(v2 형식)을 바로 매칭한다(작업 스레드 안에서 부른다)."""
    import uuid
    case_id = f"demo-{uuid.uuid4().hex[:8]}"
    engine.register_case(case_id, apid)
    # 출동 시뮬레이션이 켜져 있으면 구급차를 그 사건 현장에 도착한 상태로 둔다 — 확정되면 병원으로 출발해 사건이 끝까지 간다
    if sim is not None:
        pos = _ambulance_pos(apid)
        if pos is not None and sim.place_on_scene(apid, case_id, pos):
            _broadcast_sim_state(apid)
    voice = VoiceCallSummaryMessage.model_validate({
        "caseId": case_id, "source": "ai",
        "transcript": {"raw_text": f"[시연] {complaint}", "filtered_text": f"[시연] {complaint}"},
        "summary": {"ktas_level": ktas, "chief_complaint": {"major": complaint, "minor": complaint}},
    })
    _run_match_job(voice)
    return case_id


def _demo_act(case_id: str, action: str, hospital_id: str, reason: str | None = None) -> None:
    _handle_dashboard_action({"caseId": case_id, "action": action, "hospital_id": hospital_id, "actor": "hospital",
                              "timestamp": _utcnow_iso(), **({"reason": reason} if reason else {})})


def _top_pending(case_id: str, skip: set[str] = frozenset()) -> str | None:
    result = engine.get_case_result(case_id)
    if result is None:
        return None
    for h in dashboard_payload(result.model_dump())["hospitals"]:
        if h["status"] == "pending" and h["hospitalId"] not in skip and not h.get("unavailableReason"):
            return h["hospitalId"]
    return None


def _demo_approve_next(case_id: str, skip: set[str]) -> str | None:
    """판단 대기 병원을 순서대로 수용시켜 본다 — 실제 데이터엔 응급실 만실(수용 거부)인 병원이 많다."""
    tried = set(skip)
    for _ in range(8):
        hid = _top_pending(case_id, tried)
        if hid is None:
            return None
        _demo_act(case_id, "hospital_approve", hid)
        if engine.get_case_status(case_id, hid) == "approved":
            return hid
        tried.add(hid)
    return None


def _run_demo_scenario(kind: str, ws) -> None:
    """시연 콘솔·관제의 [상황 부여] — 작업 스레드에서 돈다."""
    ok, note, made = True, "", []
    try:
        if kind == "conflict":
            # 권역센터 한 곳이 두 환자의 1순위 수용 병원이 되고 여력이 1석 → 관제 판단 대기(배정 요청 모달)
            center = _nearest_center(DEMO_CENTER)
            if center is None:
                raise RuntimeError("권역응급의료센터 정보가 없습니다")
            if engine.effective_bed_count(center) != 1 or _is_bed_count_unknown(center):
                engine.update_hospital_info(center.model_copy(update={
                    "availableBedCount": 1, "bedsByType": {**(center.bedsByType or {}), "ER_ADULT": 1}}))
                decision_log.log_decision("demo_bed_override", {"hospitalId": center.hospitalId, "beds": 1, "demo": True})
            apids = _idle_ambulances_near(center.gps, 2)
            if len(apids) < 2:
                raise RuntimeError("대기 중인 구급차가 2대 필요합니다")
            made = [_demo_case(apids[0], 1, "심정지 의심"), _demo_case(apids[1], 2, "뇌졸중 의심")]
            for case_id in made:
                _demo_act(case_id, "hospital_approve", center.hospitalId)
            # 2호차엔 권역센터보다 뒤 순위인 대안 병원도 수용 — 1순위는 둘 다 권역센터로 남고, 배분 안이 2호차를 대안으로 옮긴다
            # 수용 병원끼리는 finalScore 순이라, 권역센터보다 점수가 높은 병원을 수용시키면 그쪽이 1순위가 돼 충돌이 풀린다
            result = engine.get_case_result(made[1])
            hs = dashboard_payload(result.model_dump())["hospitals"] if result else []
            center_score = next((h.get("finalScore") or 0.0 for h in hs if h["hospitalId"] == center.hospitalId), 0.0)
            ahead = {h["hospitalId"] for h in hs if (h.get("finalScore") or 0.0) >= center_score}
            _demo_approve_next(made[1], ahead | {center.hospitalId})
            note = f"{center.name} 여력 1석 · 환자 2명"
        elif kind == "refusal":
            # 병원이 '수술실 사용 중'으로 수용 곤란 → 30분 동안 다른 사건에서 그 병원 +15분(학습 반영)
            apids = _idle_ambulances_near(DEMO_CENTER, 2)
            if len(apids) < 2:
                raise RuntimeError("대기 중인 구급차가 2대 필요합니다")
            first = _demo_case(apids[0], 2, "흉통")
            top = _top_pending(first)
            if top is None:
                raise RuntimeError("요청 병원이 없습니다")
            _demo_act(first, "hospital_reject", top, "OR_OCCUPIED")
            made = [first, _demo_case(apids[1], 2, "흉통")]
            note = f"{_hospital_name(top)} 수술실 사용 중 → 다음 사건에 30분 반영"
        elif kind == "no_accept":
            # 아무도 수용 회신을 안 한 사건 — 사건 상세에서 [수용 확인 요청]·[상황실 지정]
            apids = _idle_ambulances_near(DEMO_CENTER, 1)
            if not apids:
                raise RuntimeError("대기 중인 구급차가 없습니다")
            made = [_demo_case(apids[0], 2, "의식 저하")]
            note = "수용 회신 없음 — 관제가 수용 확인 요청 또는 상황실 지정"
        elif kind == "recent_block":
            # 1순위 병원이 1시간 전 대동맥응급 차단 공지 → 첫 동시 전송에서 보류(존을 넓히면 포함)
            center = _nearest_center(DEMO_CENTER, ("권역응급의료센터", "지역응급의료센터"))
            apids = _idle_ambulances_near(center.gps if center else DEMO_CENTER, 1)
            if center is None or not apids:
                raise RuntimeError("센터 병원과 대기 구급차가 필요합니다")
            start = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
            block = {"kind": "severe", "message": "[시연] 흉부외과 의료진 부족", "department": "흉부외과",
                     "diseaseGroup": "대동맥응급", "startAt": start}
            engine.update_hospital_info(center.model_copy(update={
                "acceptanceMessages": [*(center.acceptanceMessages or []), AcceptanceMessage(**block)]}))
            decision_log.log_decision("demo_block_message", {"hospitalId": center.hospitalId, "demo": True})
            made = [_demo_case(apids[0], 2, "대동맥 박리 의심")]
            note = f"{center.name} 최근 차단 공지 → 첫 동시 전송 보류"
        else:
            raise RuntimeError(f"모르는 상황: {kind}")
    except Exception as e:  # noqa: BLE001
        ok, note = False, str(e)
    decision_log.log_decision("demo_scenario", {"kind": kind, "ok": ok, "note": note, "caseIds": made, "demo": True})
    _notify_result(ws, made[0] if made else None, f"demo_scenario:{kind}", ok, note)


def _plan_mci(gps: GpsPoint, counts: dict[str, int], radius_km: float = 15.0) -> dict:
    """다수 사상자 예상 분배(규칙 — spider 줄 길이 + 배정마다 부하, 확인된 병상 여력까지). 확정이 아니라 미리 보기다."""
    import spider_rule
    hour = spider_rule.local_hour(datetime.now(timezone.utc))
    near = []
    for h in engine.list_hospitals():
        km = haversine_km(gps.lat, gps.lng, h.gps.lat, h.gps.lng)
        if km <= radius_km:
            unknown = _is_bed_count_unknown(h)
            near.append({"info": h, "km": km, "beds": None if unknown else engine.effective_bed_count(h), "given": 0,
                         "bySev": {}})
    summary = {}
    for n in near:
        level = n["info"].emergencyLevel or "기타"
        row = summary.setdefault(level, {"count": 0, "beds": 0, "unknown": 0})
        row["count"] += 1
        if n["beds"] is None:
            row["unknown"] += 1
        else:
            row["beds"] += n["beds"]
    unplaced = 0
    for sev in ("중증", "중등증", "경증"):
        k, _ = _MCI_KTAS[sev]
        for _ in range(max(0, int(counts.get(sev, 0)))):
            best = None
            for n in near:
                if n["beds"] is not None and n["beds"] - n["given"] <= 0:
                    continue
                travel = n["km"] * DEFAULT_MIN_PER_KM
                load = 10.0 * n["given"] / (n["given"] + max(1, n["beds"] or 1))
                ln = spider_rule.line(k, "general", n["info"], travel, load, 0, hour)
                if ln["len"] is None:
                    continue
                if best is None or ln["len"] < best[0]:
                    best = (ln["len"], n)
            if best is None:
                unplaced += 1
                continue
            best[1]["given"] += 1
            best[1]["bySev"][sev] = best[1]["bySev"].get(sev, 0) + 1
    plan = sorted(({"hospitalId": n["info"].hospitalId, "name": n["info"].name, "emergencyLevel": n["info"].emergencyLevel,
                    "km": round(n["km"], 1), "beds": n["beds"], "count": n["given"], "bySeverity": n["bySev"],
                    "lat": n["info"].gps.lat, "lng": n["info"].gps.lng}
                   for n in near if n["given"]), key=lambda r: -r["count"])
    return {"hospitalsInRadius": len(near), "radiusKm": radius_km, "byLevel": summary, "plan": plan, "unplaced": unplaced}


def _handle_mci_register(ws, payload: dict) -> None:
    """관제 [다수 사상자 신고](2026-11-04): 위치·추정 사상자 수를 받아 에이전트가 반경 병원 여력 집계 → 가까운 대기 구급대
    추천 → 예상 분배(규칙)를 계산해 그 관제 탭에 mci_assessment로 돌려준다. 출동은 관제가 [출동 지시]로 정한다."""
    import uuid
    if _socket_identity.get(ws, (None, None))[0] != "monitor":
        _notify_refused(ws, None, "not_dispatcher")
        return
    try:
        gps = GpsPoint(lat=float(payload["lat"]), lng=float(payload["lng"]))
    except (KeyError, TypeError, ValueError):
        _notify_result(ws, None, "mci_register", False, "위치가 필요합니다")
        return
    counts = {k: max(0, int((payload.get("counts") or {}).get(k, 0) or 0)) for k in _MCI_KTAS}
    total = sum(counts.values())
    plan = _plan_mci(gps, counts)
    # 필요 대수만큼 가까운 대기 구급차를 찾는다 — 모자라면 그 수를 그대로 알려 인근 지역 지원을 요청하게 한다
    needed = _mci_needed_ambulances(counts)
    apids = _idle_ambulances_near(gps, needed)
    shortage = max(0, needed - len(apids))
    incident_id = f"mci-{uuid.uuid4().hex[:6]}"
    names = {a.apid: a.name for a in engine.list_ambulances()}
    _mci_incidents[incident_id] = {"gps": gps.model_dump(), "counts": counts, "apids": apids, "label": payload.get("label")}
    message = {
        "type": "mci_assessment", "incidentId": incident_id, "gps": gps.model_dump(), "label": payload.get("label"),
        "counts": counts, "total": total, "source": "rule",
        "neededAmbulances": needed, "shortage": shortage, "perAmbulance": MCI_PER_AMBULANCE,
        "ambulances": [{"apid": a, "name": names.get(a), "km": round(haversine_km(gps.lat, gps.lng, p.lat, p.lng), 1),
                        "lat": p.lat, "lng": p.lng}
                       for a in apids if (p := _ambulance_pos(a)) is not None],
        **plan,
        "steps": [
            {"stage": "인식", "source": "rule", "text": f"반경 {plan['radiusKm']:g}km 병원 {plan['hospitalsInRadius']}곳의 응급실 여력·등급 집계"},
            {"stage": "판단", "source": "rule", "text": f"사상자 {total}명을 중증부터 줄 길이·여력·부하로 분배 — {len(plan['plan'])}곳"
                                                       + (f", 미배정 {plan['unplaced']}명(범위 확장 필요)" if plan["unplaced"] else "")},
            {"stage": "행동", "source": "rule", "text": f"필요 구급차 {needed}대(중증·중등증 1명당 1대, 경증 2명당 1대) — 가까운 대기 {len(apids)}대 추천"
                                                       + (f", {shortage}대 부족 → 인근 지역 지원 요청 필요" if shortage else "")
                                                       + " · 관제가 [출동 지시]하면 출동"},
        ],
    }
    decision_log.log_decision("mci_registered", {"incidentId": incident_id, "gps": gps.model_dump(), "counts": counts,
                                                 "neededAmbulances": needed, "shortage": shortage,
                                                 "plan": plan["plan"], "unplaced": plan["unplaced"], "apids": apids})
    _send_to_socket(ws, message, "다수 사상자 분석")


def _handle_mci_dispatch(ws, payload: dict) -> None:
    """관제 [출동 지시] — 등록한 다수 사상자 현장으로 추천 구급대를 출동시킨다(출동 시뮬레이션, 사건마다 새 caseId)."""
    import uuid
    if _socket_identity.get(ws, (None, None))[0] != "monitor":
        _notify_refused(ws, None, "not_dispatcher")
        return
    incident = _mci_incidents.get(payload.get("incidentId") or "")
    if incident is None or sim is None:
        _notify_result(ws, None, "mci_dispatch", False, "출동 시뮬레이션이 꺼져 있거나 등록이 없습니다")
        return
    sent = 0
    for apid in payload.get("apids") or incident["apids"]:
        _handle_sim_command({"type": "dispatch", "apid": apid, "caseId": f"case-{uuid.uuid4().hex[:10]}",
                             "timestamp": _utcnow_iso(), "target": incident["gps"], "targetMode": "map"})
        sent += 1
    decision_log.log_decision("mci_dispatched", {"incidentId": payload.get("incidentId"), "count": sent})
    _notify_result(ws, None, "mci_dispatch", sent > 0, f"{sent}대 출동")


# ── 관제 지도(role=monitor, 2026-10-03) ─────────────────────────────────────
# 병원 대시보드는 직접 접속하지 않고, 관제 지도에서 환자 요청이 온 병원을 눌러 연다. 지도는 전체 병원·구급차
# 위치(map_overview), 사건 요약(case_overview), 구급차 이동(ambulance_phase·position)을 받는다. 통화 전문·
# 활력징후 등 환자 상세는 보내지 않는다 — 그건 요청을 받은 병원 대시보드(role=hospital)만 받는다.


#: case_overview 병원 항목에 그대로 옮기는 HospitalMatch 설명 필드(2026-10-14) — schema.MonitorCaseHospital 참고
_MONITOR_EXPLAIN_FIELDS = (
    "gps", "emergencyLevel", "availableBedCount", "bedCountUnknown", "bedDataStale", "erBedCapacity", "erOccupancyPct",
    "travelMin", "travelBasis", "etaMin", "finalScore", "specialtyMatch", "bedReliability", "reliability", "severeFreshness",
    "demoteReasons", "bonusReasons", "loadReason", "occupancyReason", "inFlightCount", "excluded", "acceptanceMessages",
    "notSelected", "ktasSuitability", "refusalPenaltyMin", "refusalReasons", "dispatchHold",
)


def _monitor_case(payload: dict) -> dict:
    """매칭 결과(HubMatchResult를 dump한 dict) → 관제 지도용 사건 요약."""
    payload = dashboard_payload(payload)
    patient = payload.get("patientInfo") or {}
    meta = case_tracker.meta(payload["caseId"]) or {}
    responded = case_tracker.responded(payload["caseId"])
    return MonitorCase(
        num=meta.get("num"), startedAt=meta.get("startedAt"), symptom=meta.get("symptom"),
        events=case_tracker.events(payload["caseId"]),
        zoneExpandAt=_zone_expand_at(payload),
        zonePausedLeftSec=_zone_paused_left(payload),
        paused=_case_paused(payload["caseId"]),
        caseId=payload["caseId"],
        apid=payload.get("apid"),
        ambulanceName=payload.get("ambulanceName"),
        ambulanceGps=payload.get("ambulanceGps"),
        severityTag=patient.get("severityTag"),
        # spider 실시간 화면용 환자 요약(2026-10-14) — 전문·활력징후는 빼고 분류 결과만
        ktasLevel=patient.get("ktasLevel"), expectedDiagnosis=patient.get("expectedDiagnosis"),
        chiefComplaint=patient.get("chiefComplaint"), requiredDepartment=patient.get("requiredDepartment"),
        patient=patient.get("patient"), confirmedBy=patient.get("confirmedBy"),
        diseaseGroup=engine.case_group(payload["caseId"]),
        dispatchPolicy=payload.get("dispatchPolicy"),
        zoneActive=payload.get("zoneActive") or [],
        zoneBandKm=ZONE_BAND_KM,
        hospitals=[
            MonitorCaseHospital(
                hospitalId=h["hospitalId"], name=h["name"],
                # 병원이 안 눌렀어도 응급실 병상 0이 확인되면(E-Gen) 지도엔 "수용 불가"로 — 판단 대기로 두면 아직
                # 답할 병원처럼 보였다(2026-10-03). E-Gen 갱신으로 병상이 생기면 재계산 때 판단 대기로 돌아온다.
                status="rejected" if h.get("unavailableReason") and h.get("status") == "pending" else h.get("status", "pending"),
                distanceKm=h["distanceKm"], roadDistanceKm=h.get("roadDistanceKm"), zone=zone_of(h["distanceKm"]),
                rejectReason=h.get("rejectReason"), unavailableReason=h.get("unavailableReason"),
                respondedAt=responded.get(h["hospitalId"]),
                # 설명 필드(2026-10-14, 아이패드 관제·spider 실시간) — HospitalMatch 값 그대로
                **{k: h.get(k) for k in _MONITOR_EXPLAIN_FIELDS},
            )
            for h in payload.get("hospitals") or []
        ],
    ).model_dump()


def _build_map_overview() -> dict:
    import spider_rule

    hour = spider_rule.local_hour(datetime.now(timezone.utc))
    ambulances = []
    for info in engine.list_ambulances():
        gps = (sim.gps_for(info.apid) if sim is not None else None) or info.gps
        ambulances.append(MapAmbulance(apid=info.apid, name=info.name, gps=gps, base=info.gps))
    def _rel(h):
        rel = engine.bed_reliability_now(h) or {}
        return {"bedAuthority": rel.get("authority"), "bedRiskLevel": rel.get("riskLevel"), "bedCheckedAt": rel.get("checkedAt")}

    return MapOverview(
        hospitals=[
            MapHospital(hospitalId=h.hospitalId, name=h.name, gps=h.gps, emergencyLevel=h.emergencyLevel, erPhone=h.erPhone,
                        **_rel(h),
                        inFlightCount=engine.in_flight_count(h.hospitalId),
                        availableBedCount=engine.effective_bed_count(h),
                        bedCountUnknown=_is_bed_count_unknown(h),
                        mapCapacity=spider_rule.hospital_z(h, hour)[1],
                        mapKtasLevel=spider_rule.ktas_suitability(3, "general", h, hour)["hospitalKtas"],
                        supportedKtas=spider_rule.ktas_suitability(3, "general", h, hour)["supportedKtas"])
            for h in engine.list_hospitals()
        ],
        ambulances=ambulances,
        simDispatch=sim is not None,
    ).model_dump()


def _send_to_monitors_locked(payload: dict) -> None:
    """관제 지도 탭 전부에 보낸다. _sockets_lock을 쥔 채로 부른다."""
    message = json.dumps(payload, ensure_ascii=False)
    for ws, (role, _id) in list(_socket_identity.items()):
        if role != "monitor":
            continue
        try:
            ws.send(message)
        except Exception as e:  # noqa: BLE001
            print(f"  [통신] 관제 지도 전송 실패: {e}")


def _send_map_overview() -> None:
    with _sockets_lock:
        if not any(role == "monitor" for role, _id in _socket_identity.values()):
            return
    overview = _build_map_overview()
    with _sockets_lock:
        _send_to_monitors_locked(overview)


# ── 현장 확인 입력 방식(2026-10-06) ───────────────────────────────────────────
# 시연 콘솔 ② 현장 확인에서 고른 방식(caseId -> "voice" | "template"). "template"(정해진 상황 선택)이면 그 사건의 현장 통화를
# 휴대폰 앱으로 시작할 수 없다 — 정해진 상황 카드와 실제 음성 요약이 같은 사건에 겹쳐 들어가지 않게. 그 구급차 화면(휴대폰
# 앱 포함)에 알려 전화 버튼을 막고, hub도 통화 시작을 거부한다(구버전 앱 대비). 콘솔이 알리지 않은 사건은 예전처럼 통화 가능.
# 이송 중(④)도 같은 방식이다(stage "transport") — "정해진 상황 선택"이면 휴대폰 앱의 [목적지 병원과 통화]가 막히고
# hub도 이송 중 추가 통화를 거부한다. 두 단계의 방식은 따로 보관한다(② 방식이 ④ 통화를 막지 않게).
SCENE_INPUT_MODES = ("voice", "template")
INPUT_MODE_STAGES = ("scene", "transport")
_input_modes: dict[str, dict[str, str]] = {stage: {} for stage in INPUT_MODE_STAGES}  # stage -> caseId -> mode
_scene_input_mode = _input_modes["scene"]


def _send_scene_input_mode(case_id: str, apid: str | None, ws=None) -> None:
    """그 구급차 소켓들에(ws를 주면 그 소켓 하나에) 사건의 현장 확인·이송 중 통화 방식을 알린다."""
    for stage in INPUT_MODE_STAGES:
        mode = _input_modes[stage].get(case_id)
        if mode is not None:
            _send_input_mode(case_id, apid, stage, mode, ws)


def _send_input_mode(case_id: str, apid: str | None, stage: str, mode: str, ws=None) -> None:
    payload = {"type": "scene_input_mode", "caseId": case_id, "apid": apid, "mode": mode, "stage": stage}
    if ws is not None:
        _send_to_socket(ws, payload, "현장 확인 방식 따라잡기")
        return
    message = json.dumps(payload)
    with _sockets_lock:
        for sock, (role, id_) in list(_socket_identity.items()):
            if role == "ambulance" and id_ == apid:
                try:
                    sock.send(message)
                except Exception as e:  # noqa: BLE001
                    print(f"  [통신] 현장 확인 방식 전송 실패: {e}")


def _handle_scene_input_mode(payload: dict) -> None:
    case_id, mode, stage = payload.get("caseId"), payload.get("mode"), payload.get("stage") or "scene"
    if not case_id or mode not in SCENE_INPUT_MODES or stage not in INPUT_MODE_STAGES \
            or _input_modes[stage].get(case_id) == mode:
        return
    _input_modes[stage][case_id] = mode
    apid = engine.get_case_apid(case_id) or payload.get("apid")
    _send_input_mode(case_id, apid, stage, mode)


# ── 시연 영상 모드(2026-10-06) ─────────────────────────────────────────────────
# 시연 사이사이에 화면마다 정해진 영상을 띄워 둔다. 콘솔 [영상 모드]·영상 위 [시연 모드] 버튼이 demo_mode를 보내면 연결된
# 모든 화면(관제 지도·병원·콘솔·구급차, 맥·리눅스 구분 없이)에 같은 모드를 알린다. 화면은 시연 상태를 그대로 둔 채
# 영상을 덮어 띄우므로, 시연 모드로 돌아오면 직전 상태 그대로다. 사건·로그와 무관한 화면 연출이라 저장하지 않는다.
DEMO_MODES = ("live", "video")
_demo_mode = "live"


def _set_demo_mode(mode: str) -> None:
    global _demo_mode
    if mode not in DEMO_MODES:
        return
    _demo_mode = mode
    message = json.dumps({"type": "demo_mode", "mode": mode})
    with _sockets_lock:
        for ws in list(_dashboard_sockets):
            try:
                ws.send(message)
            except Exception as e:  # noqa: BLE001 — 끊긴 소켓은 수신 루프가 정리한다
                print(f"  [통신] 영상 모드 전송 실패: {e}")
    print(f"  [시연] {'영상 모드' if mode == 'video' else '시연 모드'}로 전환 — 화면 {len(_dashboard_sockets)}개")


def _send_to_socket(ws, payload: dict, label: str) -> None:
    """소켓 하나에만 보낸다(따라잡기·신원 확인 응답). 브로드캐스트와 같은 락을 쓴다."""
    with _sockets_lock:
        try:
            ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            print(f"  [통신] {label} 전송 실패: {e}")


# 사건별 미응답은 수용 거절과 별개이며 기존 scene 캐시와 함께 정리된다.
import first_call
_first_call_lock = threading.RLock()
_first_call_coordinator = first_call.Coordinator()

def _handle_first_call(ws, payload):
    with _first_call_lock:
        _apply_first_call(ws, payload)


def _apply_first_call(ws, payload):
    case_id = payload.get("caseId")
    role, apid = _socket_identity.get(ws, (None, None))
    if role != "ambulance" or not case_id or engine.get_case_apid(case_id) != apid:
        _send_to_socket(ws, {"type": "first_call_error", "message": "현재 구급대 사건이 아닙니다"}, "첫 통화")
        return
    if _case_paused(case_id):
        return
    previous = _case_scene.get(case_id, {})
    attempts = list(previous.get("callAttempts", []))
    hid = payload.get("noAnswerHospitalId")
    if hid:
        valid = {h["hospitalId"] for h in previous.get("hospitals", [])}
        if hid not in valid:
            return
        if hid not in attempts:
            attempts.append(hid)
            decision_log.log_decision("first_call_no_answer", {"caseId": case_id, "hospitalId": hid, "source": "rule"})
    # 원래 현장 좌표를 유지하며 재연결에도 미응답 이력을 보존한다.
    gps = previous.get("ambulanceGps")
    _case_scene[case_id] = {**previous, "callAttempts": attempts}
    _send_scene_candidates(case_id, apid, GpsPoint(**gps) if gps else None)


def _send_scene_candidates(case_id: str, apid: str, scene_gps: GpsPoint | None = None, cascade: bool = True) -> None:
    # 추천 계산과 의향 반영을 직렬화해 동시 요청의 중복 추천을 줄인다.
    with _first_call_lock:
        changed = _build_scene_candidates(case_id, apid, scene_gps)
        if not (cascade and changed):
            return
        # 이 사건의 추천 병원이 바뀌면 그 병원의 점유가 달라졌으니, 아직 통화 전인 다른 구급차 사건의 목록도 바로 다시 계산해 보낸다
        # (구급차가 다시 요청할 때까지 기다리면 두 폰이 같은 병원을 추천받은 채로 남는다). 연쇄 갱신은 한 번만 — 서로 추천을 뺏고
        # 뺏기는 순환을 막으려고 다시 계산하는 쪽은 또 다른 쪽을 부르지 않는다.
        for other_id, scene in list(_case_scene.items()):
            if other_id == case_id or not isinstance(scene, dict) or not scene.get("hospitals"):
                continue
            other_apid = scene.get("apid") or engine.get_case_apid(other_id)
            if not other_apid or engine.get_case_result(other_id) is not None:
                continue   # 이미 요약이 병원들에 전달된 사건은 추천 단계가 끝났다
            gps = scene.get("ambulanceGps")
            _build_scene_candidates(other_id, other_apid, GpsPoint(**gps) if gps else None)


def _build_scene_candidates(case_id: str, apid: str, scene_gps: GpsPoint | None = None) -> bool:
    """환자 정보가 오기 전, 후보를 그 구급차 탭에만 보낸다(2026-10-01). 규칙 기반(이동·병상·전문의·
    도착 유효 확률 + 다른 구급차 점유, first_call.rank)이고 진료과 매칭·승인은 아직 없어서, 병원 탭에는 보내지 않는다.

    2026-10-04: **출동 지령 즉시**에도 보낸다(scene_gps = 사고 현장 좌표) — 1차 신고에서
    증상·중증도를 이미 아는데 가추천이 현장 도착까지 기다릴 이유가 없다. 기준점은 구급차
    현재 위치가 아니라 **현장**(이송 출발지)이다. 현장 통화(2차)가 끝나면 확정 매칭이
    이 가추천을 대체한다."""
    if scene_gps is not None:
        gps, fallback = scene_gps, False
    else:
        gps, fallback = _resolve_ambulance_gps(case_id)
    zone = engine.resolve_start_zone(gps)
    # 신고 접수 1차 증상(2026-10-04)은 순위에 쓰지 않는다(시민 신고라 임상 근거가 약하다, 2026-11-03) —
    # 전화 앱 머리에 "신고: 흉통(중증)"을 띄울 재료로만 같이 보낸다.
    pre = _pre_alerts.get(case_id) or {}
    reported_severity = pre.get("reportedSeverity")
    hospitals = engine.build_zone_candidates(gps, max_zone=zone)
    previous = _case_scene.get(case_id, {})
    attempts = previous.get("callAttempts", [])
    attempted_rows = []
    now_mono = time.monotonic()
    with _sockets_lock:
        calls = list(_case_call.values())
    results = engine.list_case_results()
    active_ids = set(_case_scene) | {r.caseId for r in results}
    # 완료 사건은 남아 있는 캐시가 있어도 부하에서 제외한다.
    active_ids = set(engine.list_open_case_ids())
    transport_etas = {}
    if sim is not None:
        for r in results:
            state = sim.state(r.apid) if r.apid else None
            if state and state.get("caseId") == r.caseId and state.get("phase") == "transporting" and state.get("etaSec") is not None:
                for h in r.hospitals:
                    if h.status == "confirmed": transport_etas[r.caseId, h.hospitalId] = state["etaSec"] / 60
    loads = _first_call_coordinator.pressure(case_id, active_ids, calls, results, now_mono, transport_etas)
    while True:
        fresh, attempted_rows = first_call.rank(hospitals, attempts, loads)
        if fresh or zone >= 10:
            hospitals = fresh + attempted_rows
            # 통화 요청·통화 중에는 현재 선택을 유지한다.
            current = next((c for c in calls if c.get("caseId") == case_id and c.get("state") in ("ringing", "calling")), None)
            stable_id = current.get("hospitalId") if current else None
            stable = next((h for h in fresh if h["hospitalId"] == stable_id), None)
            if stable:
                for h in hospitals: h["firstCallRecommended"] = h is stable
            chosen = next((h for h in hospitals if h.get("firstCallRecommended")), None)
            _first_call_coordinator.remember(case_id, chosen["hospitalId"] if chosen else None, now_mono)
            break
        zone += 1
        hospitals = engine.build_zone_candidates(gps, max_zone=zone)

    payload = {
        "type": "scene_candidates",
        "caseId": case_id,
        "apid": apid,
        "ambulanceGps": gps.model_dump(),
        "ambulanceGpsFallback": fallback,
        "zoneActive": list(range(1, zone + 1)),
        "hospitals": hospitals,
        "callAttempts": attempts,
        "firstCallExhausted": not any(h.get("firstCallRecommended") for h in hospitals),
        "reportedSymptom": pre.get("reportedSymptom"),
        "reportedSeverity": reported_severity,
        "source": "rule",
    }
    # 첫 연락 추천(2026-10-03)을 의사결정 로그에 남긴다 — 추천 병원이 실제 첫 통화·수용으로
    # 이어졌는지(적중률)를 나중에 승인 액션·거절 로그와 대조해 셀 수 있는 유일한 재료라서다.
    recommended = next((h for h in hospitals if h.get("firstCallRecommended")), None)
    changed = (recommended["hospitalId"] if recommended is not None else None) != _case_recommended.get(case_id)
    if recommended is not None:
        _case_recommended[case_id] = recommended["hospitalId"]
        decision_log.log_decision("first_call_recommended", {
            "caseId": case_id,
            "apid": apid,
            "hospitalId": recommended["hospitalId"],
            "coordination": recommended.get("coordination"),
            "source": "rule",
            "reason": recommended.get("firstCallReason"),
            "distanceKm": recommended["distanceKm"],
            "availableBedCount": recommended["availableBedCount"],
        })
    with _sockets_lock:
        _case_scene[case_id] = payload
        targets = [ws for ws, (role, id_) in _socket_identity.items() if role == "ambulance" and id_ == apid]
    for ws in targets:
        _send_to_socket(ws, payload, "현장 후보")
    return changed


# ── 중앙 voice·통화 상태 (2026-10-03) ───────────────────────────────────────
# 중앙 voice가 등록돼 있으면 모든 구급차 통화를 거기로 보낸다: 대시보드(휴대폰·태블릿)가 브라우저 마이크 음성을
# 16kHz 16비트 PCM 바이너리 프레임으로 보내면, 그 소켓이 지금 통화 중인 사건의 전송기(_AudioRelay)가 모아서
# 0.25초마다 voice로 넘긴다. 음성은 저장·로그하지 않고 전달만 한다. 중앙 voice가 없으면 예전처럼 구급차별 voice로
# 신호만 중계하고 브라우저 음성은 버린다.

#: 중앙 voice 주소와 마지막 등록 시각(monotonic). voice가 30초마다 다시 등록한다.
_central_voice: dict = {}
CENTRAL_VOICE_STALE_SEC = 90.0
#: 대시보드 소켓 -> 그 소켓이 지금 음성을 보내는 사건(caseId)
_socket_call: dict = {}
#: caseId -> 음성 전송기
_audio_relays: dict = {}
#: caseId -> 통화 상태(call_status 메시지 본문). 사건이 닫히면 지운다.
_case_call: dict[str, dict] = {}
#: caseId -> 현장 후보의 첫 연락 추천 병원(first_call_selected 기록용)
_case_recommended: dict[str, str] = {}
#: caseId -> 마지막으로 보낸 현장 후보. 현장 도착 뒤에 연 휴대폰 탭도 병원 목록을 받게 따라잡기로 다시 준다.
_case_scene: dict[str, dict] = {}
AUDIO_RELAY_INTERVAL_SEC = 0.25


def _central_voice_url() -> str | None:
    with _voice_addresses_lock:
        url, seen = _central_voice.get("url"), _central_voice.get("seenAt")
    if url and seen is not None and time.monotonic() - seen <= CENTRAL_VOICE_STALE_SEC:
        return url
    return None


class _AudioRelay:
    """한 통화의 음성을 모아 순서대로 voice에 넘긴다. finish()하면 남은 음성을 다 보낸 뒤 /call/end를 보낸다
    (종료 신호가 마지막 음성보다 먼저 가면 voice가 끝부분을 놓친다)."""

    def __init__(self, case_id: str, base_url: str) -> None:
        self.case_id = case_id
        self.base_url = base_url
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._finishing = threading.Event()
        self._end_payload: dict | None = None
        self.bytes_sent = 0
        threading.Thread(target=self._run, name=f"audio-{case_id[:8]}", daemon=True).start()

    def push(self, chunk: bytes) -> None:
        with self._lock:
            self._buffer.extend(chunk)

    def finish(self, end_payload: dict) -> None:
        self._end_payload = end_payload
        self._finishing.set()

    def _flush(self) -> None:
        with self._lock:
            data, self._buffer = bytes(self._buffer), bytearray()
        if not data:
            return
        try:
            requests.post(f"{self.base_url}/call/{self.case_id}/audio", data=data,
                          headers={"Content-Type": "application/octet-stream"}, timeout=5)
            self.bytes_sent += len(data)
        except requests.RequestException as e:
            print(f"  [통신] caseId={self.case_id} 음성 전달 실패: {e}")

    def _run(self) -> None:
        while not self._finishing.wait(AUDIO_RELAY_INTERVAL_SEC):
            self._flush()
        self._flush()
        try:
            requests.post(f"{self.base_url}/call/end", json=self._end_payload or {"caseId": self.case_id}, timeout=10)
        except requests.RequestException as e:
            print(f"  [통신] caseId={self.case_id} 중앙 voice 통화 종료 전달 실패: {e}")
        with _sockets_lock:
            if _audio_relays.get(self.case_id) is self:
                del _audio_relays[self.case_id]
        print(f"  [통신] caseId={self.case_id} 통화 음성 {self.bytes_sent / 32000:.1f}초 분량 전달 완료")


def _handle_audio_frame(ws, chunk: bytes) -> None:
    """대시보드가 보낸 음성 프레임 — 그 소켓이 중앙 voice로 통화 중이면 그 사건 전송기로, 아니면 버린다."""
    with _sockets_lock:
        case_id = _socket_call.get(ws)
        relay = _audio_relays.get(case_id) if case_id else None
    if relay is not None:
        relay.push(chunk)


def _call_status_targets_locked(status: dict) -> list:
    """통화 상태를 받을 소켓: 그 구급차 탭 전부(휴대폰·태블릿) + 전화 건 병원 탭 + 관제 지도. _sockets_lock 안에서."""
    targets = []
    for ws, (role, id_) in _socket_identity.items():
        if role == "monitor" or (role == "ambulance" and id_ == status["apid"]) or \
                (role == "hospital" and status.get("hospitalId") and id_ == status["hospitalId"]):
            targets.append(ws)
    return targets


def _send_call_status(status: dict) -> None:
    with _sockets_lock:
        if "requestId" not in status and status.get("state") == "calling":
            status = {**status, "requestId": _case_call.get(status["caseId"], {}).get("requestId")}
        _case_call[status["caseId"]] = status
        targets = _call_status_targets_locked(status)
    for ws in targets:
        _send_to_socket(ws, status, "통화 상태")


_call_connection_lock = threading.RLock()
_call_request_sockets = {}

def _handle_call_connection(ws, payload):
    """시연 연결 결과. ringing 동안 voice/녹음은 시작하지 않는다."""
    with _call_connection_lock:
        cid, hid, rid = payload.get("caseId"), payload.get("hospitalId"), payload.get("requestId")
        role, actor = _socket_identity.get(ws, (None, None))
        apid = engine.get_case_apid(cid) if cid else None
        op = payload.get("operation")
        if not apid or not isinstance(rid, str) or not rid or len(rid) > 100:
            return
        status = _case_call.get(cid, {})
        owner = role == "ambulance" and actor == apid
        if op == "request":
            if not owner or not engine.get_hospital(hid) or status.get("state") in ("ringing", "calling"):
                return
            if _case_paused(cid) or (sim is not None and (sim.case_of(apid) != cid or sim.phase_of(apid) not in CALLABLE_PHASES)):
                _send_to_socket(ws, {"type":"call_connection_error", "requestId":rid}, "전화 연결")
                return
            hospital = engine.get_hospital(hid)
            _call_request_sockets[cid] = ws
            _send_call_status({"type":"call_status", "caseId":cid, "apid":apid, "hospitalId":hid,
                              "hospitalName":hospital.name, "state":"ringing", "startedAt":payload.get("timestamp", ""),
                              "requestId":rid, "device":"phone", "followup":engine.get_case_result(cid) is not None})
            return
        if status.get("requestId") != rid or status.get("hospitalId") != hid or status.get("state") != "ringing":
            return
        responder = role == "monitor" or (role == "hospital" and actor == hid)
        if op == "answer" and responder:
            signal = CallSignal(signal="call_started", timestamp=payload.get("timestamp", ""), apid=apid, caseId=cid, hospitalId=hid, device="phone")
            origin = _call_request_sockets.pop(cid, None)
            if origin is None or _socket_identity.get(origin) != ("ambulance", apid):
                _send_call_status({**status, "state":"cancelled", "cancelled":True})
                return
            _relay_call_signal(signal, origin)
            if _case_call.get(cid, {}).get("state") == "ringing":
                _send_call_status({**status, "state":"cancelled", "cancelled":True})
        elif (op == "no_answer" and (owner or responder)) or (op == "cancel" and owner):
            _call_request_sockets.pop(cid, None)
            _first_call_coordinator.release(cid)
            _send_call_status({**status, "state":"no_answer" if op == "no_answer" else "cancelled", "cancelled":True})
            if op == "no_answer":
                previous = _case_scene.get(cid, {})
                attempts = list(previous.get("callAttempts", []))
                if hid not in attempts: attempts.append(hid)
                _case_scene[cid] = {**previous, "callAttempts":attempts}
                decision_log.log_decision("first_call_no_answer", {"caseId":cid,"hospitalId":hid,"source":"rule"})
                gps = previous.get("ambulanceGps")
                _send_scene_candidates(cid, apid, GpsPoint(**gps) if gps else None)


def _relay_call_signal(signal: CallSignal, ws=None) -> None:
    """dashboard의 통화 시작/종료 신호를 그 apid로 등록된 feature/voice
    인스턴스로 중계한다. call_started 시점에 (caseId -> apid)를 hub_engine에
    등록해둬야, 나중에 그 caseId로 도착하는 /voice/summary가 이 구급차의
    GPS를 찾을 수 있다. voice가 아직 자가등록 전이거나 안 떠 있어도
    dashboard 쪽 흐름은 끊기면 안 되므로 예외를 흡수한다."""
    if signal.signal == "call_started":
        # 대시보드 통화가 꺼져 있으면 휴대폰 전화 앱으로만 받는다(2026-10-03). 화면엔 버튼이 없지만 열려 있던 구버전
        # 탭이 보낼 수 있어 hub도 막는다. device가 없는 예전 신호는 그대로 받는다(하위 호환).
        if signal.device == "tablet" and not DASHBOARD_CALL:
            print(f"  [통화] {signal.apid} 대시보드 통화 시작 거부 — 휴대폰 전화 앱으로만(HUB_DASHBOARD_CALL=1로 켬)")
            decision_log.log_decision("call_start_refused", {"apid": signal.apid, "caseId": signal.caseId,
                                                             "reason": "dashboard_call_off"})
            return
        # 출동 시뮬레이션 중엔 그 출동의 사건으로만, 현장 도착 뒤에 통화한다(버튼만 막는 게 아니라 hub도 규칙을
        # 지킨다). 2026-10-05부터 "사건당 통화 한 번"은 현장 첫 연결에만 해당한다 — 환자 상태가 바뀌면 이송 중
        # (목적지 병원)이나 재선택 대기 중에도 다시 통화할 수 있다. 새 요약은 환자 정보에 덧붙는다.
        if sim is not None and (sim.phase_of(signal.apid) not in CALLABLE_PHASES or sim.case_of(signal.apid) != signal.caseId):
            print(f"  [시뮬레이션] {signal.apid} 통화 시작 거부 — 현장 도착 전이거나 다른 사건")
            decision_log.log_decision("call_start_refused", {"apid": signal.apid, "caseId": signal.caseId,
                                                             "phase": sim.phase_of(signal.apid)})
            _notify_refused(ws, signal.caseId, "phase")
            return
        if _case_paused(signal.caseId):
            decision_log.log_decision("call_start_refused", {"apid": signal.apid, "caseId": signal.caseId,
                                                             "reason": "paused"})
            _notify_refused(ws, signal.caseId, "paused")
            return
        # 콘솔이 "정해진 상황 선택"으로 두면 그 단계의 통화는 받지 않는다 — 현장 첫 통화(매칭 전)는 ② 방식,
        # 이송 중 추가 통화는 ④ 방식(2026-10-06). 재선택 대기(rerouting)의 통화는 콘솔 ④와 무관해 막지 않는다.
        in_transport = sim is not None and sim.phase_of(signal.apid) == "transporting"
        blocked = (_input_modes["transport"].get(signal.caseId) == "template" if in_transport
                   else _scene_input_mode.get(signal.caseId) == "template" and engine.get_case_result(signal.caseId) is None)
        if blocked:
            print(f"  [통화] {signal.apid} 통화 시작 거부 — 콘솔이 정해진 상황 선택 중")
            decision_log.log_decision("call_start_refused", {"apid": signal.apid, "caseId": signal.caseId,
                                                             "reason": "template_mode"})
            _notify_refused(ws, signal.caseId, "template_mode")
            return
        engine.register_case(signal.caseId, signal.apid)
        followup = engine.get_case_result(signal.caseId) is not None
        if not followup:
            _send_scene_candidates(signal.caseId, signal.apid)
        ambulance = engine.get_ambulance(signal.apid)
        hospital = engine.get_hospital(signal.hospitalId) if signal.hospitalId else None
        case_tracker.start(signal.caseId, signal.apid, ambulance.name if ambulance else None)
        phase = sim.phase_of(signal.apid) if sim is not None else None
        label = "이송 중 추가 통화" if phase == "transporting" else "추가 통화" if followup else "현장 통화 시작"
        case_tracker.event(signal.caseId, "p", label + (f" · {hospital.name}" if hospital else ""))
        _send_call_status({
            "type": "call_status", "caseId": signal.caseId, "apid": signal.apid,
            "ambulanceName": ambulance.name if ambulance else None,
            "hospitalId": signal.hospitalId, "hospitalName": hospital.name if hospital else None,
            "device": signal.device, "state": "calling", "startedAt": signal.timestamp, "endedAt": None,
            "followup": followup, "cancelled": False,
        })
        if followup:
            _start_call_hold(signal.caseId, signal.apid)
        if signal.hospitalId and not followup:
            # 첫 연락 추천이 실제로 맞았나 — 추천과 구급대원이 고른 병원을 나란히 남긴다(적중률 재료).
            recommended = _case_recommended.get(signal.caseId)
            decision_log.log_decision("first_call_selected", {
                "caseId": signal.caseId, "apid": signal.apid, "hospitalId": signal.hospitalId,
                "recommendedHospitalId": recommended, "followedRecommendation": recommended == signal.hospitalId,
                "device": signal.device,
            })
    else:
        with _sockets_lock:
            status = dict(_case_call.get(signal.caseId) or {})
        if status:
            _send_call_status({**status, "state": "ended", "endedAt": signal.timestamp,
                               "cancelled": bool(signal.cancelled)})
        if signal.cancelled:
            _release_call_hold(signal.caseId, "cancelled")
        else:
            with _call_holds_lock:
                if signal.caseId in _call_holds:
                    _call_holds[signal.caseId]["deadline"] = time.time() + CALL_HOLD_AFTER_END_SEC
        if signal.cancelled:
            case_tracker.event(signal.caseId, "c", "통화 취소 — 전달하지 않음")
            decision_log.log_decision("call_cancelled", {"apid": signal.apid, "caseId": signal.caseId,
                                                         "hospitalId": signal.hospitalId, "device": signal.device})

    central_url = _central_voice_url()
    if central_url is not None:
        _relay_to_central_voice(signal, ws, central_url)
        return

    with _voice_addresses_lock:
        voice_base_url = _voice_addresses.get(signal.apid)
    if voice_base_url is None:
        print(f"  [통신] {signal.apid}의 voice 주소가 아직 등록되지 않아 신호 중계를 건너뜀")
        return

    path = "/call/start" if signal.signal == "call_started" else "/call/end"
    try:
        requests.post(
            f"{voice_base_url}{path}",
            json={"timestamp": signal.timestamp, "caseId": signal.caseId, "cancelled": bool(signal.cancelled)},
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"  [통신] {signal.apid}의 feature/voice로 통화 신호 중계 실패 ({path}): {e}")


def _relay_to_central_voice(signal: CallSignal, ws, base_url: str) -> None:
    """중앙 voice로 통화 시작·종료를 보내고, 그 사이 이 소켓의 음성 프레임을 그 사건 전송기로 묶는다."""
    if signal.signal == "call_started":
        try:
            response = requests.post(f"{base_url}/call/start", json={
                "caseId": signal.caseId, "apid": signal.apid, "hospitalId": signal.hospitalId,
                "timestamp": signal.timestamp,
            }, timeout=10)
            if response.status_code >= 400 and response.status_code != 409:
                print(f"  [통신] 중앙 voice 통화 시작 거부({response.status_code}): {response.text[:200]}")
                return
        except requests.RequestException as e:
            print(f"  [통신] 중앙 voice로 통화 시작 전달 실패: {e}")
            return
        with _sockets_lock:
            if signal.caseId not in _audio_relays:
                _audio_relays[signal.caseId] = _AudioRelay(signal.caseId, base_url)
            if ws is not None:
                _socket_call[ws] = signal.caseId
        print(f"  [통신] {signal.apid} 통화 시작 → 중앙 voice (caseId={signal.caseId})")
        return

    with _sockets_lock:
        relay = _audio_relays.get(signal.caseId)
        for sock in [s for s, cid in _socket_call.items() if cid == signal.caseId]:
            del _socket_call[sock]
    end_payload = {"caseId": signal.caseId, "timestamp": signal.timestamp, "cancelled": bool(signal.cancelled)}
    if relay is not None:
        relay.finish(end_payload)  # 남은 음성을 다 보낸 뒤 /call/end
        return
    try:
        requests.post(f"{base_url}/call/end", json=end_payload, timeout=10)
    except requests.RequestException as e:
        print(f"  [통신] 중앙 voice로 통화 종료 전달 실패: {e}")


def _send_catchup(ws, identify: DashboardIdentify) -> list[str]:
    """소켓이 연결 직후 보낸 자기소개(DashboardIdentify)에 답한다. hub는
    보통 새 매칭 결과가 생길 때만 그 순간 연결된 소켓들에 브로드캐스트하는데,
    이미 진행 중인 사건이 있는 상태에서 새 탭이 뒤늦게 연결되면 그 브로드캐스트를
    놓쳐서 화면에 아무것도 안 뜨는 문제가 있었다(schema.py의 DashboardIdentify
    문서 참고, 2026-08-11 실제 재현됨). 이 소켓과 관련된 사건들만 골라 지금
    즉시 이 소켓에만 한 번씩 보내준다 — 형식은 평소 브로드캐스트와 같은
    HubMatchResult라 dashboard는 "따라잡기 메시지"인지 구분할 필요 없이
    받은 대로 처리하면 된다."""
    if identify.role == "monitor":
        cases = engine.list_case_results()
        print(f"  [통신] 관제 지도 연결 — 진행 중인 사건 {len(cases)}건 요약 전송")
        for result in cases:
            _send_to_socket(ws, _monitor_case(result.model_dump()), "관제 지도 따라잡기")
        matched = {result.caseId for result in cases}
        for case_id in list(_pre_alerts):
            if case_id not in matched:
                _send_case_meta(case_id, ws)
        _send_to_socket(ws, CaseHistory(cases=case_tracker.history()).model_dump(), "지난 사건")
        return [result.caseId for result in cases]
    cases = (
        engine.get_cases_for_hospital(identify.id)
        if identify.role == "hospital"
        else engine.get_cases_for_apid(identify.id)
    )
    print(f"  [통신] {identify.role} {identify.id} 연결 — 진행 중인 사건 {len(cases)}건 따라잡기 전송")
    for result in cases:
        dumped = dashboard_payload(result.model_dump())
        if identify.role == "hospital":
            with _sockets_lock:
                _case_audience.setdefault(result.caseId, set()).add(identify.id)
        _send_to_socket(ws, {**dumped, "paused": _case_paused(result.caseId), "zoneExpandAt": _zone_expand_at(dumped),
                             "zonePausedLeftSec": _zone_paused_left(dumped)}, "따라잡기")
        # 따라잡기로 받아 본 것도 "도달"이다 — 뒤늦게 연결한 병원이 요청을
        # 봤는데 무응답이면 미도달이 아니라 무시로 분류돼야 한다.
        if identify.role == "hospital" and any(
            h.hospitalId == identify.id for h in result.hospitals
        ):
            with _sockets_lock:
                _case_reach.setdefault(result.caseId, set()).add(identify.id)
    return [result.caseId for result in cases]


def _resolve_identity(role: str, id_: str) -> tuple[str | None, bool]:
    """role(hospital/ambulance)과 id(hpid/apid)로 hub가 아는 실제 이름과
    존재 여부를 찾는다. WebSocket의 identify 응답과 HTTP `GET /identity`
    양쪽이 같은 로직을 쓴다."""
    if role == "monitor":
        return "관제 지도", True
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
    # 자기 위치(2026-10-04) — 병원 대시보드가 사건 없이도 본원 지도를 그리게 한다
    gps = None
    if identify.role == "hospital":
        hospital = engine.get_hospital(identify.id)
        gps = hospital.gps if hospital else None
    elif identify.role == "ambulance":
        ambulance = engine.get_ambulance(identify.id)
        gps = ambulance.gps if ambulance else None
    info = DashboardIdentityInfo(
        role=identify.role, id=identify.id, name=name, known=known, simDispatch=sim is not None,
        dashboardCall=DASHBOARD_CALL, gps=gps,
    )
    print(f"  [통신] {identify.role} {identify.id} 신원 확인 응답 — known={known}, name={name}")
    _send_to_socket(ws, info.model_dump(), "identity_info")


# hospital_score 신뢰도 tier(문자열 라벨) -> "물어볼 당시 병원이 뭐라고 신고했나".
# declaredAtRequest로 넘기면 info가 "가능이라 신고했는데 거절"을 셀 수 있어
# 신고 정확도를 운영 데이터로 직접 측정한다(CLAUDE.md "거절 로그" 절). 미상
# tier(unknown_*)는 신고 자체가 없었다는 뜻이라 필드를 아예 넣지 않는다.
_TIER_TO_DECLARED = {"declared_yes": "Y", "declared_no": "불가능"}


def _hospital_dashboard_connected(hospital_id: str) -> bool:
    """이 병원의 대시보드 소켓이 지금 연결돼 있는가 (identify 기준)."""
    with _sockets_lock:
        return any(
            role == "hospital" and hid == hospital_id
            for role, hid in _socket_identity.values()
        )


def _send_selection_released(case_id: str, result, timestamp: str) -> None:
    """이송이 확정된 순간, **승인했지만 선택되지 않은** 병원들에 "선택되지 않았습니다"를 즉시 보낸다(2026-10-22).

    임상 자문 요구 — *"다수 병원이 수용 가능성을 회신하더라도 실제 수용 확약은 최종 선택한 한 병원에만 부여하고,
    나머지 병원에는 선택되지 않았음을 즉시 자동으로 알리는 기능이 필요합니다."* 수용 승낙은 빈 병상 확인이 아니라
    처치 공간 확보·기존 진료 조정·신규 수용 제한 같은 자원 선배정이라, 알려 주지 않으면 그 준비가 묶여 있는다.

    매칭 결과의 `notSelected` 깃발(hub_engine._mark_not_selected)과 같은 사실을 **푸시로** 한 번 더 보내는 것이다 —
    병원 화면이 카드 목록을 다시 훑지 않아도 바로 안내를 띄울 수 있게. 승인 자체는 풀지 않는다(status는 approved
    그대로): 이동 중 재선택의 대상으로 남아야 한다는 원칙 그대로다. 근거·수치는 poc/CLINICAL_CONVERGENCE.md §4
    (배정이 공유되지 않으면 도착 거절이 12~72% 늘고, 거절만 공유해도 대부분 되찾는다).
    """
    confirmed = next((h for h in result.hospitals if h.status == "confirmed"), None)
    released = [h.hospitalId for h in result.hospitals if h.notSelected]
    if confirmed is None or not released:
        return
    payload = {
        "type": "selection_released",
        "caseId": case_id,
        "confirmedHospitalId": confirmed.hospitalId,
        "confirmedHospitalName": confirmed.name,
        "timestamp": timestamp,
    }
    message_by_hospital = {
        hid: json.dumps({**payload, "hospitalId": hid}, ensure_ascii=False) for hid in released
    }
    sent, dead = [], set()
    with _sockets_lock:
        for ws in _dashboard_sockets:
            role, id_ = _socket_identity.get(ws, (None, None))
            if role != "hospital" or id_ not in message_by_hospital:
                continue
            try:
                ws.send(message_by_hospital[id_])
                sent.append(id_)
            except Exception as e:  # noqa: BLE001
                print(f"  [통신] 미선택 통보 전송 실패, 연결 제거: {e}")
                dead.add(ws)
        _dashboard_sockets.difference_update(dead)
    print(f"  [통신] 미선택 통보 — 확정 {confirmed.hospitalId} / 대상 {released} / 전달 {sent}")
    # 통보 누락·지연을 나중에 셀 수 있게 "보낼 대상"과 "실제 전달"을 따로 남긴다. 떠 있지 않은 병원 탭은
    # 다음 identify 따라잡기에서 notSelected 깃발로 같은 사실을 받는다.
    decision_log.log_decision("selection_released", {
        "caseId": case_id, "confirmedHospitalId": confirmed.hospitalId,
        "releasedHospitalIds": released, "deliveredHospitalIds": sent, "timestamp": timestamp,
    })


def _send_dispatcher_notice(case_id: str, kind: str, hospital, timestamp: str) -> int:
    """관제가 구급대원 대신 한 일을 그 사건의 구급차 화면에 알린다(2026-11-01). 전달한 소켓 수를 돌려준다.
    메시지: dispatcher_notice {caseId, kind, hospitalId, hospitalName, timestamp} — kind는 지금 "transport_confirmed"뿐,
    구급 앱이 모르는 type은 버리므로 먼저 보내도 안전하다. 구급 화면이 안 떠 있으면 0(로그에 남아 나중에 셀 수 있다)."""
    apid = engine.get_case_apid(case_id)
    payload = {"type": "dispatcher_notice", "caseId": case_id, "kind": kind, "hospitalId": hospital.hospitalId,
               "hospitalName": hospital.name, "timestamp": timestamp}
    with _sockets_lock:
        targets = [ws for ws, (role, id_) in _socket_identity.items() if role == "ambulance" and apid and id_ == apid]
    for ws in targets:
        _send_to_socket(ws, payload, "관제 알림")
    decision_log.log_decision("dispatcher_notice", {**payload, "apid": apid, "delivered": len(targets)})
    return len(targets)


def _rejection_payload(case_id: str, hospital_id: str, timestamp: str, reason_code: str) -> dict:
    """feature/info 거절 로그 수신구가 받는 형태로 조립한다. 필수는 hospitalId
    하나뿐이고(수신구가 관대하게 받는다), 나머지는 사건 캐시에서 best-effort로
    채운다 — 조회가 실패하면 그 필드만 빠지고 전달 자체는 계속된다(거절 로그는
    소급 생성이 안 되므로 부분 정보라도 남기는 게 낫다).

    `*AtRequest` 필드들은 **결정 시점의 스냅샷**(2026-09-28 확충)이다 — 그때
    화면에 뭐가 보였고 시스템이 뭘 믿었는지가 로그에 없으면, 나중에 "가능이라
    떠 있었는데 거절"(신고 정확도)이나 "authority 90%였는데 만실 거절"(확률의
    운영 검증, G2 라벨)을 소급해서 셀 방법이 없다.
    """
    payload: dict = {
        "hospitalId": hospital_id,
        "caseId": case_id,
        "timestamp": timestamp,
        "reasonCode": reason_code,
    }

    result = engine.get_case_result(case_id)
    if result is None:
        return payload
    payload["severity"] = result.patientInfo.severityTag
    match = next((h for h in result.hospitals if h.hospitalId == hospital_id), None)
    if match is None:
        return payload

    # 결정 시점 스냅샷 — 그때 대시보드에 보였던 병상·이동시간·순위 점수와
    # 병상 신뢰도 확률. BEDS_FULL 거절과 대조하면 정보 무효의 독립 관측
    # (infosurv G2 라벨)이 된다.
    payload["availableBedCountAtRequest"] = match.availableBedCount
    payload["bedCountUnknownAtRequest"] = match.bedCountUnknown
    payload["bedDataStaleAtRequest"] = match.bedDataStale
    if match.travelMin is not None:
        payload["travelMinAtRequest"] = match.travelMin
    if match.finalScore is not None:
        payload["finalScoreAtRequest"] = match.finalScore
    if match.bedReliability is not None:
        payload["bedAuthorityAtRequest"] = match.bedReliability.authority
        payload["bedRArriveAtRequest"] = match.bedReliability.rArrive

    if match.reliability is not None:
        group = match.reliability.group
        payload["diseaseGroup"] = group
        info = engine.get_hospital(hospital_id)
        group_score = (
            info.assessment.groups.get(group)
            if info is not None and info.assessment is not None
            else None
        )
        declared = _TIER_TO_DECLARED.get(getattr(group_score, "tier", None))
        if declared is not None:
            payload["declaredAtRequest"] = declared

    return payload


def _build_rejection_payload(action: ApprovalAction) -> dict:
    payload = _rejection_payload(
        action.caseId, action.hospital_id, action.timestamp, action.reason or "UNSPECIFIED"
    )
    # 도착 전 응답(병원 화면의 "불가")과 도착 후 수용 불가를 구분한다(2026-10-01). 도착 후 거절은
    # 구급차가 실제로 가서 확인한 결과라 신뢰도 모델의 가장 강한 독립 관측(G2)이다.
    payload["stage"] = {"arrival_refused": "arrival", "transport_withdraw": "transport"}.get(action.action, "request")
    return payload


#: 확정 없이 이 시간(분) 넘게 활동이 없는 사건은 "미결 종료"로 보고 무응답을
#: 정리 기록한 뒤, 사건을 닫는다(close_case — 캐시·따라잡기·주기 재계산에서 빠지고
#: 대시보드에 case_closed를 보낸다. 2026-10-01). 사건 내용은 의사결정 로그에 이미
#: 남아 있다. 0 이하면 끈다.
UNRESOLVED_CASE_TIMEOUT_MIN = float(os.environ.get("HUB_UNRESOLVED_TIMEOUT_MIN", "120"))


def _log_no_responses(case_id: str, timestamp: str, finalized_to: str | None) -> None:
    """사건이 끝난 시점(도착 수용·현장 종료·미결 방치, 2026-10-01부터)에, 여전히 무응답
    (pending)인 후보들을 거절 로그에 남긴다 — CLAUDE.md 거절 로그 절의
    "무응답(NO_RESPONSE)도 반드시 남길 것"(없으면 낮은 점수가 낮은 점수를
    재생산하는 되먹임이 생긴다).

    ⚠ 소비 주의 — 무응답은 거절과 **다른 축**의 신호다: 수용 능력이 아니라
    채널에 대한 정보라, 수용성 판정(G2 라벨·assessment 검증)에는 쓰지 말고
    보급(미도달)·응답성(무시) 지표로만 분리 집계해야 한다. 그 구분을 위해:
    - `reachedAtBroadcast`: 사건 진행 중 이 병원 대시보드에 요청이 실제로
      도달한 이력이 있는가 (_case_reach — 도달했는데 무응답 = 무시)
    - `hospitalDashboardConnected`: 기록 순간의 연결 여부 (보조 신호)
    - `caseFinalized`: 확정된 사건인가, 확정 없이 방치된 사건인가 — 미결
      사건의 무응답은 요청 자체가 유효했는지 모호하므로(데모·중단 포함)
      분석에서 따로 걸러야 한다
    """
    with _sockets_lock:
        if case_id in _case_swept:
            return  # 이미 기록한 사건 (중복 final_approval·sweep 재방문 방지)
        _case_swept.add(case_id)
        reach = _case_reach.pop(case_id, set())
        _case_last_activity.pop(case_id, None)

    result = engine.get_case_result(case_id)
    if result is None:
        return
    logged = 0
    for match in result.hospitals:
        if match.hospitalId == finalized_to or match.status != "pending":
            continue
        if "beds_full" in match.demoteReasons:
            # 병상 0이 확인돼 승인 버튼이 막혀 있던 병원 — 응답할 수 없었던 것이지 무시한 게 아니다(2026-10-01).
            continue
        payload = _rejection_payload(case_id, match.hospitalId, timestamp, "NO_RESPONSE")
        payload["reachedAtBroadcast"] = match.hospitalId in reach
        payload["hospitalDashboardConnected"] = _hospital_dashboard_connected(match.hospitalId)
        payload["caseFinalized"] = finalized_to is not None
        if finalized_to is not None:
            payload["finalizedTo"] = finalized_to
        send_rejection_to_info(payload)
        logged += 1
    if logged:
        kind = "이송 확정" if finalized_to is not None else "미결 종료(sweep)"
        print(f"  [통신] {kind} — 무응답 후보 {logged}곳을 NO_RESPONSE로 거절 로그에 기록")


def _sweep_unresolved_cases(now: datetime | None = None) -> int:
    """확정 없이 방치된 사건들의 무응답을 정리 기록한다(_maintenance_loop에서
    주기 호출). 정리한 사건 수를 돌려준다."""
    if UNRESOLVED_CASE_TIMEOUT_MIN <= 0:
        return 0
    now = now or datetime.now(timezone.utc)
    with _sockets_lock:
        due = [
            case_id
            for case_id, last in _case_last_activity.items()
            if case_id not in _case_swept
            and (now - last).total_seconds() >= UNRESOLVED_CASE_TIMEOUT_MIN * 60
        ]
    for case_id in due:
        result = engine.get_case_result(case_id)
        confirmed = next((h.hospitalId for h in result.hospitals if h.status == "confirmed"), None) if result else None
        _log_no_responses(case_id, now.isoformat(timespec="seconds"), finalized_to=confirmed)
        _close_case(case_id, "unresolved_timeout")
    return len(due)


def _close_case(case_id: str, reason: str, include_confirmed: bool = False) -> bool:
    """확정 없이 끝난 사건을 닫고 대시보드에 알린다. 방치 정리(sweep)와 현장 종료가 같이 쓴다.
    include_confirmed=True면 이송 확정 사건도 닫는다(시연 초기화)."""
    if not engine.close_case(case_id, include_confirmed=include_confirmed):
        return False
    _forget_case(case_id, reason)
    return True


def _forget_case(case_id: str, reason: str) -> None:
    """사건에 딸린 hub 쪽 기록(통화 상태·현장 후보·예비 고지 등)을 지우고 대시보드에 case_closed를 보낸다.
    엔진에 없는 사건(출동만 했거나 통화가 취소돼 매칭 전인 사건)도 이걸로 닫는다 — 시연 초기화가 엔진 사건만
    닫아 이런 기록이 남으면, 따라잡기로 새로 연 화면에까지 다시 보내져 초기화가 안 된 것처럼 보였다(2026-10-06)."""
    with _sockets_lock:
        _case_audience.pop(case_id, None)
        _case_call.pop(case_id, None)
        _case_recommended.pop(case_id, None)
        _case_scene.pop(case_id, None)
    with _triage_lock:
        _transport_triage.pop(case_id, None)
    _pre_alerts.pop(case_id, None)
    _confirm_requests.pop(case_id, None)
    for modes in _input_modes.values():
        modes.pop(case_id, None)
    _record_case_closed(case_id, reason)
    decision_log.log_decision("case_closed", {"caseId": case_id, "reason": reason})
    _send_to_dashboard({"type": "case_closed", "caseId": case_id, "reason": reason})
    print(f"  [정리] caseId={case_id} 사건 종료({reason}) — 캐시에서 제거, 대시보드에 알림")


#: 출동 시뮬레이션에서 통화를 시작할 수 있는 단계 — 현장(첫 통화·추가 통화), 이송 중·재선택 대기(추가 통화, 2026-10-05)
CALLABLE_PHASES = ("on_scene", "transporting", "rerouting")


def _notify_refused(ws, case_id: str | None, reason: str) -> None:
    """조작이 거부됐다고 그 소켓에만 알린다(2026-10-05) — 대시보드가 "현재 시연 일시정지 중입니다." 같은 안내를 띄운다."""
    if ws is not None:
        _send_to_socket(ws, {"type": "action_refused", "caseId": case_id, "reason": reason}, "조작 거부")


def _notify_result(ws, case_id: str | None, action: str, ok: bool, reason: str | None = None) -> None:
    """관제 개입의 결과를 누른 소켓에만 알린다(2026-11-01) — 요청이 받아들여졌는지 화면에서 알 수 있게."""
    if ws is not None:
        _send_to_socket(ws, {"type": "action_result", "caseId": case_id, "action": action, "ok": ok, "reason": reason}, "조작 결과")


def _handle_dashboard_action(payload: dict, ws=None, allocated: bool = False) -> None:
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

    # 시연 일시정지 중엔 모든 조작을 받지 않는다(2026-10-05) — 화면에서도 막지만 다른 탭에서 우회되지 않게.
    if _case_paused(action.caseId):
        decision_log.log_decision("approval_action_refused", {"action": action.model_dump(), "reason": "paused"})
        _notify_refused(ws, action.caseId, "paused")
        return

    # dispatcher는 관제(monitor) 소켓만 쓸 수 있다 — 아무 탭이나 actor만 바꿔 관제를 사칭하지 못하게(인증이 생기기 전 최소 방어)
    if action.actor == "dispatcher" and ws is not None and _socket_identity.get(ws, (None, None))[0] != "monitor":
        decision_log.log_decision("approval_action_refused", {"action": action.model_dump(), "reason": "dispatcher requires monitor socket"})
        _notify_refused(ws, action.caseId, "not_dispatcher")
        return

    # 1순위 수용 병원이 겹쳐 여력이 모자란 사건은 관제가 정한다(2026-11-04) — 구급대원 이송 승인을 그때까지 막는다.
    # 대량사고 [분배 확정](allocated)은 관제가 이미 정한 배분이라 막지 않는다.
    if action.action == "final_approval" and action.actor == "paramedic" and not allocated \
            and _is_dispatcher_pending(action.caseId):
        decision_log.log_decision("approval_action_refused", {"action": action.model_dump(), "reason": "dispatcher_pending"})
        _notify_refused(ws, action.caseId, "dispatcher_pending")
        return

    # 승인 액션도 사건의 "활동"이다 — 미결 sweep의 유휴 판정 기준을 갱신한다.
    with _sockets_lock:
        if action.caseId not in _case_swept:
            _case_last_activity[action.caseId] = datetime.now(timezone.utc)

    # 출동 시뮬레이션 중엔 구급차가 그 병원에 실제로 도착했을 때만 도착 결과를 받는다(2026-10-01). 버튼만
    # 막는 게 아니라 hub도 지킨다 — 이송 중에 "도착 후 수용 불가"가 들어와 엔진만 바뀌고 구급차는 계속 달리는
    # 어긋남이 실서버 E2E에서 실제로 났다.
    if sim is not None and action.action in ("arrival_accepted", "arrival_refused"):
        apid = engine.get_case_apid(action.caseId)
        state = sim.state(apid) if apid else None
        if not state or state["phase"] != "at_hospital" or state["caseId"] != action.caseId \
                or state["hospitalId"] != action.hospital_id:
            print(f"  [시뮬레이션] 도착 결과 거부 — 구급차가 {action.hospital_id}에 아직 도착하지 않음")
            decision_log.log_decision("approval_action_refused", {
                "action": action.model_dump(), "reason": "ambulance has not arrived (simulation)",
                "ambulancePhase": state["phase"] if state else None})
            return
    # 구급차가 이미 도착한 뒤에는 목적지를 바꿀 수 없다. final_approval을 받아 엔진의
    # confirmed 병원만 바뀌면 도착 결과 화면이 실제 도착 병원과 다른 이름을 표시한다.
    # 도착 후 다른 병원이 수용할 수 있다면 먼저 현재 도착 병원의 arrival_refused를 기록하고
    # rerouting 단계에서 새 목적지를 확정해야 한다.
    if sim is not None and action.action == "final_approval":
        apid = engine.get_case_apid(action.caseId)
        state = sim.state(apid) if apid else None
        if state and state.get("phase") == "at_hospital" and state.get("caseId") == action.caseId:
            decision_log.log_decision("approval_action_refused", {
                "action": action.model_dump(), "reason": "destination cannot change after arrival",
                "arrivedHospitalId": state.get("hospitalId"),
            })
            _notify_refused(ws, action.caseId, "already_arrived")
            return

    # 이송 중 수용 철회(2026-10-05)는 구급차가 그 병원으로 가는 중일 때만 — 이미 도착했으면 "도착 후 수용 불가"를 쓴다.
    if sim is not None and action.action == "transport_withdraw":
        apid = engine.get_case_apid(action.caseId)
        state = sim.state(apid) if apid else None
        if not state or state["phase"] != "transporting" or state["caseId"] != action.caseId \
                or state["hospitalId"] != action.hospital_id:
            print(f"  [시뮬레이션] 이송 중 철회 거부 — 구급차가 {action.hospital_id}로 이송 중이 아님")
            decision_log.log_decision("approval_action_refused", {
                "action": action.model_dump(), "reason": "ambulance is not transporting to this hospital (simulation)",
                "ambulancePhase": state["phase"] if state else None})
            return

    # 도착 후 수용 불가는 확정을 풀기 **전에** 결정 시점 스냅샷(병상 수·확률)을 떠 둔다.
    arrival_refusal = _build_rejection_payload(action) if action.action in ("arrival_refused", "transport_withdraw") else None
    pending_decision = action.action == "final_approval" and _is_dispatcher_pending(action.caseId)
    designated = (action.action == "final_approval" and action.actor == "dispatcher"
                  and engine.get_case_status(action.caseId, action.hospital_id) == "pending")
    applied = engine.apply_approval_action(action)
    if applied and designated:
        _send_dispatcher_designated(action.caseId, action.hospital_id, action.timestamp)
    if applied:
        _archive_call("action", action.model_dump(), engine.get_case_apid(action.caseId))
        if pending_decision:
            _log_assignment_decision(action.caseId, action.hospital_id)
    if action.actor == "dispatcher":
        _notify_result(ws, action.caseId, action.action, bool(applied), None if applied else "refused")
    # spider 매칭 규칙(2026-10-15): 승인·확정·도착 결과로 부하·줄 길이가 바뀌면 다른 사건의 순위·τ 창 표시를 다시 맞춘다
    if applied:
        _match_executor.submit(_refresh_active_cases)

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
    elif action.action in ("arrival_refused", "transport_withdraw") and arrival_refusal is not None and applied:
        send_rejection_to_info(arrival_refusal)
        if action.action == "transport_withdraw":
            case_tracker.event(action.caseId, "r", "이송 중 수용 철회 — 다른 병원 재선택")
        # 승인한 다른 병원이 없으면 그 자리에서 존을 넓혀 같은 환자 정보로 다시 요청한다(재통화 없음).
        if not engine.has_other_approved(action.caseId, action.hospital_id):
            ambulance_gps, _ = _resolve_ambulance_gps(action.caseId)
            expanded_result = engine.force_expand_zone(action.caseId, ambulance_gps, cause=action.action)
    elif action.action == "arrival_accepted" and applied:
        # 무응답은 사건이 끝날 때 기록한다(2026-10-01). 예전엔 첫 이송 승인 순간에 기록해서, 그 뒤
        # 승인하고 재선택된 병원까지 "무응답"으로 남았다.
        _log_no_responses(action.caseId, action.timestamp, finalized_to=action.hospital_id)

    updated_result = expanded_result or engine.get_case_result(action.caseId)
    if updated_result is not None:
        _send_to_dashboard(updated_result.model_dump())
        # 이송이 확정됐으면 승인했지만 선택되지 않은 병원들에 즉시 알린다(2026-10-22, 임상 자문 요구).
        if action.action == "final_approval" and applied:
            _send_selection_released(action.caseId, updated_result, action.timestamp)
            if action.actor == "dispatcher":
                confirmed = next((h for h in updated_result.hospitals if h.status == "confirmed"), None)
                if confirmed is not None:
                    delivered = _send_dispatcher_notice(action.caseId, "transport_confirmed", confirmed, action.timestamp)
                    _notify_result(ws, action.caseId, "dispatcher_notice", delivered > 0, None if delivered else "no_ambulance_screen")
    if action.action == "arrival_accepted" and applied:
        # 환자 수용으로 이송이 끝났다 — 두 대시보드에서 이 사건(병원 후보·수용 요청·통화 요약)을 지운다
        # (2026-10-01). 엔진에는 기록·병상 차감 때문에 확정 60분 동안 남지만, 따라잡기에서도 빠진다.
        _record_case_closed(action.caseId, "arrival_accepted")
        _send_to_dashboard({"type": "case_closed", "caseId": action.caseId, "reason": "arrival_accepted"})

    if sim is not None and applied and action.action in ("arrival_accepted", "arrival_refused"):
        apid = engine.get_case_apid(action.caseId)
        if apid and sim.on_arrival_result(apid, action.caseId, accepted=action.action == "arrival_accepted"):
            _broadcast_sim_state(apid)
    if sim is not None and applied and action.action == "transport_withdraw":
        apid = engine.get_case_apid(action.caseId)
        if apid and sim.on_transport_withdrawn(apid, action.caseId):
            _broadcast_sim_state(apid)

    if sim is not None and action.action == "final_approval" and updated_result is not None:
        confirmed = next((h for h in updated_result.hospitals if h.status == "confirmed"), None)
        apid = engine.get_case_apid(action.caseId)
        if confirmed is not None and apid and sim.on_confirmed(apid, action.caseId, confirmed.hospitalId, confirmed.gps):
            _broadcast_sim_state(apid)

    # 확정·도착 결과는 병원별 이송 중 건수(TTL 오버레이)를 바꾼다 — 관제 지도의
    # "이 병원으로 이송 중 N건" 표시가 따라오도록 overview를 다시 보낸다(2026-10-03).
    if action.action in ("final_approval", "arrival_accepted", "arrival_refused", "transport_withdraw"):
        _send_map_overview()


def _handle_info_confirm(confirm: HospitalInfoConfirm) -> None:
    """병원 대시보드의 "현재 정보 확인" 신호 처리(2026-09-29).

    E-Gen 자기 신고 밖에서 처음 생기는 유효 확인 관측이다 — 값이 그대로여도
    "방금 사람이 확인한 정확한 값"임을 시스템이 알게 되는 유일한 경로.
    엔진에 기록해 그 병원 병상 신뢰도가 조건부 생존(S(a)/S(u))으로 되올라가게
    하고, 의사결정 로그에도 남긴다(나중에 infosurv 유효 확인 라벨 재료).
    """
    try:
        ts = datetime.fromisoformat(confirm.timestamp.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except ValueError:
        ts = datetime.now(timezone.utc)

    if not engine.confirm_hospital_info(confirm.hospitalId, ts):
        print(f"  [통신] 모르는 병원({confirm.hospitalId})의 정보 확인 — 무시")
        return
    decision_log.log_decision(
        "hospital_info_confirmed",
        {"hospitalId": confirm.hospitalId, "timestamp": confirm.timestamp},
    )
    print(f"  [통신] {confirm.hospitalId} 정보 확인 수신 — 관련 사건 신뢰도 재계산")
    # 확인 효과(확률 상승)가 다음 주기(60초)를 기다리지 않고 화면에 바로
    # 반영되게 관련 사건을 즉시 재계산한다. 임베딩·카카오 호출이 낄 수 있어
    # 소켓 스레드를 막지 않도록 작업 스레드로 넘긴다.
    _match_executor.submit(_refresh_cases_for_hospital, confirm.hospitalId)
    # 병원 자신의 화면(귀원 정보 현황)에도 ✓·확률 리셋이 즉시 뜨게 한다.
    _send_self_info_to_hospital(confirm.hospitalId)


# ── 이송 중 활력징후 모니터링 (2.5단계, 2026-10-04) ──────────────────────────
# 입력 구멍: POST /vitals(향후 119구급스마트시스템·구급차 모니터 어댑터용)와 dashboard
# WS transport_vitals(지금은 데모 시나리오·수기)가 같은 처리로 모인다. 판정은
# transport_triage.py 규칙 엔진(NEWS2 + 규칙표, source: "rule")이 하고, hub는 결과를
# 역할별로 보낸다 — 구급차 탭은 전부(자기 환자), 확정 병원 탭은 notify 이상만
# (오경보보다 침묵), 관제 지도는 heli_advisory만(환자 상세 없이).

#: 사건별 판정 상태 — 사건이 닫힐 때(_close_case) 같이 지운다.
_transport_triage: dict[str, TransportTriage] = {}
_triage_lock = threading.Lock()

#: 재검토 제안에 동봉할 대체 후보의 이동시간 상한(분). 이 안에 아무도 없으면 헬기 권고.
#: 질환별 골든타임 규칙이 정해지기 전의 단일 초기값 — TRANSPORT_TRIAGE.md 참고.
TRANSPORT_ALT_MAX_MIN = float(os.environ.get("HUB_TRANSPORT_ALT_MAX_MIN", "30"))


def _transport_alternatives(result, confirmed_id: str | None) -> list[TransportAlternative]:
    """재검토 티어에 동봉할 대체 병원 후보(최대 3곳, hub 순위 순). 결정은 사람이 한다."""
    if result is None:
        return []
    out: list[TransportAlternative] = []
    for h in result.hospitals:
        if h.hospitalId == confirmed_id or h.status not in ("approved", "pending"):
            continue
        if h.demoteReasons:
            continue  # 수용 불가 신고·확인된 만실·거절 병원은 대체 후보로 내밀지 않는다
        if h.travelMin is None or h.travelMin > TRANSPORT_ALT_MAX_MIN:
            continue
        out.append(TransportAlternative(
            hospitalId=h.hospitalId, name=h.name, status=h.status, travelMin=h.travelMin,
            availableBedCount=h.availableBedCount, bedCountUnknown=h.bedCountUnknown,
            rArrive=h.bedReliability.rArrive if h.bedReliability else None,
        ))
        if len(out) >= 3:
            break
    return out


def _handle_transport_vitals(msg: TransportVitals) -> dict:
    """측정 1회 수신 → 규칙 엔진 판정 → 역할별 전송. 판정 payload를 돌려준다(HTTP 응답용)."""
    obs = VitalObservation(
        measured_at=msg.observation.measuredAt, source=msg.observation.source,
        rr=msg.observation.rr, spo2=msg.observation.spo2, sbp=msg.observation.sbp,
        hr=msg.observation.hr, bt=msg.observation.bt, avpu=msg.observation.avpu,
    )
    with _triage_lock:
        triage = _transport_triage.setdefault(msg.caseId, TransportTriage())
        assessment = triage.evaluate(obs)

    result = engine.get_case_result(msg.caseId)
    confirmed_id = (
        next((h.hospitalId for h in result.hospitals if h.status == "confirmed"), None) if result else None
    )
    tier, alternatives, reasons = assessment.tier, [], list(assessment.reasons)
    if tier == "review":
        alternatives = _transport_alternatives(result, confirmed_id)
        if not alternatives:
            # 엔진은 "대체가 필요하다"까지만 말한다 — 시간 안에 갈 병원이 없으면 여기서 권고로 올린다.
            tier = "heli_advisory"
            reasons.append(
                f"{TRANSPORT_ALT_MAX_MIN:g}분 안에 갈 수 있는 대체 병원 없음 — 헬기 대기 권고(결정은 관제)"
            )

    payload = TransportAssessmentMessage(
        caseId=msg.caseId, tier=tier, news2=assessment.news2,
        news2Missing=assessment.news2_missing, si=assessment.si, reasons=reasons,
        observation=msg.observation, demo=msg.demo, scenario=msg.scenario,
        alternatives=alternatives,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    ).model_dump()

    apid = msg.apid or engine.get_case_apid(msg.caseId)
    notify_hospital = confirmed_id if tier in ("notify", "review", "heli_advisory") else None
    message = json.dumps(payload, ensure_ascii=False)
    with _sockets_lock:
        dead = set()
        for ws in _dashboard_sockets:
            role, id_ = _socket_identity.get(ws, (None, None))
            if (role == "ambulance" and id_ == apid) or (
                role == "hospital" and notify_hospital and id_ == notify_hospital
            ):
                try:
                    ws.send(message)
                except Exception as e:  # noqa: BLE001
                    print(f"  [통신] transport_assessment 전송 실패, 연결 제거: {e}")
                    dead.add(ws)
        _dashboard_sockets.difference_update(dead)
        if msg.demo:
            # 가상 시나리오 판정은 시연 통제 콘솔(role=monitor, /control)에도 그대로 에코한다(2026-10-04) —
            # 합성 데이터라 "관제는 환자 상세를 받지 않는다" 원칙과 충돌하지 않는다. 실데이터는 아래 경로만.
            _send_to_monitors_locked(payload)
        elif tier == "heli_advisory":
            # 실데이터의 관제 전달은 활력징후 상세 없이 권고 사실만 — 환자 상세는 병원 대시보드만 받는 원칙
            _send_to_monitors_locked({
                "type": "transport_assessment", "caseId": msg.caseId, "tier": tier,
                "reasons": reasons, "demo": msg.demo, "source": "rule",
                "timestamp": payload["timestamp"],
            })
    if tier in ("notify", "review", "heli_advisory"):
        decision_log.log_decision("transport_assessment", {
            "caseId": msg.caseId, "tier": tier, "news2": assessment.news2, "si": assessment.si,
            "reasons": reasons, "observation": msg.observation.model_dump(),
            "alternatives": [a.hospitalId for a in alternatives],
            "demo": msg.demo, "scenario": msg.scenario,
        })
        label = {"notify": "상태 변화 전달", "review": "대체 병원 제안", "heli_advisory": "헬기 대기 권고"}[tier]
        print(f"  [이송중] caseId={msg.caseId} NEWS2 {assessment.news2} — {label}")
    return payload


@app.post("/vitals")
def receive_vitals():
    """활력징후 입력 구멍(2.5단계)의 공식 HTTP 수신구 — 향후 119구급스마트시스템·
    구급차 모니터 어댑터가 여기로 보낸다. dashboard WS와 같은 처리로 모인다."""
    try:
        msg = TransportVitals.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": exc.errors()}), 400
    return jsonify(_handle_transport_vitals(msg)), 202


def _build_self_info(hospital_id: str) -> HospitalSelfInfo | None:
    """병원 대시보드용 "귀원 정보 현황"(2026-09-29). 신뢰도는 horizon 0으로
    환산한다 — 자기 화면엔 이송(도착 시점) 개념이 없으므로 rArrive==authority."""
    info = engine.get_hospital(hospital_id)
    if info is None:
        return None
    now = datetime.now(timezone.utc)
    confirmed = engine.get_info_confirmation(hospital_id)
    return HospitalSelfInfo(
        hospitalId=hospital_id,
        name=info.name,
        availableBedCount=engine.effective_bed_count(info),
        bedCountUnknown=_is_bed_count_unknown(info),
        updatedAt=info.updatedAt,
        bedReliability=bed_reliability.evaluate(
            info.bedReliability, 0.0, now=now, horizon_sec=0.0, confirmed_at=confirmed
        ),
        bedReliabilityByType=(
            {
                field: bed_reliability.evaluate(
                    payload, 0.0, now=now, horizon_sec=0.0, confirmed_at=confirmed
                )
                for field, payload in info.bedReliabilityByType.items()
            }
            if info.bedReliabilityByType
            else None
        ),
        severeDeclarations=info.severeDeclarations,
        # 본원 지정 등급·진료과·이송 중 부하(2026-10-04) — "지금 얼마나/어떤 분야를 받을 수
        # 있는 병원인가"를 자기 화면에서 바로 보게 한다
        emergencyLevel=info.emergencyLevel,
        specialties=info.specialties,
        inFlightCount=engine.in_flight_count(hospital_id),
    )


def _send_self_info_to_hospital(hospital_id: str) -> None:
    """그 병원(hpid)으로 identify한 모든 소켓에 자기 정보 현황을 보낸다.
    연결이 없으면 조용히 넘어간다."""
    with _sockets_lock:
        targets = [
            sock
            for sock, (role, hid) in _socket_identity.items()
            if role == "hospital" and hid == hospital_id and sock in _dashboard_sockets
        ]
    if not targets:
        return
    payload = _build_self_info(hospital_id)
    if payload is None:
        return
    data = payload.model_dump()
    for sock in targets:
        _send_to_socket(sock, data, "self_info")


def _refresh_cases_for_hospital(hospital_id: str) -> None:
    for result in engine.get_cases_for_hospital(hospital_id):
        try:
            ambulance_gps, _ = _resolve_ambulance_gps(result.caseId)
            updated = engine.refresh_case(result.caseId, ambulance_gps)
        except Exception as e:  # noqa: BLE001
            print(f"  [재계산] caseId={result.caseId} 실패: {e!r}")
            continue
        if updated is not None:
            _send_to_dashboard(updated.model_dump())


def _handle_identify(ws, identify: DashboardIdentify) -> None:
    """연결 직후 자기소개 처리: 신원 확인 → (관제 지도면 전체 목록) → 따라잡기 → 구급차 위치 → (병원이면 귀원 정보)."""
    with _sockets_lock:
        _socket_identity[ws] = (identify.role, identify.id)
    _send_identity_info(ws, identify)
    if identify.role == "monitor":
        _send_to_socket(ws, _build_map_overview(), "관제 지도 목록")
        # 매칭 전(통화 전) 사건도 신고 단계부터 보이게 — 예비 고지 요약 따라잡기(2026-10-04).
        # 이미 매칭된 사건은 바로 아래 _send_catchup의 case_overview가 담당한다.
        for case_id, summary in list(_pre_alerts.items()):
            if engine.get_case_result(case_id) is None:
                _send_to_socket(ws, summary, "예비 고지 따라잡기")
    active = _send_catchup(ws, identify)
    if identify.role == "ambulance":  # 결과 전(출동·통화 중) 사건의 현장 후보·실시간 자막도 지우지 않게
        active = sorted(set(active) | set(engine.get_case_ids_for_apid(identify.id)))
        sim_case = sim.case_of(identify.id) if sim is not None else None
        for case_id in set(active) | ({sim_case} if sim_case else set()):
            _send_scene_input_mode(case_id, identify.id, ws)
    if identify.role == "monitor":  # 매칭 전(예비 고지) 사건도 진행 중이다 — 목록에서 빠져 있어 다시 연결한 관제·spider가
        active = sorted(set(active) | set(_pre_alerts))  # 방금 받은 예비 고지 사건을 바로 지웠다(2026-10-15)
    # 탭은 hub가 꺼졌다 켜져도 자동 재연결하며 화면 상태를 그대로 들고 있다 — 그 사이 끝난 사건(재시작 정리·
    # 방치 정리 등)은 case_closed를 못 받았으니, 지금 진행 중인 목록을 알려 나머지를 지우게 한다(2026-10-03).
    _send_to_socket(ws, {"type": "case_sync", "caseIds": active}, "사건 목록 동기화")
    # 관제 판단 대기 따라잡기(2026-11-04) — 관제는 충돌 묶음 전체, 구급대는 자기 사건의 대기 상태
    if identify.role == "monitor":
        _send_to_socket(ws, _assignment_snapshot(), "배정 충돌")
    elif identify.role == "ambulance":
        with _assignment_lock:
            mine = {c: h for c, h in _assignment_pending.items() if c in set(active)}
        for case_id, hospital_id in mine.items():
            _send_to_socket(ws, _dispatcher_pending_message(case_id, hospital_id), "관제 판단 대기")
    if sim is not None and identify.role in ("ambulance", "monitor"):
        apids = [identify.id] if identify.role == "ambulance" else [a.apid for a in engine.list_ambulances()]
        for apid in apids:
            state = sim.state(apid)
            if state is not None:
                _send_to_socket(ws, _sim_message("ambulance_phase", state), "시뮬레이션 상태")
    # 병원 탭: 이 병원으로 이송 중·도착한 구급차의 현재 상태(2026-10-03). 병원 대시보드는 이제 관제 지도에서
    # 눌러 여는데, 구급차가 도착한 **뒤에** 열면 그 탭은 "도착(at_hospital)"을 받은 적이 없어 [환자 수용 완료]
    # 버튼이 꺼진 채였다 — 상태가 바뀔 때만 보내던 걸 연결 시점에도 한 번 준다.
    if sim is not None and identify.role == "hospital":
        for ambulance in engine.list_ambulances():
            state = sim.state(ambulance.apid)
            if state and state.get("hospitalId") == identify.id and state.get("phase") in ("transporting", "at_hospital"):
                _send_to_socket(ws, _sim_message("ambulance_phase", state), "시뮬레이션 상태")
    # 현장 후보 따라잡기(2026-10-03) — 현장 도착 뒤에 연 탭(휴대폰 통화 화면)도 전화할 병원 목록을 받게
    if identify.role == "ambulance":
        with _sockets_lock:
            scenes = [_case_scene[c] for c in engine.get_case_ids_for_apid(identify.id) if c in _case_scene]
        for scene in scenes:
            _send_to_socket(ws, scene, "현장 후보")
    # 진행 중인 통화 상태(📞)도 따라잡기 — 통화 중에 연 병원 탭·관제 지도·태블릿에도 뜨게(2026-10-03)
    with _sockets_lock:
        statuses = [st for st in _case_call.values() if ws in _call_status_targets_locked(st)]
    for status in statuses:
        _send_to_socket(ws, status, "통화 상태")
    # 병원이면 사건 유무와 무관하게 "귀원 정보 현황"도 바로 준다.
    if identify.role == "hospital":
        self_info = _build_self_info(identify.id)
        if self_info is not None:
            _send_to_socket(ws, self_info.model_dump(), "self_info")


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
    # 시연 영상 모드는 화면마다 신원과 무관하게 따른다 — 연결되자마자(나중에 연 화면·재연결 포함) 지금 모드를 알린다
    _send_to_socket(ws, {"type": "demo_mode", "mode": _demo_mode}, "영상 모드 따라잡기")
    try:
        while True:
            message = ws.receive()
            if message is None:  # 연결 종료
                break
            if isinstance(message, (bytes, bytearray)):
                # 통화 음성(16kHz PCM) — 중앙 voice로 통화 중인 소켓이면 그 사건으로 넘기고, 아니면 버린다(2026-10-03)
                _handle_audio_frame(ws, bytes(message))
                continue

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
                _relay_call_signal(signal, ws)
            elif payload.get("type") == "call_connection":
                _handle_call_connection(ws, payload)
            elif payload.get("type") == "first_call_request":
                _handle_first_call(ws, payload)
            elif payload.get("type") == "identify":
                try:
                    identify = DashboardIdentify.model_validate(payload)
                except ValidationError as exc:
                    print(f"  [통신] 잘못된 DashboardIdentify 수신: {exc.errors()}")
                    continue
                _handle_identify(ws, identify)
            elif payload.get("type") in ("live_case_get", "live_case_patch"):
                _handle_live_case_edit(ws, payload)
            elif payload.get("type") in ("record_sync", "record_import", "record_handover"):
                # token은 로그에 출력하지 않는다. identify만으로 과거 기록을 읽을 수 없다.
                identity = _socket_identity.get(ws, (None, None))
                if payload.get("type") == "record_sync" and identity[0] == "ambulance" and record_archive.authorized(identity[1], payload.get("token")):
                    for result in engine.get_cases_for_apid(identity[1]):
                        _archive_call("observe", dashboard_payload(result.model_dump()))
                try:
                    response = record_archive.handle(identity, payload)
                except Exception:
                    response = {"type": "record_error", "requestId": payload.get("requestId"), "error": "storage_unavailable"}
                _send_to_socket(ws, response, "기록 동기화")
                if response.get("type") in ("record_import_result", "record_handover_result") and not response.get("conflict"):
                    _notify_record_clients(identity[1])
                    record = response.get("record")
                    if record and engine.get_case_apid(record["caseId"]) == identity[1]:
                        live = record_archive.live_get(identity[1], record["caseId"])
                        with _sockets_lock:
                            targets = [s for s in _dashboard_sockets if _socket_identity.get(s) == identity]
                        for target in targets:
                            _send_to_socket(target, live, "기록 수정의 현재 화면 반영")
            elif payload.get("type") == "voice_summary":
                # 아이폰 앱의 온디바이스 통화 요약(2026-10-05) — /voice/summary(HTTP)와 같은 내용을 이 연결로 받는다.
                # 공개 도메인 터널은 /voice/*를 열지 않아서(인증 없는 주입 경로 차단) 기기에서 만든 요약이 404가 났다.
                # 구급차(role=ambulance) 소켓에서 온 것만, 그 구급차의 사건 요약만 받는다.
                role, sock_apid = _socket_identity.get(ws, (None, None))
                try:
                    voice = VoiceCallSummaryMessage.model_validate(payload)
                except ValidationError as exc:
                    print(f"  [통신] 잘못된 voice_summary 수신: {exc.errors()}")
                    continue
                if role != "ambulance" or engine.get_case_apid(voice.caseId) not in (None, sock_apid):
                    print(f"  [통신] voice_summary 거부 — 구급차 소켓이 아니거나 다른 구급차의 사건 (caseId={voice.caseId})")
                    continue
                _match_executor.submit(_run_match_job, voice)
            elif payload.get("type") == "patient_override":
                # 구급대원의 통화 요약 확인·수정(2026-10-13, Override). 그 사건을 연 구급차의 소켓에서 온 것만 받는다 —
                # 병원·관제·다른 구급차는 환자 정보를 고칠 수 없다. 일시정지 중엔 다른 조작처럼 거부한다.
                role, sock_apid = _socket_identity.get(ws, (None, None))
                try:
                    override = PatientOverride.model_validate(payload)
                except ValidationError as exc:
                    print(f"  [통신] 잘못된 patient_override 수신: {exc.errors()}")
                    continue
                case_apid = engine.get_case_apid(override.caseId)
                if role != "ambulance" or case_apid is None or case_apid != sock_apid:
                    print(f"  [통신] patient_override 거부 — 이 사건의 구급차 소켓이 아님 (caseId={override.caseId})")
                    _notify_refused(ws, override.caseId, "not_owner")
                    continue
                if _case_paused(override.caseId):
                    _notify_refused(ws, override.caseId, "paused")
                    continue
                _match_executor.submit(_run_override_job, override, ws)
            elif payload.get("type") == "info_confirm":
                try:
                    confirm = HospitalInfoConfirm.model_validate(payload)
                except ValidationError as exc:
                    print(f"  [통신] 잘못된 HospitalInfoConfirm 수신: {exc.errors()}")
                    continue
                _handle_info_confirm(confirm)
            elif payload.get("type") == "transport_vitals":
                try:
                    vitals = TransportVitals.model_validate(payload)
                except ValidationError as exc:
                    print(f"  [통신] 잘못된 TransportVitals 수신: {exc.errors()}")
                    continue
                if _case_paused(vitals.caseId):
                    _notify_refused(ws, vitals.caseId, "paused")
                    continue
                _handle_transport_vitals(vitals)
            elif payload.get("type") in ("dispatch", "scene_end", "sim_pause", "sim_resume", "sim_reset", "sim_fast_forward"):
                # 일시정지 중엔 재개·초기화만 받는다(2026-10-05). 빨리감기·현장 종료도 조작이라 막는다.
                if payload.get("type") in ("scene_end", "sim_fast_forward") and _apid_paused(payload.get("apid")):
                    _notify_refused(ws, payload.get("caseId"), "paused")
                    continue
                _handle_sim_command(payload)
            elif payload.get("type") == "mci_preview":
                try:
                    preview = MciPreview.model_validate(payload)
                except ValidationError as exc:
                    print(f"  [통신] 잘못된 MciPreview 수신: {exc.errors()}")
                    continue
                _send_to_socket(ws, {"type": "mci_plan", "caseIds": preview.caseIds,
                                     "plan": engine.plan_mci(preview.caseIds)}, "대량사고 분배 미리 보기")
            elif payload.get("type") == "mci_allocate":
                try:
                    allocate = MciAllocate.model_validate(payload)
                except ValidationError as exc:
                    print(f"  [통신] 잘못된 MciAllocate 수신: {exc.errors()}")
                    continue
                _match_executor.submit(_mci_allocate, allocate.caseIds, ws)
            elif payload.get("type") == "scene_input_mode":
                _handle_scene_input_mode(payload)
            elif payload.get("type") == "demo_mode":
                _set_demo_mode(payload.get("mode", ""))
            elif payload.get("type") == "confirm_request":
                _handle_confirm_request(ws, payload)
            elif payload.get("type") == "demo_scenario":
                _match_executor.submit(_run_demo_scenario, str(payload.get("kind") or ""), ws)
            elif payload.get("type") == "mci_register":
                _handle_mci_register(ws, payload)
            elif payload.get("type") == "mci_dispatch":
                _handle_mci_dispatch(ws, payload)
            elif payload.get("type") == "zone_expand_now":
                try:
                    expand = ZoneExpandNow.model_validate(payload)
                except ValidationError as exc:
                    print(f"  [통신] 잘못된 ZoneExpandNow 수신: {exc.errors()}")
                    continue
                if _case_paused(expand.caseId):
                    _notify_refused(ws, expand.caseId, "paused")
                    _notify_result(ws, expand.caseId, "zone_expand_now", False, "paused")
                    continue
                _match_executor.submit(_expand_and_report, expand.caseId, ws)
            elif "action" in payload:
                _handle_dashboard_action(payload, ws)
    finally:
        with _sockets_lock:
            _dashboard_sockets.discard(ws)
            _socket_identity.pop(ws, None)
            # 통화 중 끊긴 소켓 — 전송기는 그대로 두고(종료 신호나 voice의 무음 자동 종료로 끝난다) 묶음만 푼다
            _socket_call.pop(ws, None)
        with _call_connection_lock:
            for cid, origin in list(_call_request_sockets.items()):
                if origin is ws:
                    _call_request_sockets.pop(cid, None)
                    status = _case_call.get(cid, {})
                    if status.get("state") == "ringing":
                        _send_call_status({**status, "state":"cancelled", "cancelled":True})


# ── 출동 시뮬레이션 (2026-10-01, HUB_SIM_DISPATCH=1) ─────────────────────────


def _sim_message(kind: str, state: dict) -> dict:
    """ambulance_phase(상태 바뀔 때, 경로 포함) / ambulance_position(움직이는 동안 1초마다, 경로 없음)."""
    body = dict(state) if kind == "ambulance_phase" else {k: v for k, v in state.items() if k != "path"}
    return {"type": kind, **body, "simulated": True}


def _send_sim(kind: str, state: dict) -> None:
    """그 구급차 탭 전부 + 이송 중·병원 도착이면 그 확정 병원 탭 + 관제 지도 탭 전부(2026-10-03)에 보낸다."""
    if kind == "ambulance_phase":
        ambulance = engine.get_ambulance(state["apid"])
        _archive_call("phase", state, ambulance.name if ambulance else None)
    message = json.dumps(_sim_message(kind, state), ensure_ascii=False)
    hospital_id = state.get("hospitalId") if state.get("phase") in ("transporting", "at_hospital") else None
    with _sockets_lock:
        for ws, (role, id_) in list(_socket_identity.items()):
            if role == "monitor" or (role == "ambulance" and id_ == state["apid"]) or \
                    (hospital_id and role == "hospital" and id_ == hospital_id):
                try:
                    ws.send(message)
                except Exception as e:  # noqa: BLE001
                    print(f"  [통신] 시뮬레이션 위치 전송 실패: {e}")


def _broadcast_sim_state(apid: str) -> None:
    state = sim.state(apid) if sim is not None else None
    if state is None:
        return
    if state.get("gps"):
        engine.set_gps_override(apid, GpsPoint(**state["gps"]))
    _send_sim("ambulance_phase", state)


def _handle_sim_command(payload: dict) -> None:
    """[이동](dispatch) · [현장 종료](scene_end) · [정지](sim_pause) · [상황 재개](sim_resume, 2026-10-03)."""
    if sim is None:
        print("  [시뮬레이션] 꺼져 있어 출동·현장 종료 명령을 무시 (HUB_SIM_DISPATCH=1로 켬)")
        return
    try:
        model = {"dispatch": DispatchRequest, "sim_pause": SimControl, "sim_resume": SimControl,
                 "sim_fast_forward": SimControl, "sim_reset": SimReset}.get(payload.get("type"), SceneEnd)
        cmd = model.model_validate(payload)
    except ValidationError as exc:
        print(f"  [통신] 잘못된 시뮬레이션 명령: {exc.errors()}")
        return
    if isinstance(cmd, SimReset):
        # [시연 초기화](2026-10-04) — 모든 사건 종료(case_closed 전파) + 전 구급차 기지 복귀 +
        # 이송 중 병상 차감 해제. "시연 정지(일시정지)가 사건을 안 지운다"는 혼동을 분리한 리셋.
        with _call_holds_lock:
            _call_holds.clear()
        closed: list[str] = []
        for info in engine.list_ambulances():
            sim.reset(info.apid)
            _broadcast_sim_state(info.apid)
        # 진행 중인 사건은 **전부** 닫는다(2026-10-04) — 예전엔 구급차가 지금 맡은 사건만 닫았고, 그것도 이송 확정
        # 사건은 엔진이 60분 보관 규칙으로 거절해서 대량사고를 연달아 돌린 뒤 초기화하면 이송 중·병원 도착 사건이
        # 남았다. 구급차는 기지로 돌아가 주인 없는 사건이 되어 구급차 대시보드에도 이어지지 않았다.
        for case_id in engine.list_open_case_ids():
            if _close_case(case_id, "sim_reset", include_confirmed=True):
                closed.append(case_id)
        # 엔진엔 없는 사건까지(출동만 했거나 매칭 전) — 남은 통화 상태·예비 고지·현장 후보도 지우고 화면에 알린다
        with _sockets_lock:
            leftover = set(_case_call) | set(_case_scene) | set(_case_audience) | set(_case_recommended)
        leftover |= set(case_tracker.open_case_ids()) | set(_pre_alerts)
        for case_id in leftover - set(closed):
            _forget_case(case_id, "sim_reset")
        engine.clear_bed_overlay()
        decision_log.log_decision("sim_reset", {"closedCases": closed, "simulated": True})
        _send_map_overview()
        print(f"  [시뮬레이션] 시연 초기화 — 사건 {len(closed)}건 종료, 전 구급차 기지 복귀")
        return
    if isinstance(cmd, SimControl) and cmd.type == "sim_fast_forward":
        # [빨리감기](2026-10-04) — 이송 중 남은 이동을 3초 안에 마친다
        ok, reason = sim.fast_forward(cmd.apid)
        decision_log.log_decision("sim_fast_forward" if ok else "sim_control_refused",
                                  {"apid": cmd.apid, "caseId": cmd.caseId, "command": cmd.type, "reason": reason, "simulated": True})
        print(f"  [시뮬레이션] {cmd.apid} 빨리감기" + ("" if ok else f" 거부 ({reason})"))
        if ok:
            _pause_zone_timers(cmd.apid, False)  # 빨리감기는 정지도 푼다
            _broadcast_sim_state(cmd.apid)
        return
    if isinstance(cmd, SimControl):
        pausing = cmd.type == "sim_pause"
        ok, reason = sim.pause(cmd.apid) if pausing else sim.resume(cmd.apid)
        event = ("sim_paused" if pausing else "sim_resumed") if ok else "sim_control_refused"
        decision_log.log_decision(event, {"apid": cmd.apid, "caseId": cmd.caseId, "command": cmd.type,
                                          "reason": reason, "simulated": True})
        print(f"  [시뮬레이션] {cmd.apid} {'정지' if pausing else '상황 재개'}" + ("" if ok else f" 거부 ({reason})"))
        if ok:
            _pause_zone_timers(cmd.apid, pausing)
    elif isinstance(cmd, DispatchRequest):
        base = engine.get_ambulance_base(cmd.apid)
        if base is not None:
            sim.ensure_unit(cmd.apid, base.gps)
        ok, reason = sim.dispatch(cmd.apid, cmd.caseId, cmd.target)
        # 지정 위치는 집 주소일 수 있어 로그엔 약 1km 단위로 뭉갠 좌표만 남긴다(주소 글자는 애초에 안 받음).
        coarse = {"lat": round(cmd.target.lat, 2), "lng": round(cmd.target.lng, 2)} if cmd.target else None
        decision_log.log_decision("ambulance_dispatched" if ok else "dispatch_refused",
                                  {"apid": cmd.apid, "caseId": cmd.caseId, "reason": reason, "simulated": True,
                                   "targetMode": cmd.targetMode or "random", "targetCoarse": coarse})
        if ok:
            engine.register_case(cmd.caseId, cmd.apid)
            ambulance = engine.get_ambulance(cmd.apid)
            reported = f" · 신고: {cmd.reportedSymptom}" if cmd.reportedSymptom else ""
            case_tracker.start(cmd.caseId, cmd.apid, ambulance.name if ambulance else None,
                               cmd.reportedSeverity, cmd.reportedSymptom, event_text=f"출동{reported}")
            print(f"  [시뮬레이션] {cmd.apid} 출동 — caseId={cmd.caseId}")
            _send_pre_alert(cmd.apid, cmd.caseId, cmd.reportedSymptom, cmd.reportedSeverity)
            # 1차 신고 기반 가추천(2026-10-04) — 출동 즉시, 현장 좌표 기준으로 후보를 띄운다.
            # 현장 통화(2차 정보)가 끝나면 확정 매칭이 대체한다.
            state = sim.state(cmd.apid) or {}
            scene = state.get("incident")
            if scene:
                _send_scene_candidates(cmd.caseId, cmd.apid, scene_gps=GpsPoint(**scene))
        else:
            print(f"  [시뮬레이션] {cmd.apid} 출동 거부 ({reason})")
    else:
        ok = sim.scene_end(cmd.apid, cmd.caseId)
        if ok:
            _log_no_responses(cmd.caseId, cmd.timestamp, finalized_to=None)
            _close_case(cmd.caseId, "scene_ended")
            print(f"  [시뮬레이션] {cmd.apid} 현장 종료 → 기지 복귀")
        else:
            print(f"  [시뮬레이션] {cmd.apid} 현장 종료 거부 — 현장에 있지 않거나 다른 사건")
    _broadcast_sim_state(cmd.apid)


#: 관제 지도용 사건 기록(2026-10-04) — 사건 번호·시작 시각·증상·병원별 응답 시각·진행 과정·오늘 종료 사건.
#: 매칭 결과가 나갈 때마다(_send_to_dashboard) 직전과 비교해 이벤트를 만든다(case_history.py).
case_tracker = CaseTracker(archive_path=Path(os.environ.get("HUB_CASE_ARCHIVE_PATH")
                                              or Path(__file__).resolve().parent / "data" / "logs" / "case_archive.jsonl"))


# ── 시간 기반 존 확장(2026-10-04) ─────────────────────────────────────────────
# 거절 비율(40%) 확장은 병원이 "거절"을 눌러야만 움직인다 — 아무도 답하지 않으면 존이 그대로 멈춘다. 그래서 요청이
# 나간 뒤(또는 마지막 확장 뒤) ZONE_EXPAND_SEC 동안 승인·확정 병원이 없으면 존을 한 단계 넓힌다. 시연 콘솔의
# [건너뛰기]는 기다리지 않고 바로 넓힌다. 넓힐 수 없으면(상한) 타이머를 멈춘다. 규칙 기반.
ZONE_EXPAND_SEC = float(os.environ.get("HUB_ZONE_EXPAND_SEC", "60"))
ZONE_TIMER_TICK_SEC = 1.0
#: caseId -> {"zone": 지금 존, "since": 그 존이 시작된 시각(epoch), "ok": 더 넓힐 수 있는지,
#:            "paused": [정지]를 누른 시각(epoch, 2026-10-04) — 정지 중엔 시간이 흐르지 않는다}
_zone_timer: dict[str, dict] = {}
_zone_timer_lock = threading.Lock()


def _zone_waiting(payload: dict) -> bool:
    """아직 갈 곳을 찾는 중인가 — 승인·확정 병원이 없을 때만 시간 확장이 돈다."""
    return not any(h.get("status") in ("approved", "confirmed") for h in payload.get("hospitals") or [])


def _case_paused(case_id: str | None) -> bool:
    apid = engine.get_case_apid(case_id) if case_id else None
    return _apid_paused(apid)


def _apid_paused(apid: str | None) -> bool:
    """운영자의 시연 일시정지인가 — 조작을 잠근다. 이송 중 추가 통화로 이동만 멈춘 경우(pauseReason "call")는 잠그지 않는다."""
    state = (sim.state(apid) or {}) if sim is not None and apid else {}
    return bool(state.get("paused")) and state.get("pauseReason") != "call"


# ── 이송 중 추가 통화 동안 이동 멈춤(2026-10-05) ─────────────────────────────
# 이송 중 목적지 병원과 다시 통화하면, 통화 내용을 듣고 정보를 처리하는 동안 구급차 이동(시뮬레이션)을 잠시 멈춘다.
# 통화 취소면 바로, 전송이면 2차 요약이 반영된 뒤 다시 출발한다. 요약이 안 오면(음성 없음·실패) 안전 시간 뒤 푼다.
CALL_HOLD_MAX_SEC = float(os.environ.get("HUB_CALL_HOLD_MAX_SEC", "600"))        # 통화가 이보다 길면 그냥 푼다
CALL_HOLD_AFTER_END_SEC = float(os.environ.get("HUB_CALL_HOLD_AFTER_END_SEC", "120"))  # 전송 뒤 요약을 기다리는 최대 시간
#: caseId -> {"apid", "deadline"(epoch)}
_call_holds: dict[str, dict] = {}
_call_holds_lock = threading.Lock()


def _start_call_hold(case_id: str, apid: str) -> None:
    if sim is None or sim.phase_of(apid) != "transporting":
        return
    ok, _ = sim.pause(apid, reason="call")
    if not ok:
        return  # 이미 멈춰 있다(운영자 일시정지 등)
    with _call_holds_lock:
        _call_holds[case_id] = {"apid": apid, "deadline": time.time() + CALL_HOLD_MAX_SEC}
    case_tracker.event(case_id, "p", "추가 통화 — 통화·정보 처리 동안 이송 잠시 멈춤")
    decision_log.log_decision("transport_call_hold", {"caseId": case_id, "apid": apid, "simulated": True})
    _pause_zone_timers(apid, True)
    _broadcast_sim_state(apid)


def _release_call_hold(case_id: str, cause: str) -> None:
    with _call_holds_lock:
        hold = _call_holds.pop(case_id, None)
    if hold is None or sim is None:
        return
    ok, _ = sim.resume(hold["apid"], reason="call")
    decision_log.log_decision("transport_call_released", {"caseId": case_id, "apid": hold["apid"], "cause": cause,
                                                          "resumed": ok, "simulated": True})
    if ok:
        label = {"cancelled": "통화 취소", "summary_applied": "통화 내용 반영", "timeout": "정보 처리 시간 초과"}.get(cause, cause)
        case_tracker.event(case_id, "p", f"{label} — 이송 재개")
        _pause_zone_timers(hold["apid"], False)
        _broadcast_sim_state(hold["apid"])


def _expire_call_holds(now: float | None = None) -> None:
    now = time.time() if now is None else now
    with _call_holds_lock:
        expired = [cid for cid, hold in _call_holds.items() if hold["deadline"] <= now]
    for case_id in expired:
        _release_call_hold(case_id, "timeout")


def _touch_zone_timer(payload: dict) -> None:
    """매칭 결과가 나갈 때마다: 처음 보는 사건이거나 존이 바뀌었으면 타이머를 지금부터 다시 잰다
    (구급차가 [정지] 중이면 멈춘 채로 시작)."""
    case_id = payload["caseId"]
    zone = max(payload.get("zoneActive") or [1])
    now = time.time()
    paused = now if _case_paused(case_id) else None
    with _zone_timer_lock:
        current = _zone_timer.get(case_id)
        if current is None or current["zone"] != zone:
            _zone_timer[case_id] = {"zone": zone, "since": now, "ok": True, "paused": paused}


def _zone_left_sec(timer: dict, now: float) -> float:
    """남은 시간(초). 정지 중이면 정지한 순간의 남은 시간 그대로."""
    at = timer["paused"] if timer["paused"] is not None else now
    return ZONE_EXPAND_SEC - (at - timer["since"])


def _zone_expand_at(payload: dict) -> str | None:
    """다음 자동 확장 시각. 정지 중이면 None(화면은 _zone_paused_left로 남은 시간을 멈춘 채 보여준다)."""
    if ZONE_EXPAND_SEC <= 0 or not _zone_waiting(payload):
        return None
    with _zone_timer_lock:
        timer = dict(_zone_timer.get(payload["caseId"]) or {})
    if not timer or not timer["ok"] or timer["paused"] is not None:
        return None
    return datetime.fromtimestamp(timer["since"] + ZONE_EXPAND_SEC, timezone.utc).isoformat(timespec="seconds")


def _zone_paused_left(payload: dict) -> int | None:
    """[정지] 중이면 멈춰 있는 남은 시간(초), 아니면 None."""
    if ZONE_EXPAND_SEC <= 0 or not _zone_waiting(payload):
        return None
    with _zone_timer_lock:
        timer = dict(_zone_timer.get(payload["caseId"]) or {})
    if not timer or not timer["ok"] or timer["paused"] is None:
        return None
    return max(0, int(round(_zone_left_sec(timer, time.time()))))


def _pause_zone_timers(apid: str, pausing: bool) -> None:
    """[정지]·[상황 재개](2026-10-04): 그 구급차 사건의 존 확장 시간도 멈추고, 재개하면 남은 시간부터 다시 센다.
    관제 지도·콘솔의 카운트다운이 바로 바뀌도록 사건 요약을 다시 보낸다."""
    now = time.time()
    changed = []
    for case_id in engine.get_case_ids_for_apid(apid):
        with _zone_timer_lock:
            timer = _zone_timer.get(case_id)
            if timer is None:
                continue
            if pausing and timer["paused"] is None:
                timer["paused"] = now
            elif not pausing and timer["paused"] is not None:
                timer["since"] += now - timer["paused"]
                timer["paused"] = None
            else:
                continue
        changed.append(case_id)
    for case_id in changed:
        result = engine.get_case_result(case_id)
        if result is not None:
            with _sockets_lock:
                _send_to_monitors_locked(_monitor_case(result.model_dump()))
    # 병원·구급차 탭도 일시정지 여부를 알아야 버튼을 막는다(2026-10-05) — 타이머가 없는 사건(이송 중 등)까지 전부
    for case_id in engine.get_case_ids_for_apid(apid):
        result = engine.get_case_result(case_id)
        if result is not None:
            _send_to_dashboard(result.model_dump())


def _expand_case_zone(case_id: str, cause: str) -> str:
    """존을 한 단계 넓혀 같은 환자 정보로 다시 요청한다. cause: "timeout"(ZONE_EXPAND_SEC, 기본 60초) | "manual"(건너뛰기)."""
    result = engine.get_case_result(case_id)
    if result is None or not _zone_waiting(result.model_dump()):
        return "not_waiting"
    label = f"{int(ZONE_EXPAND_SEC)}초 동안 수용 병원 없음" if cause == "timeout" else "관제 건너뛰기"
    case_tracker.note_expand_cause(case_id, label)
    gps, _ = _resolve_ambulance_gps(case_id)
    current = max(result.zoneActive or [1])
    target = engine.next_zone_with_new(gps, current, case_id=case_id)
    expanded = engine.force_expand_zone(case_id, gps, cause=f"zone_{cause}", to_zone=target) if target else None
    if expanded is None:
        # 더 넓힐 수 없다(상한) — 타이머를 멈추고 화면의 카운트다운도 지운다
        with _zone_timer_lock:
            timer = _zone_timer.setdefault(case_id, {"zone": current, "since": time.time(), "ok": True, "paused": None})
            timer["ok"] = False
        case_tracker.note_expand_cause(case_id, "")
        _send_to_dashboard(result.model_dump())
        print(f"  [존 확장] case={case_id} 더 넓힐 수 없음 — 시간 확장 멈춤")
        return "max_zone"
    _send_to_dashboard(expanded.model_dump())
    return "expanded"


def _expand_and_report(case_id: str, ws) -> None:
    """관제의 [존 확장 즉시 실행] — 넓혔는지, 못 넓혔다면 왜인지를 누른 소켓에 알린다."""
    outcome = _expand_case_zone(case_id, "manual")
    _notify_result(ws, case_id, "zone_expand_now", outcome == "expanded", outcome)


def _zone_timer_loop() -> None:
    while True:
        time.sleep(ZONE_TIMER_TICK_SEC)
        try:
            _zone_timer_tick()
        except Exception as e:  # noqa: BLE001
            print(f"  [존 확장 타이머] 오류(계속 진행): {e!r}")


def _zone_timer_tick(now: float | None = None) -> None:
    """시간이 된 사건의 존을 넓힌다(작업 스레드로). 테스트가 now를 넘겨 한 번만 돌린다. 정지 중인 사건은 건너뛴다."""
    now = time.time() if now is None else now
    with _zone_timer_lock:
        due = [cid for cid, t in _zone_timer.items()
               if t["ok"] and t["paused"] is None and _zone_left_sec(t, now) <= 0]
        # 닫힌 사건은 지운다
        for cid in [c for c in _zone_timer if engine.get_case_result(c) is None]:
            _zone_timer.pop(cid, None)
    for case_id in due:
        result = engine.get_case_result(case_id)
        if result is None:
            continue
        with _zone_timer_lock:
            timer = _zone_timer.get(case_id)
            if timer is None:
                continue
            # 승인 병원이 생겼으면 쉬었다가, 다시 대기로 돌아오면 그때부터 잰다. 확장할 때도 중복 실행을 막으려
            # 지금으로 당겨 둔다(결과가 오면 _touch_zone_timer가 새 존 기준으로 다시 잰다).
            timer["since"] = now
        if _zone_waiting(result.model_dump()):
            _match_executor.submit(_expand_case_zone, case_id, "timeout")


def _send_case_meta(case_id: str, ws=None) -> None:
    """매칭 전 사건의 번호·시작 시각·증상을 관제 지도에 보낸다(ws가 있으면 그 소켓에만 — 따라잡기)."""
    meta = case_tracker.meta(case_id)
    if meta is None:
        return
    payload = CaseMeta(**meta, events=case_tracker.events(case_id)).model_dump()
    if ws is not None:
        _send_to_socket(ws, payload, "사건 정보")
        return
    with _sockets_lock:
        _send_to_monitors_locked(payload)


def _record_case_closed(case_id: str, reason: str) -> None:
    """사건이 끝나면 지난 사건 목록에 남기고 관제 지도에 새 목록을 보낸다."""
    _archive_call("close", case_id)
    if case_tracker.close(case_id, reason) is None:
        return
    payload = CaseHistory(cases=case_tracker.history()).model_dump()
    with _sockets_lock:
        _send_to_monitors_locked(payload)


#: 매칭 전(통화 전) 사건의 예비 고지 요약(caseId -> payload). 관제가 신고 접수 단계부터
#: 전 과정을 팔로잉할 수 있게, 늦게 연 관제 탭의 따라잡기 재료로 쓴다(2026-10-04).
#: 사건이 닫힐 때 지운다 — 매칭된 뒤에는 case_overview가 역할을 이어받는다.
_pre_alerts: dict[str, dict] = {}


def _send_pre_alert(
    apid: str, case_id: str, reported_symptom: str | None = None, reported_severity: str | None = None
) -> None:
    """출동 직후, 현장 존 안 후보 병원에 예비 고지(2026-10-04) — v2 계획 '예비 고지'의 경량판.

    신고 접수 때 파악한 1차 증상(reportedSymptom)이 있으면 같이 보낸다 — 상황실은 신고
    전화에서 이미 증상 개요를 아는 게 실무라서다. 단 '신고 내용'일 뿐 확정 정보가 아니고
    (현장 평가 = 통화 요약과 다를 수 있음), **경증(low) 신고는 예비 고지를 생략한다** —
    v2 계획의 "중증 의심이거나 특정 진료과가 필요한 경우에만 예비 고지" 그대로.
    존은 scene_candidates와 같은 발상으로 첫 비어있지 않은 밴드까지 넓힌다.
    병원에는 자기까지의 거리만 주고 현장 좌표는 주지 않는다(지정 위치는 집 주소일 수 있음 —
    로그를 1km 단위로 뭉개는 기존 원칙과 같은 방향). 관제(콘솔)에는 발송 병원 수만 요약해 준다.
    출동 시뮬레이션 모드 전용 — 실운영에선 119 신고 접수 이벤트에 물릴 자리다."""
    state = sim.state(apid) if sim is not None else None
    scene = (state or {}).get("incident")
    if not scene:
        return
    ambulance = engine.get_ambulance(apid)
    ambulance_name = ambulance.name if ambulance else None
    # 경증(low) 신고는 병원 예비 고지를 생략한다(v2 계획) — 관제는 전 과정을 팔로잉해야
    # 하므로 요약은 중증도와 무관하게 항상 보낸다(hospitalCount=0으로 "고지 안 함" 표시).
    skip_hospitals = reported_severity == "low"
    targets: list[tuple[str, float]] = []
    if not skip_hospitals:
        for band in (1, 2, 3):
            targets = [
                (h.hospitalId, distance)
                for h in engine.list_hospitals()
                if (distance := haversine_km(scene["lat"], scene["lng"], h.gps.lat, h.gps.lng)) <= ZONE_BAND_KM * band
            ]
            if targets:
                break
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    by_hospital = {hid: round(distance, 2) for hid, distance in targets}
    reported = {"reportedSymptom": reported_symptom, "reportedSeverity": reported_severity}
    summary = {
        "type": "pre_alert", "caseId": case_id, "apid": apid, "ambulanceName": ambulance_name,
        "hospitalCount": len(targets), **reported, "source": "rule", "timestamp": timestamp,
    }
    # 매칭 전 사건의 관제 따라잡기 재료(2026-10-04) — 늦게 연 관제 탭도 신고 단계부터 보이게.
    _pre_alerts[case_id] = summary
    _send_case_meta(case_id)
    summary_json = json.dumps(summary, ensure_ascii=False)
    with _sockets_lock:
        for ws, (role, id_) in list(_socket_identity.items()):
            try:
                if role == "hospital" and id_ in by_hospital:
                    ws.send(json.dumps({
                        "type": "pre_alert", "caseId": case_id, "apid": apid,
                        "ambulanceName": ambulance_name, "distanceKm": by_hospital[id_],
                        **reported, "source": "rule", "timestamp": timestamp,
                    }, ensure_ascii=False))
                elif role == "monitor":
                    ws.send(summary_json)
            except Exception as e:  # noqa: BLE001
                print(f"  [통신] 예비 고지 전송 실패: {e}")
    if skip_hospitals:
        print("  [시뮬레이션] 경증 신고 — 병원 예비 고지 생략(관제 요약만)")
        decision_log.log_decision("pre_alert", {
            "caseId": case_id, "apid": apid, "hospitals": 0,
            "reportedSymptom": reported_symptom, "reportedSeverity": reported_severity,
            "simulated": True,
        })
        return
    if not targets:
        return
    decision_log.log_decision("pre_alert", {
        "caseId": case_id, "apid": apid, "hospitals": len(targets),
        "sceneCoarse": {"lat": round(scene["lat"], 2), "lng": round(scene["lng"], 2)},
        "reportedSymptom": reported_symptom, "reportedSeverity": reported_severity,
        "simulated": True,
    })
    print(f"  [시뮬레이션] 예비 고지 — 현장 인근 병원 {len(targets)}곳")


def _sim_tick() -> None:
    """구급차를 한 칸 옮기고, 위치를 엔진(매칭·경로가 읽는 값)과 대시보드에 반영한다."""
    _expire_call_holds()
    changed, moving = sim.tick()
    for state in changed + moving:
        if state.get("gps"):
            engine.set_gps_override(state["apid"], GpsPoint(**state["gps"]))
    for state in moving:
        _send_sim("ambulance_position", state)
    for state in changed:
        _send_sim("ambulance_phase", state)
        if state["phase"] == "on_scene" and state.get("caseId"):
            _send_scene_candidates(state["caseId"], state["apid"])
        decision_log.log_decision("ambulance_phase", {k: state[k] for k in ("apid", "caseId", "phase")})


def _sim_loop() -> None:
    while True:
        time.sleep(SIM_TICK_SEC)
        try:
            _sim_tick()
        except Exception as e:  # noqa: BLE001
            print(f"  [시뮬레이션] 오류(계속 진행): {e!r}")


# ── 백그라운드: 주기적 재계산 · 상태 저장 (2026-09-28) ───────────────────────

_voice_addresses_dirty = False
_refresh_future: Future | None = None


def _mark_voice_addresses_dirty() -> None:
    global _voice_addresses_dirty
    _voice_addresses_dirty = True


def _refresh_active_cases() -> None:
    """진행 중인 사건을 다시 계산하고, 달라진 사건만 대시보드에 다시 보낸다(작업 스레드에서 돈다).
    spider 매칭 규칙(2026-10-15): 우선하는 사건(KTAS 낮은 숫자, 같으면 먼저 닿는)부터 — 앞 사건의 줄이 정해진 뒤 계산해야
    양보가 한 번에 맞는다."""
    for case_id in engine.spider_priority_order(engine.get_active_case_ids()):
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
    state["caseHistory"] = case_tracker.export_state()
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
    case_tracker.import_state(state.get("caseHistory") or {})
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
            # 확정 없이 방치된 사건: 무응답 기록 뒤 사건을 닫는다(case_closed).
            _sweep_unresolved_cases()
            # 확정된 지 CASE_RETENTION_MIN 지난 사건을 지우고, 열린 탭에서도 카드를 지우게 한다.
            for case_id in engine.prune_expired_cases():
                with _sockets_lock:
                    _case_audience.pop(case_id, None)
                    _case_call.pop(case_id, None)
                    _case_recommended.pop(case_id, None)
                    _case_scene.pop(case_id, None)
                _record_case_closed(case_id, "retention_expired")
                _send_to_dashboard({"type": "case_closed", "caseId": case_id, "reason": "retention_expired"})
            if PERSIST_STATE and (engine.take_dirty() or _voice_addresses_dirty):
                save_state()
        except Exception as e:  # noqa: BLE001
            print(f"  [백그라운드] 오류(계속 진행): {e!r}")


def _settle_restored_cases() -> None:
    """재시작 때 복구된 사건을 정리한다(2026-10-01).

    - 출동 시뮬레이션 중이면: 재시작하면 구급차가 전부 기지 대기로 돌아가서 어떤 사건도 이어갈 구급차가 없다 →
      바로 닫는다. 2026-10-03부터는 이송 확정된 사건도 닫는다 — 예전엔 확정 사건을 60분 남겨서, 서버를 껐다 켜면
      구급차는 기지에 있는데 대시보드엔 지난 사건(이송 확정)이 계속 떴다. 병상 차감은 병원 단위로 남는다.
      병원이 무시한 게 아니라 hub가 재시작한 것이라 무응답(NO_RESPONSE)은 남기지 않는다.
    - 아니면: 120분 방치 정리(sweep)의 기준인 마지막 활동 시각이 메모리에만 있어 재시작 뒤엔 영영 정리되지
      않았다 → 지금을 마지막 활동으로 잡아 둔다.
    """
    if sim is not None:
        case_ids = engine.list_case_ids()
        for case_id in case_ids:
            if engine.close_case(case_id, include_confirmed=True):
                decision_log.log_decision("case_closed", {"caseId": case_id, "reason": "hub_restart_sim_reset"})
        # 관제 지도 사건 기록도 닫는다 — 매칭 전(출동만 한) 사건까지(2026-10-04)
        for case_id in case_tracker.open_case_ids():
            case_tracker.close(case_id, "hub_restart_sim_reset")
        if case_ids:
            print(f"  [상태 복구] 출동 시뮬레이션 — 지난 사건 {len(case_ids)}건은 구급차가 기지로 돌아가 닫음")
        return
    case_ids = engine.get_unconfirmed_case_ids()
    if not case_ids:
        return
    now = datetime.now(timezone.utc)
    with _sockets_lock:
        for case_id in case_ids:
            _case_last_activity.setdefault(case_id, now)


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
    _settle_restored_cases()
    threading.Thread(target=_maintenance_loop, name="hub-maintenance", daemon=True).start()
    if ZONE_EXPAND_SEC > 0:
        threading.Thread(target=_zone_timer_loop, name="hub-zone-timer", daemon=True).start()
    if sim is not None:
        # 재시작하면 구급차는 전부 기지(대기)에서 다시 시작한다 — 시뮬레이션 상태는 저장하지 않는다.
        for ambulance in engine.list_ambulances():
            sim.ensure_unit(ambulance.apid, ambulance.gps)
        decision_log.log_decision("sim_dispatch_enabled", {"tripSec": SIM_TRIP_SEC, "transportSec": SIM_TRANSPORT_SEC})
        print("  [시뮬레이션] 출동 시뮬레이션 켜짐 (구급차 위치는 시연용 가짜 위치)")
        threading.Thread(target=_sim_loop, name="hub-sim", daemon=True).start()


if __name__ == "__main__":
    # debug=True면 코드 리로더가 켜져 파일이 바뀔 때마다 재시작되고(인메모리 상태 유실),
    # 예외 화면이 외부에 노출된다(2026-09-28 기본값 변경). 개발 중에만 HUB_DEBUG=1로 켠다.
    debug = os.environ.get("HUB_DEBUG") == "1"
    # 리로더가 켜지면 이 블록이 감시용 부모 프로세스에서도 한 번 더 돈다 — 실제 서버(자식)
    # 에서만 백그라운드를 시작해야 상태 파일을 두 프로세스가 같이 쓰지 않는다.
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_background()
    app.run(host="0.0.0.0", port=5001, debug=debug)
