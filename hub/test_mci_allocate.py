"""대량사고 [분배 확정] 검사(2026-10-05) — 실제 서버·로그 없이 app 함수를 직접 부른다.

- 중증 → 중등증 → 경증 순으로 확정한다(요청 순서와 무관)
- 사건마다 승인 병원 중 hub 순위 1위 — 하나 확정할 때마다 순위를 다시 매겨 이송 중 부하 페널티가 반영된다
  (한 병원에 몰지 않고 분산)
- 승인 병원이 없는 사건은 건너뛴다

    python test_mci_allocate.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decision_log.jsonl")
os.environ["HOSPITAL_REJECTION_LOG_DIR"] = str(Path(_TMP.name) / "rejections")
os.environ["HUB_REJECTION_URL"] = "http://127.0.0.1:9/hub/rejection"

import app  # noqa: E402
from schema import GpsPoint, VoiceCallSummaryMessage, VoiceSummary, VoiceTranscript  # noqa: E402
from test_app_background import _FakeSocket, _hospital  # noqa: E402

GPS = GpsPoint(lat=37.5665, lng=126.9780)


def _case(case_id: str, severity: str) -> None:
    app.engine.register_case(case_id, "A_NONE")
    app.engine.process_voice_summary(VoiceCallSummaryMessage(
        caseId=case_id, transcript=VoiceTranscript(raw_text="t", filtered_text="t"),
        summary=VoiceSummary(patient="성인", mechanism="흉통", symptoms=[], treatment=[], severity_tag=severity),
        source="ai",
    ), GPS)


def main() -> None:
    app.sim = None
    a = _hospital(beds=2)
    b = a.model_copy(update={"hospitalId": "T002", "name": "[테스트] 두 번째 병원", "gps": GpsPoint(lat=37.5675, lng=126.9800)})
    for h in (a, b):
        app.engine.update_hospital_info(h)

    cases = [("mci-low", "low"), ("mci-high-1", "high"), ("mci-mid", "medium"), ("mci-high-2", "high"), ("mci-none", "high")]
    for case_id, severity in cases:
        _case(case_id, severity)
    for case_id, _ in cases:
        if case_id == "mci-none":
            continue  # 승인 병원 없음
        for h in (a, b):
            app._handle_dashboard_action({"caseId": case_id, "action": "hospital_approve", "hospital_id": h.hospitalId,
                                          "actor": "hospital", "timestamp": "2026-10-05T00:00:00Z"})

    print("=== 미리 보기(mci_plan)는 확정하지 않는다 ===")
    plan = app.engine.plan_mci([c for c, _ in cases])
    assert all(app.engine.get_case_status(c, h) != "confirmed" for c, _ in cases for h in ("T001", "T002"))
    preview = {p["caseId"]: p["hospitalId"] for p in plan}
    print(f"  [확인] 미리 보기 {preview}")

    console = _FakeSocket()
    results = app._mci_allocate([c for c, _ in cases], console)
    print("=== 확정은 미리 보기와 같다 ===")
    assert {r["caseId"]: r["hospitalId"] for r in results} == preview, (results, preview)
    print("  [확인] 미리 보기 == 확정")

    print("=== 중증 → 중등증 → 경증 순으로 확정 ===")
    order = [r["caseId"] for r in results]
    assert order.index("mci-high-1") < order.index("mci-mid") < order.index("mci-low"), order
    assert order.index("mci-high-2") < order.index("mci-mid"), order
    print(f"  [확인] 처리 순서 {order}")

    print("=== 승인 병원 중 hub 순위 1위, 확정마다 부하 페널티로 분산 ===")
    confirmed = {r["caseId"]: r["hospitalId"] for r in results if r["reason"] == "confirmed"}
    assert set(confirmed) == {"mci-high-1", "mci-high-2", "mci-mid", "mci-low"}, results
    assert len(set(confirmed.values())) == 2, f"한 병원에 다 몰리면 안 된다: {confirmed}"
    assert any(r.get("loadPenaltyMin") for r in results if r["reason"] == "confirmed"), "뒤 사상자엔 부하 페널티가 붙는다"
    for case_id, hospital_id in confirmed.items():
        assert app.engine.get_case_status(case_id, hospital_id) == "confirmed"
    print(f"  [확인] 배정 {confirmed}")

    print("=== 승인 병원이 없는 사건은 건너뛰고, 콘솔에 결과를 돌려준다 ===")
    skipped = next(r for r in results if r["caseId"] == "mci-none")
    assert skipped["hospitalId"] is None and skipped["reason"] == "no_approved_hospital", skipped
    reply = [m for m in console.sent if m.get("type") == "mci_allocated"][-1]
    assert len(reply["results"]) == len(cases)
    print("  [확인] 승인 병원 없음 → 건너뜀, mci_allocated 응답")
    print("\n모든 검사 통과")


if __name__ == "__main__":
    main()
