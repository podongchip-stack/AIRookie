"""구급대원 통화 요약 확인·수정(Override, 2026-10-13) 검증 — HubEngine.apply_patient_override.

- 수정 없이 확인만: 순위·병원 그대로, confirmedBy "paramedic"·확인 시각, overrides 비어 있음
- 미확정 사건에서 KTAS를 올리면(3 → 2) 중증도가 high로 따라 바뀌고 다시 매칭돼 권역센터가 앞으로 온다
- 다시 매칭해도 병원 승인은 유지된다(승인을 자동으로 풀지 않는다 — 변경 배너로 알린다)
- 이송 확정 사건은 순위 칸을 고쳐도 병원 순서를 그대로 두고 환자 정보만 바꾼다
- 같은 칸을 두 번 고쳐도 ai는 처음 AI 값 그대로, AI 값으로 되돌리면 그 칸은 overrides에서 빠진다
- 표시용 칸(주 호소·증상)만 고치면 재매칭하지 않는다
- 새 통화 회차가 오면 확인 상태가 초기화된다(새 AI 요약은 확인 전)
- 60초 주기 재계산(refresh_case)에도 고친 값·확인 상태가 유지된다
- 상태 저장·복구 뒤에도 확인 상태가 남는다
- 없는 사건이면 None

임베딩 모델 없이 돌도록 가짜 진료과 매처를 쓴다. 의사결정 로그·상태 파일은 임시 경로.

    python hub/test_patient_override.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ.setdefault("HUB_DECISION_LOG_PATH", str(Path(_TMP.name) / "decision_log.jsonl"))
os.environ.setdefault("HUB_STATE_PATH", str(Path(_TMP.name) / "hub_state.json"))

from hub_engine import HubEngine  # noqa: E402
from schema import (  # noqa: E402
    ApprovalAction,
    GpsPoint,
    HospitalInfo,
    PatientOverride,
    Specialty,
    VoiceCallSummaryMessage,
    VoiceSummary,
    VoiceTranscript,
)

SCENE = GpsPoint(lat=37.5665, lng=126.9780)


class _FakeMatcher:
    """모든 병원의 첫 진료과를 유사도 0.5로 — 진료과 점수가 같아 거리·등급 가산으로만 순위가 갈린다."""

    def match_many(self, text, department_lists):
        return [(depts[0], 0.5) if depts else (None, 0.0) for depts in department_lists]


def _hospital(hpid: str, lat: float, level: str | None) -> HospitalInfo:
    return HospitalInfo(
        hospitalId=hpid, name=f"[테스트] {hpid}", gps=GpsPoint(lat=lat, lng=126.9780),
        availableBedCount=5, nightDutyAvailable=True,
        specialties=[Specialty(department="내과", doctorCount=0)],
        updatedAt="2026-10-13T00:00:00Z", bedsByType={"ER_ADULT": 5}, emergencyLevel=level,
    )


def _voice(case_id: str, ktas: int, severity: str, text: str = "복통") -> VoiceCallSummaryMessage:
    return VoiceCallSummaryMessage(
        caseId=case_id,
        transcript=VoiceTranscript(raw_text="통화 원문", filtered_text="통화 원문"),
        summary=VoiceSummary(patient="50대 남성", mechanism=text, symptoms=["복통"], treatment=[],
                             severity_tag=severity, ktas_level=ktas, chief_complaint="복통"),
        source="ai",
    )


def _order(result) -> list[str]:
    return [h.hospitalId for h in result.hospitals]


def _engine() -> HubEngine:
    engine = HubEngine(specialty_matcher=_FakeMatcher())
    # 가까운 지역기관(C100) vs 조금 먼 권역센터(C200). 중등증이면 가까운 쪽, 중증이면 권역 가산(−5분)으로 뒤집힌다.
    engine.update_hospital_info(_hospital("C100", 37.5675, "지역응급의료기관"))
    engine.update_hospital_info(_hospital("C200", 37.5800, "권역응급의료센터"))
    return engine


def main() -> None:
    # ── 수정 없이 확인 ──
    engine = _engine()
    first = engine.process_voice_summary(_voice("case-a", 3, "medium"), SCENE, max_zone=3)
    assert first.patientInfo.confirmedBy == "ai" and first.patientInfo.confirmedAt is None
    assert _order(first)[0] == "C100", _order(first)
    result, log = engine.apply_patient_override(PatientOverride(caseId="case-a"), SCENE)
    assert result.patientInfo.confirmedBy == "paramedic" and result.patientInfo.confirmedAt
    assert result.patientInfo.overrides == [] and log["confirmedOnly"] and not log["rematched"]
    assert _order(result) == _order(first)
    print("ok — 수정 없이 확인: 순위 그대로, confirmedBy=paramedic")

    # ── KTAS 3 → 2: 중증도 high, 재매칭으로 권역센터가 앞으로, 병원 승인 유지 ──
    engine.apply_approval_action(ApprovalAction(caseId="case-a", action="hospital_approve", hospital_id="C100",
                                                actor="hospital", timestamp="2026-10-13T00:00:00Z"))
    result, log = engine.apply_patient_override(PatientOverride(caseId="case-a", ktasLevel=2), SCENE)
    assert log["rematched"] and result.patientInfo.severityTag == "high" and result.patientInfo.ktasLevel == 2
    rec = {r.field: r for r in result.patientInfo.overrides}
    assert rec["ktasLevel"].ai == 3 and rec["ktasLevel"].value == 2
    status = {h.hospitalId: h.status for h in result.hospitals}
    assert status["C100"] == "approved", status
    # 승인한 병원이 앞에 오는 정렬 원칙이 있으므로, 순위 효과는 승인 없는 새 사건으로 따로 본다
    engine2 = _engine()
    engine2.process_voice_summary(_voice("case-b", 3, "medium"), SCENE, max_zone=3)
    upgraded, _ = engine2.apply_patient_override(PatientOverride(caseId="case-b", ktasLevel=2), SCENE)
    assert _order(upgraded)[0] == "C200", _order(upgraded)
    print("ok — KTAS 3→2: 중증도 high, 재매칭으로 권역센터 1순위, 기존 승인 유지")

    # ── 같은 칸 두 번·AI 값으로 되돌리기 ──
    again, _ = engine2.apply_patient_override(PatientOverride(caseId="case-b", ktasLevel=1), SCENE)
    rec = {r.field: r for r in again.patientInfo.overrides}
    assert rec["ktasLevel"].ai == 3 and rec["ktasLevel"].value == 1
    back, _ = engine2.apply_patient_override(PatientOverride(caseId="case-b", ktasLevel=3), SCENE)
    assert all(r.field != "ktasLevel" for r in back.patientInfo.overrides)
    assert back.patientInfo.severityTag == "medium" and _order(back)[0] == "C100"
    print("ok — 같은 칸을 다시 고쳐도 ai는 처음 값, AI 값으로 되돌리면 칸이 빠지고 순위도 돌아옴")

    # ── 표시용 칸만: 재매칭 없음 ──
    shown, log = engine2.apply_patient_override(
        PatientOverride(caseId="case-b", chiefComplaint="상복부 통증", injuryStatus=["복통", " 구토 ", ""]), SCENE)
    assert not log["rematched"] and shown.patientInfo.chiefComplaint == "상복부 통증"
    assert shown.patientInfo.injuryStatus == ["복통", "구토"]
    print("ok — 주 호소·증상만 고치면 재매칭 없이 환자 정보만 바뀜(빈 칸·공백 정리)")

    # ── 60초 재계산에도 유지 ──
    refreshed = engine2.refresh_case("case-b", SCENE) or engine2.get_case_result("case-b")
    assert refreshed.patientInfo.confirmedBy == "paramedic"
    assert refreshed.patientInfo.chiefComplaint == "상복부 통증"
    print("ok — 주기 재계산 뒤에도 고친 값·확인 상태 유지")

    # ── 이송 확정 사건: 순서 그대로 ──
    engine3 = _engine()
    engine3.process_voice_summary(_voice("case-c", 3, "medium"), SCENE, max_zone=3)
    engine3.apply_approval_action(ApprovalAction(caseId="case-c", action="hospital_approve", hospital_id="C100",
                                                 actor="hospital", timestamp="2026-10-13T00:00:00Z"))
    engine3.apply_approval_action(ApprovalAction(caseId="case-c", action="final_approval", hospital_id="C100",
                                                 actor="paramedic", timestamp="2026-10-13T00:01:00Z"))
    before = engine3.get_case_result("case-c")
    after, log = engine3.apply_patient_override(PatientOverride(caseId="case-c", ktasLevel=1), SCENE)
    assert not log["rematched"] and log["caseConfirmed"]
    assert _order(after) == _order(before) and after.patientInfo.ktasLevel == 1
    assert {h.hospitalId: h.status for h in after.hospitals}["C100"] == "confirmed"
    print("ok — 이송 확정 사건은 KTAS를 고쳐도 병원 순서·확정 유지, 환자 정보만 바뀜")

    # ── 상태 저장·복구 ──
    state = engine2.export_state()
    restored = HubEngine(specialty_matcher=_FakeMatcher())
    restored.import_state(state)
    again = restored.refresh_case("case-b", SCENE) or restored.get_case_result("case-b")
    assert again.patientInfo.confirmedBy == "paramedic"
    assert {r.field for r in again.patientInfo.overrides} == {"chiefComplaint", "injuryStatus"}
    print("ok — 상태 저장·복구 뒤에도 확인 상태·고친 칸 유지")

    # ── 새 통화 회차: 확인 초기화 ──
    newer = engine2.add_call_summary(_voice("case-b", 2, "high", "흉통"), SCENE, max_zone=3)
    assert newer.patientInfo.callRound == 2 and newer.patientInfo.confirmedBy == "ai"
    assert newer.patientInfo.overrides == []
    print("ok — 새 통화 회차는 확인 전(confirmedBy=ai)으로 돌아감")

    # ── 없는 사건 ──
    assert engine.apply_patient_override(PatientOverride(caseId="nope"), SCENE) is None
    print("ok — 없는 사건은 None")
    print("\n전부 통과")


if __name__ == "__main__":
    main()
