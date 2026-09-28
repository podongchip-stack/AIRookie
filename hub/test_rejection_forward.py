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
