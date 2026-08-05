"""hub_engine.py 위에 얹는 HTTP 레이어. 매칭 로직(hub_engine.py)과 승인
처리(decision_log.py, delivery.py)는 손대지 않고 그대로 재사용한다 — 이
파일은 요청을 받아 파싱하고 엔진을 호출한 뒤 결과를 JSON으로 돌려주는
역할만 한다 (CLAUDE.md "모델/API 호출부와 비즈니스 로직은 분리해서
구현한다" 원칙).

지금은 사건(구급차) 1건 단독 처리만 다룬다. HubEngine 인스턴스 하나를
전역으로 두고 쓰며, 여러 사건이 동시에 처리되는 경우(사건별 상태 분리)는
다음 단계에서 다룬다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from pydantic import ValidationError

from delivery import deliver
from hub_engine import HubEngine
from schema import GpsPoint, HospitalInfo, VoiceCallSummaryMessage

app = Flask(__name__)
app.json.ensure_ascii = False  # 한글 필드를 유니코드 이스케이프 없이 그대로 응답
engine = HubEngine()

# 구급차 GPS를 보내는 별도 채널이 아직 없다 (feature/voice 출력 스키마에도 없음).
# 단독 처리 검증 단계라 run_match.py와 동일한 테스트 좌표(진주시청 부근)를
# 고정값으로 둔다 — 실제 GPS 연동은 이번 범위가 아니다.
AMBULANCE_GPS = GpsPoint(lat=35.1800, lng=128.1080)
MAX_ZONE = 1


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@app.post("/info/hospitals")
def receive_hospital_info():
    """feature/info로부터 병원 정보(HospitalInfo)를 받아 등록/갱신한다."""
    try:
        info = HospitalInfo.model_validate(request.get_json(force=True))
    except ValidationError as exc:
        return jsonify({"error": "invalid HospitalInfo", "detail": exc.errors()}), 400

    engine.update_hospital_info(info)
    return jsonify({"status": "ok", "hospitalId": info.hospitalId}), 200


@app.post("/voice/summary")
def receive_voice_summary():
    """feature/voice로부터 통화 요약(VoiceCallSummaryMessage)을 받아 2단계
    매칭(존 후보 + 진료과·거리 스코어링)을 실행하고 결과를 반환한다.
    """
    try:
        voice = VoiceCallSummaryMessage.model_validate(request.get_json(force=True))
    except ValidationError as exc:
        return jsonify({"error": "invalid VoiceCallSummaryMessage", "detail": exc.errors()}), 400

    result = engine.process_voice_summary(voice, AMBULANCE_GPS, max_zone=MAX_ZONE)

    # run_match.py와 동일하게 로컬 저장(감사용 사본)도 같이 남긴다. 실제
    # voice 요약 파일명이 없는 HTTP 경로라 타임스탬프로 이름을 대신한다.
    synthetic_path = Path(f"live_{_utcnow_iso().replace(':', '')}_call_summary.json")
    deliver(result, synthetic_path)

    return jsonify(result.model_dump()), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
