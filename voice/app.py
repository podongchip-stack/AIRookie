"""feature/hub가 중계하는 통화 시작/종료 신호를 받아 로컬 마이크를 제어하는
HTTP 레이어. 녹음(mic_recorder.py)과 STT+필터링+SBAR 구조화(transcribe.py)는
손대지 않고 그대로 재사용한다 — call_capture.py의 "녹음만 하다가 종료 시
배치 파이프라인 실행" 흐름을, Ctrl+C 대신 HTTP 요청으로 트리거하도록 감싼
것뿐이다.

지금은 통화 1건 단독 처리만 다룬다 (동시 통화 미지원 — hub/info와 동일한
범위). 실제 오디오는 여기(voice의 로컬 마이크)에서 캡처한다 — dashboard가
브라우저 마이크로 캡처해 hub로 보내는 오디오(sendAudioChunk)는 화면
시각화 용도로만 쓰고 실제 STT 입력으로는 쓰지 않기로 했다 (voice와
dashboard/hub가 물리적으로 같은 공간에 있다고 가정하는 단독 처리 단계의
임시 구성이다).
"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify

from mic_recorder import MicRecorder
from transcribe import ORIGIN_DATA_DIR, transcribe

app = Flask(__name__)

# call_capture.py의 CLI 기본값과 동일 — 필요하면 환경변수로 덮어쓴다.
STT_MODEL = os.environ.get("VOICE_STT_MODEL", "medium")
LANGUAGE = os.environ.get("VOICE_LANGUAGE", "ko")
DEVICE = os.environ.get("VOICE_DEVICE", "auto")
COMPUTE_TYPE = os.environ.get("VOICE_COMPUTE_TYPE", "auto")
LLM_MODEL = os.environ.get("VOICE_LLM_MODEL", "qwen3:14b")

_recorder: MicRecorder | None = None
_session: str | None = None
_lock = threading.Lock()


def _run_pipeline(audio_path: Path) -> None:
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
    )


@app.post("/call/start")
def call_start():
    """hub가 중계한 "통화 시작" 신호. 로컬 마이크 녹음을 시작한다."""
    global _recorder, _session
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

    print(f"[통화 시작] 녹음 시작 (session={session})")
    return jsonify({"status": "recording", "session": session}), 200


@app.post("/call/end")
def call_end():
    """hub가 중계한 "통화 종료" 신호. 녹음을 멈추고 배치 파이프라인을
    백그라운드로 실행한다 (call_capture.py와 동일한 순서: 저장 -> stop ->
    STT+구조화)."""
    global _recorder, _session
    with _lock:
        if _recorder is None:
            return jsonify({"error": "not recording"}), 400

        recorder = _recorder
        session = _session
        _recorder = None
        _session = None

    audio_path = ORIGIN_DATA_DIR / f"{session}.wav"
    recorder.save_wav(audio_path)
    recorder.stop()
    print(f"[통화 종료] 녹음 저장 완료 (session={session}) — 파이프라인 실행 시작")

    threading.Thread(target=_run_pipeline, args=(audio_path,), daemon=True).start()

    return jsonify({"status": "processing_started", "session": session}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True, threaded=True)
