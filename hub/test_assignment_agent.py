"""상황실 배정 에이전트 1단계(충돌 감지, 2026-11-04) 검사.

① 규칙(assignment_agent.detect_conflicts) — 1순위 겹침 + 여력 부족만 충돌, 미상은 충돌, 확정 사건은 제외
② 앱 배선 — 관제는 assignment_conflicts, 구급대는 dispatcher_pending, 구급대원 이송 승인은 막고 관제 지정은 받는다,
   확정으로 여력이 바뀌면 다시 판정해 대기를 푼다.

실행: python test_assignment_agent.py — 실제 상태·의사결정 로그·거절 로그는 건드리지 않는다(임시 경로로 돌린다).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decision_log.jsonl")
os.environ["HOSPITAL_REJECTION_LOG_DIR"] = str(Path(_TMP.name) / "rejections")
os.environ["HUB_REJECTION_URL"] = "http://127.0.0.1:9/hub/rejection"  # 수신구 없음 — 조용히 흡수된다
os.environ["HUB_SPIDER_HOUR"] = "14"  # 야간 감점이 붙으면 테스트 병원 역량이 KTAS 2 환자에 못 미쳐 수용 회신이 거부된다

import app  # noqa: E402
import assignment_agent as aa  # noqa: E402
from schema import DashboardIdentify, GpsPoint, VoiceCallSummaryMessage, VoiceSummary, VoiceTranscript  # noqa: E402
from test_app_background import _FakeSocket, _hospital  # noqa: E402

SCENE = GpsPoint(lat=37.5665, lng=126.9780)


def _case(case_id: str, ktas: int, hospitals: list[tuple[str, str]]) -> dict:
    return {"caseId": case_id, "patientInfo": {"ktasLevel": ktas},
            "hospitals": [{"hospitalId": h, "status": s} for h, s in hospitals]}


def test_rule() -> None:
    print("=== ① 규칙 ===")
    a = _case("A", 1, [("H1", "approved"), ("H2", "approved")])
    b = _case("B", 3, [("H1", "approved"), ("H3", "pending")])
    c = _case("C", 2, [("H2", "pending"), ("H1", "approved")])
    cap = {"H1": 1}

    groups = aa.detect_conflicts([b, a, c], cap.get)
    assert [g["hospitalId"] for g in groups] == ["H1"]
    assert groups[0]["caseIds"] == ["A", "C", "B"], "위급한 순(KTAS 1 → 2 → 3)"
    assert groups[0]["capacity"] == 1 and groups[0]["source"] == "rule"
    print("  [확인] 1순위 수용 병원 H1에 3건 · 여력 1 → 충돌, KTAS 순")

    assert aa.detect_conflicts([a, b], {"H1": 2}.get) == [], "여력이 사건 수 이상이면 충돌 아님"
    assert aa.detect_conflicts([a], {"H1": 0}.get) == [], "1건은 여력 0이어도 충돌 아님 — 병원이 수용 회신했다"
    unknown = aa.detect_conflicts([a, b], {}.get)
    assert unknown and not unknown[0]["capacityKnown"], "병상 미상·낡은 값은 2건 이상이면 충돌"
    confirmed = _case("A", 1, [("H1", "confirmed")])
    assert aa.detect_conflicts([confirmed, b], {"H1": 0}.get) == [], "확정 사건은 묶지 않는다"
    excluded = {"caseId": "D", "patientInfo": {"ktasLevel": 2},
                "hospitals": [{"hospitalId": "H1", "status": "approved", "excluded": True}, {"hospitalId": "H2", "status": "approved"}]}
    assert aa.top_accepted(excluded) == "H2", "이 사건에서 제외된 병원은 1순위가 아니다"
    print("  [확인] 여력 충분·1건·확정·제외 병원은 충돌 아님, 미상은 충돌")

    print("=== ① 배분 안 ===")
    def match(hid, status, line, travel):
        return {"hospitalId": hid, "name": hid, "status": status, "spiderLen": line, "travelMin": travel,
                "loadPenaltyMin": 0.0, "occupancyPenaltyMin": 0.0, "availableBedCount": 1,
                "ktasSuitability": {"confirmedBlock": None, "effectiveCapacity": 4.2, "requiredCapacity": 3}}
    results = {
        "A": {"caseId": "A", "patientInfo": {"ktasLevel": 1, "requiredDepartment": "흉부외과"},
              "hospitals": [match("H1", "approved", 5.0, 10.0)]},
        "B": {"caseId": "B", "patientInfo": {"ktasLevel": 2},
              "hospitals": [match("H1", "approved", 6.0, 9.0), match("H2", "approved", 9.0, 9.0), match("H3", "pending", 12.0, 8.0)]},
        "C": {"caseId": "C", "patientInfo": {"ktasLevel": 3},
              "hospitals": [match("H1", "approved", 8.0, 7.0), match("H2", "approved", 9.5, 12.0)]},
    }
    infos = {"H1": {"specialties": [{"department": "응급의학과", "doctorCount": 23}, {"department": "흉부외과", "doctorCount": 4}],
                    "equipmentOperating": {"CT": "Y", "ANGIO": "Y"}}}
    group = {"hospitalId": "H1", "caseIds": ["A", "B", "C"]}
    proposal = aa.build_proposal(group, results, infos, {"H1": 1, "H2": 5}.get)
    plan = {c["caseId"]: c["proposedHospitalId"] for c in proposal["cases"]}
    assert plan == {"A": "H1", "B": "H2", "C": "H2"}, plan
    b = proposal["cases"][1]
    assert "H1 여력은 더 위급한 환자에게" in b["reason"] and "이동 +0분" in b["reason"], b["reason"]
    assert [h["hospitalId"] for h in b["candidates"]] == ["H2", "H1", "H3"], "수용 병원(배정 뒤 순서) + 판단 대기 후보"
    a_h1 = proposal["cases"][0]["candidates"][0]
    assert a_h1["emDoctors"] == 23 and a_h1["deptDoctors"] == 4 and a_h1["equipment"]["ANGIO"] == "Y"
    assert a_h1["gainMin"] == 5.0, "줄 길이 5 = 이동 10 − 이득 5 + 부하 0"
    none = aa.build_proposal({"hospitalId": "H1", "caseIds": ["X"]},
                             {"X": {"patientInfo": {"ktasLevel": 2}, "hospitals": [match("H9", "pending", 3.0, 3.0)]}}, {}, {}.get)
    assert none["cases"][0]["proposedHospitalId"] is None and "수용 확인" in none["cases"][0]["reason"]
    print("  [확인] KTAS 1 → 권역(여력 1), 나머지 → 다음 수용 병원 · 근거(전문의·장비·줄 길이 분해) · 수용 병원 없으면 확인 필요")


def _summary(case_id: str) -> VoiceCallSummaryMessage:
    return VoiceCallSummaryMessage(
        caseId=case_id, transcript=VoiceTranscript(raw_text="", filtered_text=""),
        summary=VoiceSummary(patient="50대 남성", mechanism="흉부 충격", symptoms=[], treatment=[], severity_tag="high"),
        source="ai",
    )


def _of(sock: _FakeSocket, type_: str) -> list[dict]:
    return [m for m in sock.sent if m.get("type") == type_]


def _action(case_id: str, action: str, actor: str, hospital_id: str) -> dict:
    return {"caseId": case_id, "action": action, "hospital_id": hospital_id, "actor": actor,
            "timestamp": "2026-11-04T09:00:00Z"}


def test_app() -> None:
    print("=== ② 앱 배선 ===")
    full = _hospital(beds=1)  # 여력 1
    app.engine.update_hospital_info(full)
    monitor, amb1, amb2 = _FakeSocket(), _FakeSocket(), _FakeSocket()
    app._dashboard_sockets.update({monitor, amb1, amb2})
    app._handle_identify(monitor, DashboardIdentify(role="monitor", id="map"))
    app._handle_identify(amb1, DashboardIdentify(role="ambulance", id="A1"))
    app._handle_identify(amb2, DashboardIdentify(role="ambulance", id="A2"))
    assert _of(monitor, "assignment_conflicts")[-1]["groups"] == [], "연결 때 지금 충돌 목록(없음)을 받는다"

    for case_id, apid in (("case-1", "A1"), ("case-2", "A2")):
        app.engine.register_case(case_id, apid)
        app._send_to_dashboard(app.engine.process_voice_summary(_summary(case_id), SCENE).model_dump())
    assert app._assignment_groups == [], "수용 회신 전엔 충돌 아님"

    app._handle_dashboard_action(_action("case-1", "hospital_approve", "hospital", full.hospitalId))
    assert app._assignment_groups == [], "한 사건만 수용이면 충돌 아님"
    app._handle_dashboard_action(_action("case-2", "hospital_approve", "hospital", full.hospitalId))
    group = _of(monitor, "assignment_conflicts")[-1]["groups"]
    assert len(group) == 1 and set(group[0]["caseIds"]) == {"case-1", "case-2"} and group[0]["capacity"] == 1
    assert group[0]["hospitalName"] == full.name
    proposal = group[0]["proposal"]
    assert [c["proposedHospitalId"] for c in proposal["cases"]] == [full.hospitalId, full.hospitalId]
    assert proposal["cases"][1]["overCapacity"], "다른 수용 병원이 없으면 여력 초과로 표시한 채 제안한다"
    assert proposal["cases"][0]["candidates"][0]["emergencyLevel"] == full.emergencyLevel
    for sock, case_id in ((amb1, "case-1"), (amb2, "case-2")):
        pending = _of(sock, "dispatcher_pending")
        assert pending and pending[-1]["caseId"] == case_id and pending[-1]["pending"], "구급대 탭이 관제 판단 대기를 받는다"
    assert not any(m["caseId"] == "case-2" for m in _of(amb1, "dispatcher_pending")), "다른 구급대 사건은 안 받는다"
    print("  [확인] 두 사건 1순위 같고 여력 1 → 관제 assignment_conflicts · 각 구급대 dispatcher_pending")

    late = _FakeSocket()
    app._dashboard_sockets.add(late)
    app._handle_identify(late, DashboardIdentify(role="ambulance", id="A2"))
    assert _of(late, "dispatcher_pending")[-1]["pending"], "뒤늦게 연 구급대 탭도 대기 상태를 따라잡는다"

    app._handle_dashboard_action(_action("case-1", "final_approval", "paramedic", full.hospitalId), ws=amb1)
    assert _of(amb1, "action_refused")[-1]["reason"] == "dispatcher_pending", "구급대원 이송 승인은 막힌다"
    assert app.engine.get_case_result("case-1").hospitals[0].status != "confirmed"
    print("  [확인] 대기 중 구급대원 이송 승인 거부(dispatcher_pending)")

    app._handle_dashboard_action(_action("case-1", "final_approval", "dispatcher", full.hospitalId), ws=monitor)
    app._match_executor.submit(lambda: None).result(timeout=120)
    assert any(h.status == "confirmed" for h in app.engine.get_case_result("case-1").hospitals), "관제 지정은 받는다"
    assert app._assignment_groups == [], "한 건이 확정되면 남은 1건은 충돌 아님"
    assert not _of(amb2, "dispatcher_pending")[-1]["pending"], "남은 사건의 대기가 풀린다"
    assert _of(monitor, "assignment_conflicts")[-1]["groups"] == []
    log = [json.loads(line) for line in app.decision_log.LOG_PATH.read_text(encoding="utf-8").splitlines()]
    decided = [e["payload"] for e in log if e["eventType"] == "assignment_decided"]
    assert decided == [{"caseId": "case-1", "hospitalId": full.hospitalId, "proposedHospitalId": full.hospitalId,
                        "followedProposal": True}], decided
    print("  [확인] 관제가 case-1 지정 → 충돌 해소, case-2 대기 해제")


if __name__ == "__main__":
    test_rule()
    test_app()
    print("\n모든 검사 통과")
