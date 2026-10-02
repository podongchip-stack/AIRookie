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

import bed_reliability
from ambulance_sim import SPEEDUP as SIM_SPEEDUP, DispatchSim
import decision_log
from delivery import HUB_REJECTION_URL, LIVE_OUTPUT_DIR, deliver, send_rejection_to_info
from routing import KakaoRouting
from geo import haversine_km
from scoring import DEFAULT_MIN_PER_KM
from hub_engine import HubEngine, _is_bed_count_unknown
from schema import (
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
    SceneEnd,
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
#: 구급차 출동 시뮬레이션(시연용 가짜 위치, 2026-10-01). HUB_SIM_DISPATCH=1일 때만 켠다.
SIM_DISPATCH = os.environ.get("HUB_SIM_DISPATCH") == "1"
sim: DispatchSim | None = DispatchSim(router) if SIM_DISPATCH else None
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
    # 30분 주기 재전송을 그대로 자기 화면 신선도 갱신으로 재사용.
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
        upstream = requests.get(url, params={"hpid": hpid} if hpid else None, timeout=30)  # 1시간마다 재생성(수 초)
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


#: 매칭 결과를 한 번이라도 받은 병원들(caseId -> hpid 집합). 후보에서 빠진 병원도
#: 다음 결과를 받아야 자기 화면의 카드를 지울 수 있어서, 역할별 전송의 수신 대상에 남긴다.
_case_audience: dict[str, set[str]] = {}


def _match_recipients(payload: dict) -> tuple[str | None, set[str]]:
    """매칭 결과를 받을 (구급차 apid, 병원 hpid 집합). _sockets_lock을 쥔 채로 부른다."""
    case_id = payload["caseId"]
    hospital_ids = {h.get("hospitalId") for h in payload.get("hospitals") or []}
    audience = _case_audience.setdefault(case_id, set())
    audience.update(hospital_ids)
    return payload.get("apid") or engine.get_case_apid(case_id), set(audience)


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
    message = json.dumps(payload, ensure_ascii=False)
    is_match = payload.get("type") == "match_result" and bool(payload.get("caseId"))
    with _sockets_lock:
        if is_match:
            apid, hospital_ids = _match_recipients(payload)
        dead = set()
        for ws in _dashboard_sockets:
            if is_match:
                role, id_ = _socket_identity.get(ws, (None, None))
                if not ((role == "ambulance" and id_ == apid) or (role == "hospital" and id_ in hospital_ids)):
                    continue
            try:
                ws.send(message)
            except Exception as e:  # noqa: BLE001
                print(f"  [통신] dashboard WebSocket 전송 실패, 연결 제거: {e}")
                dead.add(ws)
        _dashboard_sockets.difference_update(dead)

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


def _send_to_socket(ws, payload: dict, label: str) -> None:
    """소켓 하나에만 보낸다(따라잡기·신원 확인 응답). 브로드캐스트와 같은 락을 쓴다."""
    with _sockets_lock:
        try:
            ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            print(f"  [통신] {label} 전송 실패: {e}")


def _send_scene_candidates(case_id: str, apid: str) -> None:
    """환자 정보가 오기 전, 구급차 위치 기준 거리순 후보를 그 구급차 탭에만 보낸다
    (2026-10-01, 통화 시작 시·출동 시뮬레이션의 현장 도착 시). 예전엔 통화가 끝나 매칭 결과가
    올 때까지 병원 목록이 비어 있었다. 규칙 기반(거리)이고 진료과 매칭·승인은 아직 없어서,
    병원 탭에는 보내지 않는다 — 환자 정보 없는 요청이 병원 화면에 쌓이지 않게."""
    gps, fallback = _resolve_ambulance_gps(case_id)
    zone = engine.resolve_start_zone(gps)
    hospitals = engine.build_zone_candidates(gps, max_zone=zone)
    payload = {
        "type": "scene_candidates",
        "caseId": case_id,
        "apid": apid,
        "ambulanceGps": gps.model_dump(),
        "ambulanceGpsFallback": fallback,
        "zoneActive": list(range(1, zone + 1)),
        "hospitals": hospitals,
        "source": "rule",
    }
    # 첫 연락 추천(2026-10-03)을 의사결정 로그에 남긴다 — 추천 병원이 실제 첫 통화·수용으로
    # 이어졌는지(적중률)를 나중에 승인 액션·거절 로그와 대조해 셀 수 있는 유일한 재료라서다.
    recommended = next((h for h in hospitals if h.get("firstCallRecommended")), None)
    if recommended is not None:
        decision_log.log_decision("first_call_recommended", {
            "caseId": case_id,
            "apid": apid,
            "hospitalId": recommended["hospitalId"],
            "rArrive": round(recommended["bedReliability"]["rArrive"], 4),
            "distanceKm": recommended["distanceKm"],
            "availableBedCount": recommended["availableBedCount"],
        })
    with _sockets_lock:
        targets = [ws for ws, (role, id_) in _socket_identity.items() if role == "ambulance" and id_ == apid]
    for ws in targets:
        _send_to_socket(ws, payload, "현장 후보")


def _relay_call_signal(signal: CallSignal) -> None:
    """dashboard의 통화 시작/종료 신호를 그 apid로 등록된 feature/voice
    인스턴스로 중계한다. call_started 시점에 (caseId -> apid)를 hub_engine에
    등록해둬야, 나중에 그 caseId로 도착하는 /voice/summary가 이 구급차의
    GPS를 찾을 수 있다. voice가 아직 자가등록 전이거나 안 떠 있어도
    dashboard 쪽 흐름은 끊기면 안 되므로 예외를 흡수한다."""
    if signal.signal == "call_started":
        # 출동 시뮬레이션 중엔 현장 도착 뒤, 그 출동의 사건으로만 통화를 시작한다(버튼만 막는 게
        # 아니라 hub도 규칙을 지킨다).
        if sim is not None and (sim.phase_of(signal.apid) != "on_scene" or sim.case_of(signal.apid) != signal.caseId):
            print(f"  [시뮬레이션] {signal.apid} 통화 시작 거부 — 현장 도착 전이거나 다른 사건")
            decision_log.log_decision("call_start_refused", {"apid": signal.apid, "caseId": signal.caseId,
                                                             "phase": sim.phase_of(signal.apid)})
            return
        engine.register_case(signal.caseId, signal.apid)
        _send_scene_candidates(signal.caseId, signal.apid)

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
        # 따라잡기로 받아 본 것도 "도달"이다 — 뒤늦게 연결한 병원이 요청을
        # 봤는데 무응답이면 미도달이 아니라 무시로 분류돼야 한다.
        if identify.role == "hospital" and any(
            h.hospitalId == identify.id for h in result.hospitals
        ):
            with _sockets_lock:
                _case_reach.setdefault(result.caseId, set()).add(identify.id)


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
    info = DashboardIdentityInfo(
        role=identify.role, id=identify.id, name=name, known=known, simDispatch=sim is not None
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
    payload["stage"] = "arrival" if action.action == "arrival_refused" else "request"
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


def _close_case(case_id: str, reason: str) -> bool:
    """확정 없이 끝난 사건을 닫고 대시보드에 알린다. 방치 정리(sweep)와 현장 종료가 같이 쓴다."""
    if not engine.close_case(case_id):
        return False
    with _sockets_lock:
        _case_audience.pop(case_id, None)
    decision_log.log_decision("case_closed", {"caseId": case_id, "reason": reason})
    _send_to_dashboard({"type": "case_closed", "caseId": case_id, "reason": reason})
    print(f"  [정리] caseId={case_id} 사건 종료({reason}) — 캐시에서 제거, 대시보드에 알림")
    return True


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

    # 도착 후 수용 불가는 확정을 풀기 **전에** 결정 시점 스냅샷(병상 수·확률)을 떠 둔다.
    arrival_refusal = _build_rejection_payload(action) if action.action == "arrival_refused" else None
    applied = engine.apply_approval_action(action)

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
    elif action.action == "arrival_refused" and arrival_refusal is not None and applied:
        send_rejection_to_info(arrival_refusal)
        # 승인한 다른 병원이 없으면 그 자리에서 존을 넓혀 같은 환자 정보로 다시 요청한다(재통화 없음).
        if not engine.has_other_approved(action.caseId, action.hospital_id):
            ambulance_gps, _ = _resolve_ambulance_gps(action.caseId)
            expanded_result = engine.force_expand_zone(action.caseId, ambulance_gps)
    elif action.action == "arrival_accepted" and applied:
        # 무응답은 사건이 끝날 때 기록한다(2026-10-01). 예전엔 첫 이송 승인 순간에 기록해서, 그 뒤
        # 승인하고 재선택된 병원까지 "무응답"으로 남았다.
        _log_no_responses(action.caseId, action.timestamp, finalized_to=action.hospital_id)

    updated_result = expanded_result or engine.get_case_result(action.caseId)
    if updated_result is not None:
        _send_to_dashboard(updated_result.model_dump())
    if action.action == "arrival_accepted" and applied:
        # 환자 수용으로 이송이 끝났다 — 두 대시보드에서 이 사건(병원 후보·수용 요청·통화 요약)을 지운다
        # (2026-10-01). 엔진에는 기록·병상 차감 때문에 확정 60분 동안 남지만, 따라잡기에서도 빠진다.
        _send_to_dashboard({"type": "case_closed", "caseId": action.caseId, "reason": "arrival_accepted"})

    if sim is not None and applied and action.action in ("arrival_accepted", "arrival_refused"):
        apid = engine.get_case_apid(action.caseId)
        if apid and sim.on_arrival_result(apid, action.caseId, accepted=action.action == "arrival_accepted"):
            _broadcast_sim_state(apid)

    if sim is not None and action.action == "final_approval" and updated_result is not None:
        confirmed = next((h for h in updated_result.hospitals if h.status == "confirmed"), None)
        apid = engine.get_case_apid(action.caseId)
        if confirmed is not None and apid and sim.on_confirmed(apid, action.caseId, confirmed.hospitalId, confirmed.gps):
            _broadcast_sim_state(apid)


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
                with _sockets_lock:
                    _socket_identity[ws] = (identify.role, identify.id)
                _send_identity_info(ws, identify)
                _send_catchup(ws, identify)
                if sim is not None and identify.role == "ambulance":
                    state = sim.state(identify.id)
                    if state is not None:
                        _send_to_socket(ws, _sim_message("ambulance_phase", state), "시뮬레이션 상태")
                # 병원이면 사건 유무와 무관하게 "귀원 정보 현황"도 바로 준다.
                if identify.role == "hospital":
                    self_info = _build_self_info(identify.id)
                    if self_info is not None:
                        _send_to_socket(ws, self_info.model_dump(), "self_info")
            elif payload.get("type") == "info_confirm":
                try:
                    confirm = HospitalInfoConfirm.model_validate(payload)
                except ValidationError as exc:
                    print(f"  [통신] 잘못된 HospitalInfoConfirm 수신: {exc.errors()}")
                    continue
                _handle_info_confirm(confirm)
            elif payload.get("type") in ("dispatch", "scene_end"):
                _handle_sim_command(payload)
            elif "action" in payload:
                _handle_dashboard_action(payload)
    finally:
        with _sockets_lock:
            _dashboard_sockets.discard(ws)
            _socket_identity.pop(ws, None)


# ── 출동 시뮬레이션 (2026-10-01, HUB_SIM_DISPATCH=1) ─────────────────────────


def _sim_message(kind: str, state: dict) -> dict:
    """ambulance_phase(상태 바뀔 때, 경로 포함) / ambulance_position(움직이는 동안 1초마다, 경로 없음)."""
    body = dict(state) if kind == "ambulance_phase" else {k: v for k, v in state.items() if k != "path"}
    return {"type": kind, **body, "simulated": True}


def _send_sim(kind: str, state: dict) -> None:
    """그 구급차 탭 전부 + 이송 중·병원 도착이면 그 확정 병원 탭에만 보낸다(복귀는 병원과 무관)."""
    message = json.dumps(_sim_message(kind, state), ensure_ascii=False)
    hospital_id = state.get("hospitalId") if state.get("phase") in ("transporting", "at_hospital") else None
    with _sockets_lock:
        for ws, (role, id_) in list(_socket_identity.items()):
            if (role == "ambulance" and id_ == state["apid"]) or (hospital_id and role == "hospital" and id_ == hospital_id):
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
    """[이동](dispatch) · [현장 종료](scene_end)."""
    if sim is None:
        print("  [시뮬레이션] 꺼져 있어 출동·현장 종료 명령을 무시 (HUB_SIM_DISPATCH=1로 켬)")
        return
    try:
        cmd = (DispatchRequest if payload.get("type") == "dispatch" else SceneEnd).model_validate(payload)
    except ValidationError as exc:
        print(f"  [통신] 잘못된 시뮬레이션 명령: {exc.errors()}")
        return
    if isinstance(cmd, DispatchRequest):
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
            print(f"  [시뮬레이션] {cmd.apid} 출동 — caseId={cmd.caseId}")
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


def _sim_tick() -> None:
    """구급차를 한 칸 옮기고, 위치를 엔진(매칭·경로가 읽는 값)과 대시보드에 반영한다."""
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
            # 확정 없이 방치된 사건: 무응답 기록 뒤 사건을 닫는다(case_closed).
            _sweep_unresolved_cases()
            # 확정된 지 CASE_RETENTION_MIN 지난 사건을 지우고, 열린 탭에서도 카드를 지우게 한다.
            for case_id in engine.prune_expired_cases():
                with _sockets_lock:
                    _case_audience.pop(case_id, None)
                _send_to_dashboard({"type": "case_closed", "caseId": case_id, "reason": "retention_expired"})
            if PERSIST_STATE and (engine.take_dirty() or _voice_addresses_dirty):
                save_state()
        except Exception as e:  # noqa: BLE001
            print(f"  [백그라운드] 오류(계속 진행): {e!r}")


def _settle_restored_cases() -> None:
    """재시작 때 복구된 확정 전 사건을 정리한다(2026-10-01).

    - 출동 시뮬레이션 중이면: 재시작하면 구급차가 전부 기지 대기로 돌아가서, 확정 전 사건은 이어갈 구급차가
      없다 → 바로 닫는다. 병원이 무시한 게 아니라 hub가 재시작한 것이라 무응답(NO_RESPONSE)은 남기지 않는다.
    - 아니면: 120분 방치 정리(sweep)의 기준인 마지막 활동 시각이 메모리에만 있어 재시작 뒤엔 영영 정리되지
      않았다 → 지금을 마지막 활동으로 잡아 둔다.
    """
    case_ids = engine.get_unconfirmed_case_ids()
    if not case_ids:
        return
    if sim is not None:
        for case_id in case_ids:
            if engine.close_case(case_id):
                decision_log.log_decision("case_closed", {"caseId": case_id, "reason": "hub_restart_sim_reset"})
        print(f"  [상태 복구] 출동 시뮬레이션 — 확정 전 사건 {len(case_ids)}건은 구급차가 기지로 돌아가 닫음")
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
    if sim is not None:
        # 재시작하면 구급차는 전부 기지(대기)에서 다시 시작한다 — 시뮬레이션 상태는 저장하지 않는다.
        for ambulance in engine.list_ambulances():
            sim.ensure_unit(ambulance.apid, ambulance.gps)
        decision_log.log_decision("sim_dispatch_enabled", {"speedup": SIM_SPEEDUP})
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
