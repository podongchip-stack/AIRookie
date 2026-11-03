"""수용 곤란 사유의 되먹임(2026-11-04, refusal_memory.py) 검사 — 모델·네트워크·실제 로그를 쓰지 않는다.

① 규칙: 순간적 사유는 30분 동안 다른 사건에 +분, 구조적 사유는 같은 질환군만 24시간 뒤로, 주기적·환자 요인·사유 없음은
   반영 안 함, 자기 사건은 세지 않음, 시간이 지나면 풀림
② 엔진: 병원1이 사건 1을 '수술실 사용 중'으로 거절하면 사건 2에서 병원1 줄 길이가 15분 늘어 병원2가 앞선다(후보엔 남음).
   '필요 장비 없음'이면 같은 질환군 사건에서 structural_refusal로 뒤로 간다.

실행: python test_refusal_memory.py
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decision_log.jsonl")
os.environ["HUB_SPIDER_HOUR"] = "14"

from hub_engine import HubEngine  # noqa: E402
from refusal_memory import MOMENTARY_HOLD_MIN, MOMENTARY_PENALTY_MIN, RefusalMemory  # noqa: E402
from schema import ApprovalAction, BedReliabilityInput, GpsPoint, HospitalInfo  # noqa: E402
from test_real_hospitals import real_capability  # noqa: E402
from test_spider_rule import _voice  # noqa: E402

SCENE = GpsPoint(lat=37.5665, lng=126.9780)
T0 = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)


class _Matcher:
    def match_many(self, text, lists):
        return [(depts[0], 0.5) if depts else (None, 0.0) for depts in lists]


def test_rule() -> None:
    print("=== ① 규칙 ===")
    m = RefusalMemory()
    assert m.record("H1", "c1", "OR_OCCUPIED", "general", T0).axis == "momentary"
    assert m.record("H1", "c1", "ON_CALL_MISMATCH", "general", T0) is None, "주기적은 다른 사건에 반영 안 함"
    assert m.record("H1", "c1", "SEVERITY_EXCEEDED", "general", T0) is None, "환자 요인도"
    assert m.record("H1", "c1", None, "general", T0) is None, "사유 없음도"
    e = m.effect("H1", "c2", "general", T0 + timedelta(minutes=10))
    assert e.penalty_min == MOMENTARY_PENALTY_MIN and not e.demote and "수술실 사용 중" in e.reasons[0]
    assert m.effect("H1", "c1", "general", T0).penalty_min == 0, "자기 사건의 거절은 이미 rejected — 세지 않는다"
    assert m.effect("H1", "c2", "general", T0 + timedelta(minutes=MOMENTARY_HOLD_MIN + 1)).penalty_min == 0, "30분 뒤 풀림"

    m.record("H2", "c1", "NO_EQUIPMENT", "stemi", T0)
    assert m.effect("H2", "c2", "stemi", T0 + timedelta(hours=3)).demote, "같은 질환군은 뒤로"
    assert not m.effect("H2", "c2", "stroke", T0 + timedelta(hours=3)).demote, "다른 질환군엔 영향 없음"
    assert not m.effect("H2", "c2", "stemi", T0 + timedelta(hours=25)).demote, "24시간 뒤 풀림"
    print("  [확인] 순간적 30분 +15분 · 구조적 같은 질환군 24시간 · 주기적·환자 요인·사유 없음 반영 안 함 · 자기 사건 제외")


def _hospital(hid: str, lat: float) -> HospitalInfo:
    return HospitalInfo(hospitalId=hid, name=hid, gps=GpsPoint(lat=lat, lng=126.9780), availableBedCount=5,
                        bedsByType={"ER_ADULT": 5}, nightDutyAvailable=True, updatedAt=datetime.now(timezone.utc).isoformat(),
                        **real_capability("서울대학교병원"))


def _reject(engine: HubEngine, case_id: str, hid: str, reason: str) -> None:
    assert engine.apply_approval_action(ApprovalAction(caseId=case_id, action="hospital_reject", hospital_id=hid,
                                                       actor="hospital", timestamp="2026-11-04T05:00:00Z", reason=reason))


def test_engine() -> None:
    print("=== ② 엔진 ===")
    engine = HubEngine(specialty_matcher=_Matcher())
    engine.update_hospital_info(_hospital("H1", 37.5675))  # 가깝다
    engine.update_hospital_info(_hospital("H2", 37.5745))  # 조금 멀다
    first = engine.process_voice_summary(_voice("c1", 2), SCENE)
    assert first.hospitals[0].hospitalId == "H1"
    _reject(engine, "c1", "H1", "OR_OCCUPIED")
    second = engine.process_voice_summary(_voice("c2", 2), SCENE)
    h1 = next(h for h in second.hospitals if h.hospitalId == "H1")
    assert h1.refusalPenaltyMin == MOMENTARY_PENALTY_MIN and h1.refusalReasons and "수술실 사용 중" in h1.refusalReasons[0]
    assert second.hospitals[0].hospitalId == "H2", "병원1은 30분 동안 +15분 — 병원2가 앞선다"
    assert {h.hospitalId for h in second.hospitals} == {"H1", "H2"}, "후보에서 빼지 않는다"
    print("  [확인] 수술실 사용 중 거절 → 다른 사건에서 병원1 +15분, 병원2가 1순위, 병원1은 후보에 남음")

    engine2 = HubEngine(specialty_matcher=_Matcher())
    engine2.update_hospital_info(_hospital("H1", 37.5675))
    engine2.update_hospital_info(_hospital("H2", 37.5745))
    engine2.process_voice_summary(_voice("s1", 2, "심근경색"), SCENE)
    _reject(engine2, "s1", "H1", "NO_EQUIPMENT")
    stemi = engine2.process_voice_summary(_voice("s2", 2, "심근경색"), SCENE)
    assert [h.hospitalId for h in stemi.hospitals] == ["H2", "H1"]
    assert "structural_refusal" in next(h for h in stemi.hospitals if h.hospitalId == "H1").demoteReasons
    other = engine2.process_voice_summary(_voice("s3", 2, "복통"), SCENE)
    assert other.hospitals[0].hospitalId == "H1", "다른 질환군 환자에겐 영향 없음"
    print("  [확인] 필요 장비 없음 거절 → 같은 질환군(심근경색)만 뒤로, 복통 환자는 그대로")


def test_bed_risk() -> None:
    print("=== ③ 병상 위험 등급 · 최종 확인 시각(발표 8장) ===")
    engine = HubEngine(specialty_matcher=_Matcher())
    now = datetime.now(timezone.utc)
    for hid, born_min, life_h in (("FRESH", 3, 6.0), ("OLD", 300, 0.5)):
        engine.update_hospital_info(_hospital(hid, 37.5680).model_copy(update={
            "updatedAt": (now - timedelta(minutes=2)).isoformat(),
            "bedReliability": BedReliabilityInput(predictedSurvivalSec=life_h * 3600, bornAt=(now - timedelta(minutes=born_min)).isoformat(),
                                                  authorityAtSend=1.0, ttlSec=600.0, modelTag="test")}))
    result = engine.process_voice_summary(_voice("r1", 2), SCENE)
    by = {h.hospitalId: h.bedReliability for h in result.hospitals}
    assert by["FRESH"].riskLevel == "low" and by["OLD"].riskLevel == "high", {k: v.rArrive for k, v in by.items()}
    assert by["FRESH"].checkedAt, "최종 확인 시각 = E-Gen 갱신 시각(병원 확인이 더 늦으면 그 시각)"
    print("  [확인] 막 바뀐 값 → 위험 낮음, 오래 버틴 값 → 위험 높음, 최종 확인 시각 표시")


if __name__ == "__main__":
    test_rule()
    test_engine()
    test_bed_risk()
    print("\n모든 검사 통과")
