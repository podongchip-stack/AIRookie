"""feature/hub가 중계하는 통화 시작/종료 신호를 받아 로컬 마이크를 제어하는
HTTP 레이어. 녹음(mic_recorder.py)과 STT+필터링+SBAR 구조화(transcribe.py)는
손대지 않고 그대로 재사용한다 — call_capture.py의 "녹음만 하다가 종료 시
배치 파이프라인 실행" 흐름을, Ctrl+C 대신 HTTP 요청으로 트리거하도록 감싼
것뿐이다.

여러 구급차가 동시에 사건을 진행할 수 있다. 이 프로세스 자체는 구급차 1대
전용(실제 마이크가 그 구급차 장비 하나뿐이라 통화도 한 번에 하나만 가능)
이지만, hub 입장에서는 여러 대의 voice 인스턴스를 apid로 구분해야 한다.
그래서 시작할 때 자기 IP를 자동 탐지해 hub에 자가등록하고(VOICE_APID로
자신을 식별), 통화 시작 신호에 실려오는 caseId를 세션에 들고 있다가 hub로
보내는 요약에 그대로 실어 돌려준다 — hub는 이 caseId로 "어느 사건" 것인지
가려낸다. 실제 오디오는 여기(voice의 로컬 마이크)에서 캡처한다 — dashboard가
브라우저 마이크로 캡처해 hub로 보내는 오디오(sendAudioChunk)는 화면
시각화 용도로만 쓰고 실제 STT 입력으로는 쓰지 않는다.
"""
from __future__ import annotations

import os
import socket
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request

from mic_recorder import MicRecorder
from transcribe import ORIGIN_DATA_DIR, transcribe

app = Flask(__name__)

# call_capture.py의 CLI 기본값과 동일 — 필요하면 환경변수로 덮어쓴다.
STT_MODEL = os.environ.get("VOICE_STT_MODEL", "medium")
LANGUAGE = os.environ.get("VOICE_LANGUAGE", "ko")
DEVICE = os.environ.get("VOICE_DEVICE", "auto")
COMPUTE_TYPE = os.environ.get("VOICE_COMPUTE_TYPE", "auto")
LLM_MODEL = os.environ.get("VOICE_LLM_MODEL", "qwen3:14b")

# 이 voice 인스턴스가 담당하는 구급차. hub의 ambulances 레지스트리(apid)와
# 맞아야 하고, 없으면 자가등록을 아예 시도하지 않는다(단독 CLI 테스트 등).
VOICE_APID = os.environ.get("VOICE_APID")
HUB_BASE_URL = os.environ.get("HUB_BASE_URL", "http://127.0.0.1:5001")
# hub가 아직 이 apid의 AmbulanceInfo를 못 받았거나(info가 아직 안 떴거나) hub
# 자체가 안 떠 있으면 등록이 실패한다 — 한 번 실패하고 포기하지 않고 이
# 주기로 계속 재시도한다(info/send_to_hub.py와 동일한 재시도 철학).
VOICE_REGISTER_RETRY_SEC = int(os.environ.get("VOICE_REGISTER_RETRY_SEC", 5))

# 이 voice 인스턴스가 실제로 바인딩할 포트. 포트 배정표(hub=5001, info=5002
# 고정, voice=구급차 장비마다 6000대, 팀 합의 2026-08-11)의 voice 몫 — 구급차
# 레지스트리(AmbulanceInfo.voicePort)에 등록된 값과 맞춰서 실행해야 hub가
# 자가등록 시 알려주는 IP와 조합해 이 인스턴스를 찾을 수 있다. 하드코딩하면
# info(5002)와 포트가 겹쳐 같은 장비에서 동시에 못 띄우므로 환경변수로 뺐다.
VOICE_PORT = int(os.environ.get("VOICE_PORT", 6000))

_recorder: MicRecorder | None = None
_session: str | None = None
_case_id: str | None = None
_lock = threading.Lock()


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


def _run_pipeline(audio_path: Path, case_id: str | None) -> None:
    """STT+필터링+SBAR 구조화+hub 전송을 백그라운드 스레드에서 실행한다.
    수십 초 걸릴 수 있어 /call/end 응답을 막지 않으려고 스레드로 뺐다 —
    완료되면 transcribe() 내부의 send_to_hub()가 알아서 hub로 결과를 보낸다.
    """
    transcribe(
        audio_path=audio_path,
        model_size=STT_MODEL,
        language=LANGUAGE,
        device=DEVICE,
        compute_type=COMPUTE_TYPE,
        do_summarize=True,
        llm_model=LLM_MODEL,
        case_id=case_id,
    )


@app.post("/call/start")
def call_start():
    """hub가 중계한 "통화 시작" 신호. 로컬 마이크 녹음을 시작하고, 같이 온
    caseId를 세션에 기억해뒀다가 통화 종료 후 요약에 그대로 실어 보낸다."""
    global _recorder, _session, _case_id
    payload = request.get_json(silent=True) or {}
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

        _recorder = recorder
        _session = session
        _case_id = case_id

    print(f"[통화 시작] 녹음 시작 (session={session}, caseId={case_id})")
    return jsonify({"status": "recording", "session": session}), 200


@app.post("/call/end")
def call_end():
    """hub가 중계한 "통화 종료" 신호. 녹음을 멈추고 배치 파이프라인을
    백그라운드로 실행한다 (call_capture.py와 동일한 순서: 저장 -> stop ->
    STT+구조화)."""
    global _recorder, _session, _case_id
    with _lock:
        if _recorder is None:
            return jsonify({"error": "not recording"}), 400

        recorder = _recorder
        session = _session
        case_id = _case_id
        _recorder = None
        _session = None
        _case_id = None

    audio_path = ORIGIN_DATA_DIR / f"{session}.wav"
    recorder.save_wav(audio_path)
    recorder.stop()
    print(f"[통화 종료] 녹음 저장 완료 (session={session}) — 파이프라인 실행 시작")

    threading.Thread(target=_run_pipeline, args=(audio_path, case_id), daemon=True).start()

    return jsonify({"status": "processing_started", "session": session}), 200


if __name__ == "__main__":
    # hub가 살아있든 아니든 서버는 바로 뜨게, 자가등록은 별도 스레드에서
    # 재시도하며 진행한다 (hub/info가 이 voice보다 늦게 뜨는 순서도 흔할 것).
    threading.Thread(target=_register_with_hub, daemon=True).start()
    app.run(host="0.0.0.0", port=VOICE_PORT, debug=True, threaded=True)
