"""E-Gen 응급실·중증질환 메시지(acceptanceMessages, 2026-10-07) 수신·강등 검증.

- 사건 질환군에 지금 유효한 중증질환 차단 메시지가 걸린 병원은 severe_blocked로 순위만 내린다(후보에 남음)
- 끝난 메시지·아직 시작 전인 메시지는 싣지도, 내리지도 않는다
- 응급실 메시지는 필요 진료과와 같거나 응급실 전체 공지면 matched, matched가 앞
- 병원이 이 사건에 승인하면 메시지보다 그 응답이 우선 — 내리지 않는다
- 메시지 필드가 없는 병원(구 info 데이터)도 그대로 통과

임베딩 모델 없이 돌도록 가짜 진료과 매처를 쓴다.

    python hub/test_acceptance_messages.py
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ.setdefault("HUB_DECISION_LOG_PATH", str(Path(_TMP.name) / "decision_log.jsonl"))
os.environ.setdefault("HUB_STATE_PATH", str(Path(_TMP.name) / "hub_state.json"))

from hub_engine import HubEngine  # noqa: E402
from schema import (  # noqa: E402
    AcceptanceMessage,
    ApprovalAction,
    GpsPoint,
    HospitalInfo,
    Specialty,
    VoiceCallSummaryMessage,
    VoiceSummary,
    VoiceTranscript,
)
from test_real_hospitals import real_capability  # noqa: E402

KST = timezone(timedelta(hours=9))
SCENE = GpsPoint(lat=37.5665, lng=126.9780)


class _FakeMatcher:
    """병원의 첫 진료과를 유사도 0.5로 고른다 — 모든 병원이 같은 진료과 점수라 거리로만 순위가 갈린다."""

    def match_many(self, text, department_lists):
        return [(depts[0], 0.5) if depts else (None, 0.0) for depts in department_lists]


def _at(minutes: int) -> str:
    return (datetime.now(KST) + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def _hospital(hpid: str, lat: float, messages: list[AcceptanceMessage] | None) -> HospitalInfo:
    return HospitalInfo(
        hospitalId=hpid, name=f"[테스트] {hpid}", gps=GpsPoint(lat=lat, lng=126.9780),
        availableBedCount=5, nightDutyAvailable=True,
        **real_capability("강북삼성병원", [Specialty(department="흉부외과", doctorCount=0)]),
        updatedAt="2026-10-07T00:00:00Z", bedsByType={"ER_ADULT": 5},
        acceptanceMessages=messages,
    )


def _severe(group: str, start: int, end: int) -> AcceptanceMessage:
    return AcceptanceMessage(kind="severe", message="의료진 부족", department="흉부외과",
                             diseaseCode="Y0041", diseaseName="대동맥응급(흉부)", diseaseGroup=group,
                             startAt=_at(start), endAt=_at(end))


def _er(department: str, text: str) -> AcceptanceMessage:
    return AcceptanceMessage(kind="er", message=text, department=department, startAt=_at(-60), endAt=_at(60))


def _voice(case_id: str) -> VoiceCallSummaryMessage:
    return VoiceCallSummaryMessage(
        caseId=case_id,
        transcript=VoiceTranscript(raw_text="x", filtered_text="x"),
        summary=VoiceSummary(patient="60대 남성", mechanism="대동맥 박리 의심", symptoms=["흉통"],
                             treatment=[], severity_tag="high", required_department="흉부외과"),
        source="ai",
    )


def main() -> None:
    engine = HubEngine(specialty_matcher=_FakeMatcher())
    # 가까운 순: M001(차단) < M002(끝난 차단 + 응급실 메시지) < M003(시작 전 차단) < M004(필드 없음)
    engine.update_hospital_info(_hospital("M001", 37.5700, [_severe("대동맥응급", -60, 60),
                                                           _severe("중증화상", -60, 60)]))
    engine.update_hospital_info(_hospital("M002", 37.5750, [
        _severe("대동맥응급", -120, -1),
        _er("산부인과", "모든 산모 수용 불가"),
        _er("흉부외과", "흉부외과 야간 불가"),
        _er("응급실", "119 구급대원께서는 문의 후 이송 부탁드립니다."),
    ]))
    engine.update_hospital_info(_hospital("M003", 37.5800, [_severe("대동맥응급", 30, 90)]))
    engine.update_hospital_info(_hospital("M004", 37.5850, None))

    case_id = "case-acceptance-messages"
    engine.register_case(case_id, "A0000099")
    result = engine.process_voice_summary(_voice(case_id), SCENE, max_zone=1)
    order = [h.hospitalId for h in result.hospitals]
    by_id = {h.hospitalId: h for h in result.hospitals}
    for h in result.hospitals:
        msgs = [(m.kind, m.department, m.matched) for m in h.acceptanceMessages or []]
        print(f"  {h.hospitalId} {h.distanceKm}km demote={h.demoteReasons} messages={msgs}")

    assert order == ["M002", "M003", "M004", "M001"], f"차단 병원(M001)만 맨 뒤여야 한다: {order}"
    m1 = by_id["M001"]
    assert m1.demoteReasons == ["severe_blocked"]
    assert [m.matched for m in m1.acceptanceMessages] == [True, False], "사건 질환군 메시지가 앞, 다른 질환군은 matched 아님"
    assert m1.acceptanceMessages[0].diseaseGroup == "대동맥응급"
    print("  [확인] 사건 질환군 차단 메시지 → severe_blocked로 맨 뒤(후보에는 남음), 다른 질환군 메시지는 matched 아님")

    m2 = by_id["M002"]
    assert m2.demoteReasons == [], "끝난 차단 메시지로 내리면 안 된다"
    assert all(m.kind == "er" for m in m2.acceptanceMessages), "끝난 메시지는 싣지 않는다"
    assert [(m.department, m.matched) for m in m2.acceptanceMessages] == [
        ("흉부외과", True), ("응급실", True), ("산부인과", False)
    ], "필요 진료과·응급실 공지가 matched로 앞"
    assert by_id["M003"].acceptanceMessages is None and by_id["M003"].demoteReasons == [], "시작 전 메시지는 무시"
    assert by_id["M004"].acceptanceMessages is None, "메시지 필드 없는 병원도 그대로 통과"
    print("  [확인] 끝난·시작 전 메시지는 싣지도 내리지도 않음, 응급실 메시지는 필요 진료과·응급실 공지가 matched")

    engine.apply_approval_action(ApprovalAction(caseId=case_id, action="hospital_approve", hospital_id="M001",
                                                actor="hospital", timestamp="2026-10-07T00:00:00Z"))
    cached = engine.get_case_result(case_id)
    assert cached.hospitals[0].hospitalId == "M001" and cached.hospitals[0].demoteReasons == [], (
        "병원이 승인했으면 차단 메시지보다 그 응답이 우선 — 승인 병원으로 맨 앞"
    )
    print("  [확인] 차단 메시지가 있어도 병원이 이 사건에 승인하면 내리지 않음")
    print("\ntest_acceptance_messages 통과")


if __name__ == "__main__":
    main()
