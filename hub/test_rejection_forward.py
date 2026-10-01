"""dashboard의 hospital_reject 액션이 feature/info 거절 로그 수신구
(POST /hub/rejection)로 실제로 중계되는지 확인한다.

run_match.py(엔진 로직 검증)와 분리한 이유: 이 경로는 app.py의 HTTP 레이어
(_handle_dashboard_action -> _build_rejection_payload -> delivery.send_rejection_to_info)를
타므로, 수신구 스텁 서버를 하나 띄워 왕복을 실제로 확인해야 한다.

    conda activate rookie_hub
    python hub/test_rejection_forward.py
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# delivery가 모듈 로드 시점에 HUB_REJECTION_URL을 기본 인자로 바인딩하므로,
# app을 import하기 전에 스텁 주소로 덮어써야 한다.
_STUB_PORT = 5599
os.environ["HUB_REJECTION_URL"] = f"http://127.0.0.1:{_STUB_PORT}/hub/rejection"

import app  # noqa: E402
from schema import (  # noqa: E402
    ApprovalAction,
    Assessment,
    AssessmentConditions,
    AssessmentGroup,
    BedReliabilityInput,
    GpsPoint,
    HospitalInfo,
    Specialty,
    VoiceCallSummaryMessage,
    VoiceSummary,
    VoiceTranscript,
)

_received: list[dict] = []


class _StubHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        _received.append(json.loads(self.rfile.read(length) or b"{}"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true, "saved": 1}')

    def log_message(self, *args):  # 스텁 서버 접속 로그 억제
        pass


def _assessment(tier: str) -> Assessment:
    return Assessment(
        assessedAt="2026-09-10T00:00:00+09:00",
        conditions=AssessmentConditions(),
        evidence={},
        groups={
            "대동맥응급": AssessmentGroup(
                status="available" if tier == "declared_yes" else "unknown",
                tier=tier, score=1.0, confidence="high", basis=["테스트"], items={},
            )
        },
    )


def main() -> None:
    server = HTTPServer(("127.0.0.1", _STUB_PORT), _StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"=== 거절 로그 수신구 스텁 기동 (127.0.0.1:{_STUB_PORT}) ===")

    engine = app.engine
    engine.update_hospital_info(HospitalInfo(
        hospitalId="A1100017", name="[테스트] 대동맥응급 가능 신고 병원",
        gps=GpsPoint(lat=37.5665, lng=126.9780), availableBedCount=4, nightDutyAvailable=True,
        specialties=[Specialty(department="심장혈관흉부외과", doctorCount=2)],
        updatedAt="2026-09-10T00:00:00Z",
        assessment=_assessment("declared_yes"),
        bedReliability=BedReliabilityInput(
            predictedSurvivalSec=2400.0, bornAt="2026-09-10T00:00:00+00:00",
            authorityAtSend=1.0, ttlSec=2400.0, modelTag="aft_egen_theta3_ext0923",
        ),
    ))
    # 무응답(NO_RESPONSE) 시나리오용 두 번째 후보 — 아무 액션도 안 보낸다.
    engine.update_hospital_info(HospitalInfo(
        hospitalId="A1100099", name="[테스트] 끝까지 무응답 병원",
        gps=GpsPoint(lat=37.5700, lng=126.9820), availableBedCount=2, nightDutyAvailable=True,
        specialties=[Specialty(department="심장혈관흉부외과", doctorCount=1)],
        updatedAt="2026-09-10T00:00:00Z",
    ))

    case_id = "case-rejection-forward"
    engine.process_voice_summary(
        VoiceCallSummaryMessage(
            caseId=case_id,
            transcript=VoiceTranscript(raw_text="x", filtered_text="x"),
            summary=VoiceSummary(
                patient="60대 남성", mechanism="대동맥 박리 의심",
                symptoms=["흉통"], treatment=["산소 공급"], severity_tag="high",
            ),
            source="ai",
        ),
        app.FALLBACK_AMBULANCE_GPS,
        max_zone=1,
    )

    print("\n=== hospital_reject 액션 처리 (사유: BEDS_FULL) ===")
    app._handle_dashboard_action({
        "caseId": case_id,
        "action": "hospital_reject",
        "hospital_id": "A1100017",
        "actor": "hospital",
        "timestamp": "2026-09-10T14:30:00Z",
        "reason": "BEDS_FULL",
    })

    # 스텁 서버 스레드가 요청을 처리할 짧은 여유
    for _ in range(50):
        if _received:
            break
        threading.Event().wait(0.05)

    assert _received, "hospital_reject인데 거절 로그 수신구로 아무것도 안 왔다"
    payload = _received[0]
    print("  수신 payload:", json.dumps(payload, ensure_ascii=False))

    assert payload["hospitalId"] == "A1100017", "hospitalId가 그대로 전달돼야 한다"
    assert payload["caseId"] == case_id
    assert payload["reasonCode"] == "BEDS_FULL", "dashboard의 reason이 reasonCode로 전달돼야 한다"
    assert payload["severity"] == "high", "사건 캐시에서 중증도가 채워져야 한다"
    assert payload["diseaseGroup"] == "대동맥응급", "매칭된 질환군이 채워져야 한다"
    assert payload["declaredAtRequest"] == "Y", (
        "declared_yes tier면 '가능이라 신고했는데 거절'을 셀 수 있게 Y로 전달돼야 한다"
    )
    print("  [확인] hospitalId·caseId·reasonCode·severity·diseaseGroup·declaredAtRequest 전부 전달됨")

    # 결정 시점 스냅샷(2026-09-28 확충) — 그때 화면에 보였던 병상·신뢰도 확률이
    # 같이 남아야 "가능이라 떠 있었는데 거절"·"authority 높았는데 만실"을 셀 수 있다.
    assert payload["availableBedCountAtRequest"] == 4, "결정 시점 병상 수가 남아야 한다"
    assert payload["bedCountUnknownAtRequest"] is False
    assert "travelMinAtRequest" in payload and "finalScoreAtRequest" in payload
    assert 0.0 <= payload["bedAuthorityAtRequest"] <= 1.0, "결정 시점 authority가 남아야 한다"
    assert 0.0 <= payload["bedRArriveAtRequest"] <= payload["bedAuthorityAtRequest"]
    print("  [확인] 결정 시점 스냅샷(병상 수·travelMin·finalScore·authority·rArrive) 전부 전달됨")

    # 사유 없이 오는 경우도 UNSPECIFIED로 전달되는지 (관대 수신 원칙)
    _received.clear()
    app._handle_dashboard_action({
        "caseId": case_id, "action": "hospital_reject", "hospital_id": "A1100017",
        "actor": "hospital", "timestamp": "2026-09-10T14:31:00Z",
    })
    for _ in range(50):
        if _received:
            break
        threading.Event().wait(0.05)
    assert _received and _received[0]["reasonCode"] == "UNSPECIFIED", (
        "reason 없이 온 hospital_reject는 reasonCode=UNSPECIFIED로 전달돼야 한다"
    )
    print("  [확인] 사유 없는 거절도 reasonCode=UNSPECIFIED로 전달됨")

    # 이송 확정만으로는 무응답을 기록하지 않는다(2026-10-01) — 확정 뒤에 다른 병원이 승인하고
    # 재선택될 수 있어서, 그 병원까지 "무응답"으로 남는 문제가 있었다. 사건이 끝날 때(도착 수용) 기록한다.
    _received.clear()
    app._handle_dashboard_action({  # 거절했던 병원이 병상이 나서 다시 승인
        "caseId": case_id, "action": "hospital_approve", "hospital_id": "A1100017",
        "actor": "hospital", "timestamp": "2026-09-10T14:34:00Z",
    })
    app._handle_dashboard_action({
        "caseId": case_id, "action": "final_approval", "hospital_id": "A1100017",
        "actor": "paramedic", "timestamp": "2026-09-10T14:35:00Z",
    })
    threading.Event().wait(0.3)
    assert not _received, "이송 확정 순간에 NO_RESPONSE를 기록하면 안 된다"
    app._handle_dashboard_action({
        "caseId": case_id, "action": "arrival_accepted", "hospital_id": "A1100017",
        "actor": "hospital", "timestamp": "2026-09-10T14:50:00Z",
    })
    for _ in range(50):
        if _received:
            break
        threading.Event().wait(0.05)
    assert _received, "도착 수용인데 무응답 후보의 NO_RESPONSE 로그가 안 왔다"
    no_response = _received[0]
    print("  NO_RESPONSE payload:", json.dumps(no_response, ensure_ascii=False))
    assert no_response["hospitalId"] == "A1100099", "무응답 후보(A1100099)가 기록돼야 한다"
    assert no_response["reasonCode"] == "NO_RESPONSE"
    assert no_response["finalizedTo"] == "A1100017", "어느 병원으로 확정됐는지 남아야 한다"
    assert no_response["hospitalDashboardConnected"] is False, (
        "identify한 소켓이 없으니 미도달(false)로 구분돼야 한다"
    )
    assert no_response["caseFinalized"] is True, "확정으로 끝난 사건임이 표시돼야 한다"
    assert no_response["reachedAtBroadcast"] is False, (
        "병원 소켓이 한 번도 연결된 적 없으니 도달 이력도 없어야 한다"
    )
    print("  [확인] 확정 때가 아니라 도착 수용 때 무응답 후보가 NO_RESPONSE + 도달/확정 구분과 함께 기록됨")

    # 도착 결과가 중복 도착해도 무응답을 두 번 기록하지 않는다
    _received.clear()
    app._handle_dashboard_action({
        "caseId": case_id, "action": "arrival_accepted", "hospital_id": "A1100017",
        "actor": "hospital", "timestamp": "2026-09-10T14:51:00Z",
    })
    threading.Event().wait(0.3)
    assert not _received, "중복 도착 수용에 NO_RESPONSE가 또 기록되면 안 된다"
    print("  [확인] 중복 도착 결과에는 무응답 재기록 없음 (멱등)")

    # 확정 없이 방치된 사건은 sweep이 NO_RESPONSE(caseFinalized=false)로 정리한다
    _received.clear()
    from datetime import datetime, timedelta, timezone

    unresolved_case = "case-unresolved-sweep"
    engine.process_voice_summary(
        VoiceCallSummaryMessage(
            caseId=unresolved_case,
            transcript=VoiceTranscript(raw_text="x", filtered_text="x"),
            summary=VoiceSummary(
                patient="70대 여성", mechanism="대동맥 박리 의심",
                symptoms=["흉통"], treatment=["산소 공급"], severity_tag="high",
            ),
            source="ai",
        ),
        app.FALLBACK_AMBULANCE_GPS,
        max_zone=1,
    )
    with app._sockets_lock:
        app._case_last_activity[unresolved_case] = (
            datetime.now(timezone.utc) - timedelta(hours=3)
        )
    swept = app._sweep_unresolved_cases()
    assert swept == 1, f"유휴 초과 미결 사건 1건이 정리돼야 한다 (실제 {swept})"
    for _ in range(50):
        if len(_received) >= 2:
            break
        threading.Event().wait(0.05)
    assert len(_received) == 2, "미결 사건의 pending 후보 2곳이 전부 기록돼야 한다"
    assert all(p["reasonCode"] == "NO_RESPONSE" and p["caseFinalized"] is False for p in _received), (
        "미결 종료 무응답은 caseFinalized=false로 구분돼야 한다"
    )
    assert all("finalizedTo" not in p for p in _received)
    assert app._sweep_unresolved_cases() == 0, "이미 정리한 사건을 다시 정리하면 안 된다"
    assert engine.get_case_result(unresolved_case) is None, "정리된 미결 사건은 캐시에서 빠져야 한다"
    assert unresolved_case not in engine.get_active_case_ids(), "정리된 사건은 주기 재계산 대상이 아니다"
    print("  [확인] 미결 방치 사건의 무응답이 sweep으로 기록되고 사건이 닫힘 (caseFinalized=false, 재정리 없음)")

    # 수신구가 꺼져 있어도(연결 거부) 예외가 새어나오지 않아야 한다
    server.shutdown()
    server.server_close()  # 리슨 소켓까지 닫아 즉시 connection refused가 되게
    _received.clear()
    try:
        app._handle_dashboard_action({
            "caseId": case_id, "action": "hospital_reject", "hospital_id": "A1100017",
            "actor": "hospital", "timestamp": "2026-09-10T14:32:00Z", "reason": "NO_WARD",
        })
    except Exception as e:  # noqa: BLE001
        raise AssertionError(f"수신구가 꺼져 있을 때 예외가 올라왔다: {e}") from e
    print("  [확인] 수신구가 꺼져 있어도(fire-and-forget) 액션 처리는 예외 없이 계속됨")

    print("\n모든 검사 통과")


if __name__ == "__main__":
    main()
