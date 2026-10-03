"""feature/hub가 중계하는 통화 시작/종료 신호를 받아 로컬 마이크를 제어하는
HTTP 레이어. call_capture.py와 같은 흐름(통화 중 발화 단위 인식 -> 종료 시
구조화·전송)을 Ctrl+C 대신 HTTP 요청으로 트리거하도록 감싼 것이다.

두 모델(ASR·MF_BERT)은 서버가 뜰 때 한 번만 올려두고 통화마다 재사용한다. 통화 중에는
live_transcriber.py가 말이 끊길 때마다 그 발화를 바로 인식해 두므로, 종료 신호 뒤에는
마지막 발화 인식과 구조화(1초 미만)만 남는다.

여러 구급차가 동시에 사건을 진행할 수 있다. 이 프로세스 자체는 구급차 1대
전용(실제 마이크가 그 구급차 장비 하나뿐이라 통화도 한 번에 하나만 가능)
이지만, hub 입장에서는 여러 대의 voice 인스턴스를 apid로 구분해야 한다.
그래서 시작할 때 자기 IP를 자동 탐지해 hub에 자가등록하고(VOICE_APID로
자신을 식별), 통화 시작 신호에 실려오는 caseId를 세션에 들고 있다가 hub로
보내는 요약에 그대로 실어 돌려준다 — hub는 이 caseId로 "어느 사건" 것인지
가려낸다. 실제 오디오는 여기(voice의 로컬 마이크)에서 캡처한다 — dashboard가
브라우저 마이크로 캡처해 hub로 보내는 오디오(sendAudioChunk)는 화면
시각화 용도로만 쓰고 실제 STT 입력으로는 쓰지 않는다.

중앙 모드(VOICE_MODE=central, 2026-10-03): voice를 구급차마다 띄우지 않고 **한 대만** 띄운다. 구급차 대시보드
(휴대폰·태블릿 브라우저)가 마이크 음성을 16kHz PCM으로 hub에 보내면 hub가 사건(caseId)별로 여기에 넘기고,
여기서 사건마다 따로 녹음기(StreamRecorder)·발화 인식기를 두고 인식·구조화해 hub로 돌려준다. 모델은 하나를
여러 통화가 순서대로 나눠 쓴다. hub에는 "중앙 voice"로 자가등록하고 30초마다 다시 알린다(hub 재시작 대비).
    POST /call/start {caseId, apid, hospitalId?}   통화 세션 시작
    POST /call/<caseId>/audio  (16비트 PCM 바이트)  음성 조각
    POST /call/end {caseId}                         남은 인식·구조화·hub 전송
음성이 VOICE_IDLE_END_SEC(기본 60초) 동안 안 오면 그 통화를 저절로 끝낸다(휴대폰 화면이 꺼진 경우 등).
"""
from __future__ import annotations

import os
import socket
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request

from asr import AsrModel
from MF_BERT import MfBertExtractor
from live_transcriber import LiveTranscriber
from mic_recorder import MicRecorder
from stream_recorder import StreamRecorder
from transcribe import ORIGIN_DATA_DIR, emit_call_summary, load_models

app = Flask(__name__)

# call_capture.py의 CLI 기본값과 동일 — 필요하면 환경변수로 덮어쓴다.
DEVICE = os.environ.get("VOICE_DEVICE", "auto")

# 이 voice 인스턴스가 담당하는 구급차. hub의 ambulances 레지스트리(apid)와
# 맞아야 하고, 없으면 자가등록을 아예 시도하지 않는다(단독 CLI 테스트 등).
VOICE_APID = os.environ.get("VOICE_APID")
HUB_BASE_URL = os.environ.get("HUB_BASE_URL", "http://127.0.0.1:5001")
# hub가 아직 이 apid의 AmbulanceInfo를 못 받았거나(info가 아직 안 떴거나) hub
# 자체가 안 떠 있으면 등록이 실패한다 — 한 번 실패하고 포기하지 않고 이
# 주기로 계속 재시도한다(info/send_to_hub.py와 동일한 재시도 철학).
VOICE_REGISTER_RETRY_SEC = int(os.environ.get("VOICE_REGISTER_RETRY_SEC", 5))
# 통화 중 발화 하나를 인식할 때마다 그 문장을 보내는 hub 주소(2026-10-03). hub가 그 구급차 대시보드의 통화
# 시연 패널에만 실시간으로 띄운다(저장하지 않음). 예전엔 인식 결과가 통화가 끝나 요약에 실릴 때까지 화면에
# 안 나왔다. 따로 안 주면 HUB_BASE_URL의 /voice/utterance.
HUB_VOICE_UTTERANCE_URL = os.environ.get("HUB_VOICE_UTTERANCE_URL", f"{HUB_BASE_URL.rstrip('/')}/voice/utterance")

# 이 voice 인스턴스가 실제로 바인딩할 포트. 포트 배정표(hub=5001, info=5002
# 고정, voice=구급차 장비마다 6000대, 팀 합의 2026-08-11)의 voice 몫 — 구급차
# 레지스트리(AmbulanceInfo.voicePort)에 등록된 값과 맞춰서 실행해야 hub가
# 자가등록 시 알려주는 IP와 조합해 이 인스턴스를 찾을 수 있다. 하드코딩하면
# info(5002)와 포트가 겹쳐 같은 장비에서 동시에 못 띄우므로 환경변수로 뺐다.
VOICE_PORT = int(os.environ.get("VOICE_PORT", 6000))

# local(기본): 이 장비 마이크로 구급차 1대 전용 / central: 브라우저 음성을 hub 경유로 받아 모든 구급차를 처리
VOICE_MODE = os.environ.get("VOICE_MODE", "local")
# 중앙 모드: 이 시간 동안 음성이 안 오면 그 통화를 저절로 끝낸다(초)
VOICE_IDLE_END_SEC = float(os.environ.get("VOICE_IDLE_END_SEC", 60))
# 중앙 모드: hub에 "중앙 voice"로 다시 알리는 주기(초) — hub가 재시작해도 다시 붙는다
VOICE_HEARTBEAT_SEC = float(os.environ.get("VOICE_HEARTBEAT_SEC", 30))

# 서버 시작 시 __main__에서 한 번 채운다
_asr_model: AsrModel | None = None
_extractor: MfBertExtractor | None = None

_recorder: MicRecorder | None = None
_live: LiveTranscriber | None = None
_session: str | None = None
_case_id: str | None = None
_lock = threading.Lock()


class _Serialized:
    """모델 하나를 여러 통화 스레드가 나눠 쓸 때 호출을 한 번에 하나씩만 하게 감싼다(중앙 모드)."""

    def __init__(self, inner, lock: threading.Lock) -> None:
        self._inner = inner
        self._lock = lock

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            with self._lock:
                return attr(*args, **kwargs)

        return call


class _CallSession:
    """중앙 모드의 통화 하나 — 사건마다 녹음기·발화 인식기를 따로 둔다."""

    def __init__(self, case_id: str, apid: str | None, hospital_id: str | None) -> None:
        self.case_id = case_id
        self.apid = apid
        self.hospital_id = hospital_id
        self.name = f"{datetime.now().strftime('%Y_%m%d_%H%M%S')}_{apid or 'unknown'}_{case_id[:8]}"
        self.recorder = StreamRecorder()
        self.live = LiveTranscriber(self.recorder, _asr_model, on_segment=lambda seg: _send_utterance(case_id, seg, apid))
        self.live.start()


_sessions: dict[str, _CallSession] = {}


def _detect_own_ip(hub_base_url: str) -> str:
    """UDP 소켓을 hub 쪽으로 "연결"해봐서(실제로 패킷을 보내지 않아도 OS가
    라우팅 테이블로 나갈 인터페이스를 정해준다) 그 인터페이스의 로컬 IP를
    알아낸다. 구급차 노트북마다 와이파이/핫스팟 등 네트워크가 달라 IP가
    고정돼 있지 않으므로, 매번 실행 시점에 직접 탐지한다."""
    hub_host = urlparse(hub_base_url).hostname or "127.0.0.1"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((hub_host, 1))
        return sock.getsockname()[0]
    finally:
        sock.close()


def _register_with_hub() -> None:
    """VOICE_APID가 설정돼 있으면 자기 IP를 탐지해 hub에 자가등록한다.
    hub가 아직 이 apid를 모르면(feature/info가 구급차 정보를 아직 안
    보냈으면) 409가 오는데, 이 프로세스 자체를 멈출 이유는 아니라서
    VOICE_REGISTER_RETRY_SEC마다 계속 재시도한다."""
    if not VOICE_APID:
        print("  [통신] VOICE_APID 미설정 — hub 자가등록을 건너뜀 (단독 테스트 모드)")
        return

    while True:
        try:
            ip = _detect_own_ip(HUB_BASE_URL)
            response = requests.post(
                f"{HUB_BASE_URL}/voice/register",
                json={"apid": VOICE_APID, "ip": ip},
                timeout=10,
            )
            response.raise_for_status()
            print(f"  [통신] hub 자가등록 완료 — apid={VOICE_APID}, ip={ip}")
            return
        except requests.RequestException as e:
            print(f"  [통신] hub 자가등록 실패, {VOICE_REGISTER_RETRY_SEC}초 뒤 재시도: {e}")
            time.sleep(VOICE_REGISTER_RETRY_SEC)


def _send_utterance(case_id: str | None, segment, apid: str | None = None) -> None:
    """인식한 발화 하나를 hub로 보낸다 — 통화·인식을 막지 않게 별도 스레드에서, 실패는 흡수(화면 표시용일 뿐).
    중앙 모드는 통화마다 구급차가 달라 apid를 받는다."""
    apid = apid or VOICE_APID
    if not apid:
        return
    payload = {"apid": apid, "caseId": case_id, "start": round(segment.start, 1),
               "end": round(segment.end, 1), "text": segment.text}

    def post() -> None:
        try:
            requests.post(HUB_VOICE_UTTERANCE_URL, json=payload, timeout=3)
        except requests.RequestException as e:
            print(f"  [통신] 실시간 발화 전달 실패(통화 요약에는 그대로 들어간다): {e}")

    threading.Thread(target=post, daemon=True).start()


def _run_pipeline(live: LiveTranscriber, duration_sec: float, session: str, case_id: str | None) -> None:
    """남은 발화 인식 + 구조화 + hub 전송을 백그라운드 스레드에서 실행한다.
    통화 중 인식이 밀려 있으면 몇 초 걸릴 수 있어 /call/end 응답을 막지 않으려고
    스레드로 뺐다 — 완료되면 emit_call_summary() 안의 send_to_hub()가 hub로 보낸다.
    """
    segments = live.finish()
    emit_call_summary(segments, duration_sec, session, _extractor, case_id)


# ── 중앙 모드 (2026-10-03) ─────────────────────────────────────────────────


def _central_start(payload: dict):
    case_id = payload.get("caseId")
    if not case_id:
        return jsonify({"error": "caseId required"}), 400
    with _lock:
        if case_id in _sessions:
            return jsonify({"error": "already recording", "caseId": case_id}), 409
        session = _CallSession(case_id, payload.get("apid"), payload.get("hospitalId"))
        _sessions[case_id] = session
    print(f"[통화 시작] {session.apid} → {session.hospital_id or '-'} (caseId={case_id}, 진행 중 {len(_sessions)}건)")
    return jsonify({"status": "recording", "session": session.name}), 200


def _central_end(case_id: str, reason: str) -> bool:
    with _lock:
        session = _sessions.pop(case_id, None)
    if session is None:
        return False
    session.recorder.save_wav(ORIGIN_DATA_DIR / f"{session.name}.wav")
    duration_sec = len(session.recorder.snapshot()) / session.recorder.sample_rate
    print(f"[통화 종료] {session.apid} caseId={case_id} ({duration_sec:.1f}초, {reason}) — 남은 발화 인식·구조화 시작")
    threading.Thread(
        target=_run_pipeline, args=(session.live, duration_sec, session.name, case_id), daemon=True
    ).start()
    return True


@app.post("/call/<case_id>/audio")
def call_audio(case_id: str):
    """중앙 모드: hub가 넘기는 그 사건의 음성 조각(16비트 리틀엔디언 모노 PCM, 16kHz)."""
    with _lock:
        session = _sessions.get(case_id)
    if session is None:
        return jsonify({"error": "no such call", "caseId": case_id}), 404
    samples = session.recorder.append(request.get_data())
    return jsonify({"status": "ok", "samples": samples}), 200


def _idle_watch() -> None:
    """음성이 한동안 안 들어온 통화를 끝낸다 — 휴대폰 화면이 꺼지거나 연결이 끊겨 종료 신호가 안 온 경우."""
    while True:
        time.sleep(5)
        now = time.monotonic()
        with _lock:
            idle = [cid for cid, s in _sessions.items() if now - s.recorder.last_audio_at > VOICE_IDLE_END_SEC]
        for case_id in idle:
            _central_end(case_id, f"{VOICE_IDLE_END_SEC:.0f}초 동안 음성 없음 — 자동 종료")


def _register_central_with_hub() -> None:
    """중앙 voice로 hub에 자가등록하고, VOICE_HEARTBEAT_SEC마다 다시 알린다(hub가 재시작해도 다시 붙게)."""
    registered = False
    while True:
        try:
            ip = _detect_own_ip(HUB_BASE_URL)
            response = requests.post(
                f"{HUB_BASE_URL}/voice/register",
                json={"central": True, "ip": ip, "port": VOICE_PORT},
                timeout=10,
            )
            response.raise_for_status()
            if not registered:
                print(f"  [통신] hub에 중앙 voice로 등록 완료 — http://{ip}:{VOICE_PORT}")
            registered = True
            time.sleep(VOICE_HEARTBEAT_SEC)
        except requests.RequestException as e:
            print(f"  [통신] hub 중앙 voice 등록 실패, {VOICE_REGISTER_RETRY_SEC}초 뒤 재시도: {e}")
            registered = False
            time.sleep(VOICE_REGISTER_RETRY_SEC)


@app.post("/call/start")
def call_start():
    """hub가 중계한 "통화 시작" 신호. 로컬 마이크 녹음을 시작하고, 같이 온
    caseId를 세션에 기억해뒀다가 통화 종료 후 요약에 그대로 실어 보낸다.
    중앙 모드면 그 사건의 통화 세션을 만든다(음성은 /call/<caseId>/audio로 온다)."""
    global _recorder, _live, _session, _case_id
    payload = request.get_json(silent=True) or {}
    if VOICE_MODE == "central":
        return _central_start(payload)
    case_id = payload.get("caseId")

    with _lock:
        if _recorder is not None:
            return jsonify({"error": "already recording", "session": _session}), 409

        session = datetime.now().strftime("%Y_%m%d_%H%M%S")
        recorder = MicRecorder()
        try:
            recorder.start()
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 500
        live = LiveTranscriber(recorder, _asr_model, on_segment=lambda seg: _send_utterance(case_id, seg))
        live.start()

        _recorder = recorder
        _live = live
        _session = session
        _case_id = case_id

    print(f"[통화 시작] 녹음 시작 (session={session}, caseId={case_id})")
    return jsonify({"status": "recording", "session": session}), 200


@app.post("/call/end")
def call_end():
    """hub가 중계한 "통화 종료" 신호. 녹음을 멈추고 남은 처리를 백그라운드로
    실행한다 (call_capture.py와 동일한 순서: 저장 -> stop -> 남은 발화 인식+구조화).
    녹음 파일은 인식에 쓰지 않지만 사후 검증(원본 보존)용으로 남긴다."""
    global _recorder, _live, _session, _case_id
    if VOICE_MODE == "central":
        case_id = (request.get_json(silent=True) or {}).get("caseId")
        if not case_id or not _central_end(case_id, "통화 종료 신호"):
            return jsonify({"error": "not recording", "caseId": case_id}), 400
        return jsonify({"status": "processing_started", "caseId": case_id}), 200
    with _lock:
        if _recorder is None:
            return jsonify({"error": "not recording"}), 400

        recorder = _recorder
        live = _live
        session = _session
        case_id = _case_id
        _recorder = None
        _live = None
        _session = None
        _case_id = None

    recorder.save_wav(ORIGIN_DATA_DIR / f"{session}.wav")
    recorder.stop()
    duration_sec = len(recorder.snapshot()) / recorder.sample_rate
    print(f"[통화 종료] 녹음 저장 완료 (session={session}, {duration_sec:.1f}초) — 남은 발화 인식·구조화 시작")

    threading.Thread(target=_run_pipeline, args=(live, duration_sec, session, case_id), daemon=True).start()

    return jsonify({"status": "processing_started", "session": session}), 200


if __name__ == "__main__":
    from console import use_utf8_console

    use_utf8_console()  # Windows(cp949) 콘솔에서도 로그 출력으로 죽지 않게
    # hub가 살아있든 아니든 서버는 바로 뜨게, 자가등록은 별도 스레드에서
    # 재시도하며 진행한다 (hub/info가 이 voice보다 늦게 뜨는 순서도 흔할 것).
    if VOICE_MODE == "central":
        print(f"[중앙 voice] 구급차 여러 대의 브라우저 음성을 hub 경유로 받는다 (포트 {VOICE_PORT})")
        threading.Thread(target=_register_central_with_hub, daemon=True).start()
        threading.Thread(target=_idle_watch, daemon=True).start()
    else:
        threading.Thread(target=_register_with_hub, daemon=True).start()
    _asr_model, _extractor = load_models(DEVICE)
    if VOICE_MODE == "central":
        # 통화 여러 건이 모델 하나를 나눠 쓴다 — 인식·구조화 호출을 한 번에 하나씩
        _model_lock = threading.Lock()
        _asr_model = _Serialized(_asr_model, _model_lock)
        _extractor = _Serialized(_extractor, _model_lock)
    # [demo 브랜치 전용] 시연 대본 입구 — STT 없이 MF_BERT 구조화만(demo_text.py, develop 병합 금지)
    import demo_text

    demo_text.register(app, lambda: _extractor)
    # 디버그 리로더는 프로세스를 하나 더 띄워 두 모델(수 GB)을 한 번 더 올리므로 끈다
    app.run(host="0.0.0.0", port=VOICE_PORT, debug=True, threaded=True, use_reloader=False)
