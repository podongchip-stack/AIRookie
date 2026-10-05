"""app.py의 2026-09-28 정비분을 HTTP 레이어째 확인한다.

- /voice/summary가 매칭을 기다리지 않고 202로 답하고, 매칭은 작업 스레드에서 끝나
  WebSocket 브로드캐스트로 나가는지
- 구급차 위치를 못 찾은 사건이 결과에 ambulanceGpsFallback=True로 표시되는지
- 주기적 재계산이 바뀐 사건만 다시 보내는지
- 상태 파일 저장 → 새 엔진으로 복구가 되는지(통화 원문 제외)

run_match.py(엔진 로직)와 분리한 이유는 test_rejection_forward.py와 같다 — app 모듈의
전역(엔진·소켓 집합·작업 스레드)을 거쳐야 하는 경로라서다.

    conda activate rookie_hub
    python hub/test_app_background.py
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# 이 테스트가 실제 상태 파일(data/state/)·의사결정 로그(해시 체인)를 건드리지 않게
# import 전에 임시 경로로 돌린다.
_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decision_log.jsonl")

import app  # noqa: E402
import decision_log  # noqa: E402
from hub_engine import TRANSCRIPT_NOT_PERSISTED, HubEngine  # noqa: E402
from schema import (  # noqa: E402
    AmbulanceInfo, BedReliabilityInput, CallSignal, GpsPoint, HospitalInfo, Specialty,
)


class _FakeSocket:
    """flask-sock 소켓 대역. 보낸 메시지만 모아 둔다."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


def _hospital(beds: int) -> HospitalInfo:
    return HospitalInfo(
        hospitalId="T001", name="[테스트] 앱 레이어 병원",
        gps=GpsPoint(lat=37.5670, lng=126.9790), availableBedCount=beds, nightDutyAvailable=True,
        specialties=[Specialty(department="흉부외과", doctorCount=1)],
        updatedAt=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        bedsByType={"ER_ADULT": beds},
    )


def _flush_worker() -> None:
    """작업 스레드에 쌓인 일이 끝날 때까지 기다린다(작업자 1개라 순서대로 끝난다)."""
    app._match_executor.submit(lambda: None).result(timeout=120)


def main() -> None:
    socket = _FakeSocket()
    stranger = _FakeSocket()  # 이 사건 후보가 아닌 병원 탭 — 매칭 결과를 받으면 안 된다
    app._dashboard_sockets.update({socket, stranger})
    app._socket_identity[socket] = ("hospital", _hospital(beds=3).hospitalId)
    app._socket_identity[stranger] = ("hospital", "OTHER-HOSPITAL")
    app.engine.update_hospital_info(_hospital(beds=3))
    case_id = "case-app-background"
    secret = "통화 원문 — 상태 파일에 남으면 안 됨"

    print("=== /voice/summary: 202로 바로 답하고 매칭은 작업 스레드에서 ===")
    client = app.app.test_client()
    response = client.post("/voice/summary", json={
        "caseId": case_id,
        "transcript": {"raw_text": secret, "filtered_text": secret, "language": "ko",
                       "timestamp": "2026-09-28T00:00:00Z", "duration_sec": 10.0},
        "summary": {"patient": "50대 남성", "mechanism": "교통사고 흉부 충격", "symptoms": ["호흡 곤란"],
                    "treatment": ["산소 공급"], "severity_tag": "high"},
        "source": "ai",
    })
    assert response.status_code == 202, response.get_json()
    assert response.get_json() == {"status": "accepted", "caseId": case_id}
    _flush_worker()
    results = [m for m in socket.sent if m.get("type") == "match_result" and m["caseId"] == case_id]
    assert len(results) == 1, "매칭이 끝나면 WebSocket으로 결과가 한 번 나가야 한다"
    assert results[0]["ambulanceGpsFallback"] is True, "통화 시작 신호 없이 온 사건은 기본 좌표 대체로 표시돼야 한다"
    assert not stranger.sent, "후보가 아닌 병원 탭은 이 사건을 받지 않는다(역할별 전송)"
    print("  [확인] 202 응답, 결과는 type=match_result로 후보 병원 탭에만 전송, 기본 좌표 대체 표시")

    print("=== 주기적 재계산: 바뀐 사건만 다시 보냄 ===")
    socket.sent.clear()
    app._refresh_active_cases()
    assert not socket.sent, "바뀐 게 없으면 다시 보내지 않는다"
    app.engine.update_hospital_info(_hospital(beds=1))
    app._refresh_active_cases()
    assert len(socket.sent) == 1 and socket.sent[0]["hospitals"][0]["availableBedCount"] == 1
    print("  [확인] 변화 없음 → 전송 없음, 병상 3→1 → 재전송")

    print("=== 상태 저장·복구 ===")
    app._voice_addresses["A_TEST"] = "http://10.0.0.9:5002"
    app.save_state()
    saved = app.STATE_PATH.read_text(encoding="utf-8")
    assert secret not in saved and TRANSCRIPT_NOT_PERSISTED in saved, "통화 원문 대신 안내 문구가 저장돼야 한다"
    original = app.engine
    app.engine = HubEngine(specialty_matcher=original._matcher)
    app._voice_addresses.clear()
    try:
        app.load_state()
        restored = app.engine.get_case_result(case_id)
        assert restored is not None and restored.hospitals[0].availableBedCount == 1
        assert restored.patientInfo.rawTranscript == TRANSCRIPT_NOT_PERSISTED
        assert app.engine.get_hospital("T001") is not None
        assert app._voice_addresses.get("A_TEST") == "http://10.0.0.9:5002"
    finally:
        app.engine = original
    print("  [확인] 병원·사건·voice 주소 복구, 통화 원문은 저장·복구되지 않음")

    print("=== 통화 시작: 매칭 전 현장 후보를 그 구급차 탭에만 + 첫 연락 추천 ===")
    ambulance_tab = _FakeSocket()
    app._dashboard_sockets.add(ambulance_tab)
    app._socket_identity[ambulance_tab] = ("ambulance", "A_SCENE")
    socket.sent.clear()
    app.engine.update_ambulance_info(
        AmbulanceInfo(apid="A_SCENE", name="[테스트] 구급차", gps=GpsPoint(lat=37.5665, lng=126.9780), voicePort=6000,
                      updatedAt="2026-10-01T00:00:00Z")
    )
    # T001보다 조금 먼, 병상 신뢰도 예측이 붙은 병원 — 빈 병상이 확인되고 rArrive가
    # 있는 유일한 곳이라 첫 연락 추천을 받아야 한다(T001은 신뢰도 데이터가 없어 제외,
    # fail-soft 확인). 거리순 정렬 자체는 추천과 무관하게 유지돼야 한다.
    app.engine.update_hospital_info(HospitalInfo(
        hospitalId="T_REL", name="[테스트] 신뢰도 병원",
        gps=GpsPoint(lat=37.5750, lng=126.9900), availableBedCount=2, nightDutyAvailable=True,
        specialties=[Specialty(department="외과", doctorCount=1)],
        updatedAt=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        bedsByType={"ER_ADULT": 2},
        bedReliability=BedReliabilityInput(
            predictedSurvivalSec=4 * 3600.0, bornAt=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            sigma=1.0, authorityAtSend=0.95, ttlSec=3600.0, modelTag="test-aft",
        ),
    ))
    app._relay_call_signal(CallSignal(
        type="call_signal", signal="call_started", timestamp="2026-10-01T00:00:00Z", apid="A_SCENE", caseId="case-scene",
    ))
    scene = [m for m in ambulance_tab.sent if m.get("type") == "scene_candidates"]
    assert len(scene) == 1 and scene[0]["hospitals"][0]["hospitalId"] == "T001" and scene[0]["source"] == "rule"
    assert not any(m.get("type") == "scene_candidates" for m in socket.sent), "병원 탭은 현장 후보를 받지 않는다"
    by_id = {h["hospitalId"]: h for h in scene[0]["hospitals"]}
    assert by_id["T_REL"]["firstCallRecommended"] is True, "신뢰도 있는 빈 병상 병원이 첫 연락 추천을 받아야 한다"
    assert by_id["T_REL"]["bedReliability"]["rArrive"] > 0.5
    assert by_id["T001"]["firstCallRecommended"] is False and by_id["T001"]["bedReliability"] is None, \
        "신뢰도 데이터 없는 병원은 추천 없이 그대로(fail-soft)"
    logged = [json.loads(line) for line in decision_log.LOG_PATH.read_text(encoding="utf-8").splitlines()]
    first_call = [e for e in logged if e["eventType"] == "first_call_recommended"]
    assert len(first_call) == 1 and first_call[0]["payload"]["hospitalId"] == "T_REL", \
        "첫 연락 추천이 의사결정 로그에 남아야 한다(적중률 측정 재료)"
    print("  [확인] 거리순 후보가 구급차 탭에만 전송, T_REL 첫 연락 추천 + 로그 기록, T001은 fail-soft")

    app._dashboard_sockets.difference_update({socket, stranger, ambulance_tab})
    print("\n모든 검사 통과")


if __name__ == "__main__":
    main()
