"""spider 매칭 규칙(2026-10-15, spider_rule.py)이 hub 순위에 들어갔는지 — 임베딩 모델·카카오 없이.

확인하는 것:
  1) 줄 길이 식 — KTAS 2는 상급 병원으로 더 멀리(μ), 경증은 센터를 피함(−λ), 역량이 0.75 넘게 모자라면 줄 없음(뒤로)
  2) 질환군 벽 — 심근경색은 혈관조영 운영 병원만 줄(없는 병원은 뒤로, 후보에서 빼지는 않음)
  3) τ 창은 **표시만** — 같은 병원·같은 창에 한도(2)를 넘어도 건너뛰지 않고, 더 위급한 사건이 들어와도 양보가 없다
     (2026-10-22에 충돌·양보를 순위에서 걷어냈다 — spider_rule.py 모듈 설명 ⚠ · poc/CLINICAL_CONVERGENCE.md §3)
  4) 미선택 병원 통보 — 이송이 확정되면 승인했지만 선택 안 된 병원에 notSelected가 서고, 재선택하면 뒤바뀐다
실행: python test_spider_rule.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ.setdefault("HUB_SPIDER_HOUR", "14")  # spider 야간 감점이 검사 시각에 따라 바뀌지 않게(map.html 기본 14시)
os.environ.setdefault("HUB_DECISION_LOG_PATH", str(Path(_TMP.name) / "decision_log.jsonl"))
os.environ.setdefault("HUB_STATE_PATH", str(Path(_TMP.name) / "hub_state.json"))

import spider_rule  # noqa: E402
from hub_engine import HubEngine  # noqa: E402
from schema import (  # noqa: E402
    ApprovalAction, GpsPoint, HospitalInfo, Specialty, VoiceCallSummaryMessage, VoiceSummary, VoiceTranscript,
)

SCENE = GpsPoint(lat=37.5665, lng=126.9780)


class _FakeMatcher:
    def match_many(self, text, department_lists):
        return [(depts[0], 0.5) if depts else (None, 0.0) for depts in department_lists]


def _hospital(hpid: str, lat: float, level: str, em: int = 5, angio: str | None = None) -> HospitalInfo:
    return HospitalInfo(
        hospitalId=hpid, name=f"[테스트] {hpid}", gps=GpsPoint(lat=lat, lng=126.9780),
        availableBedCount=10, nightDutyAvailable=True,
        specialties=[Specialty(department="응급의학과", doctorCount=em)],
        updatedAt="2026-10-15T00:00:00Z", bedsByType={"ER_ADULT": 10}, emergencyLevel=level,
        equipmentOperating={"ANGIO": angio} if angio else None,
    )


def _voice(case_id: str, ktas: int, text: str = "복통") -> VoiceCallSummaryMessage:
    sev = {1: "high", 2: "high", 3: "medium"}.get(ktas, "low")
    return VoiceCallSummaryMessage(
        caseId=case_id, transcript=VoiceTranscript(raw_text="원문", filtered_text="원문"),
        summary=VoiceSummary(patient="50대", mechanism=text, symptoms=[], treatment=[], severity_tag=sev, ktas_level=ktas),
        source="ai",
    )


def _approval(case_id: str, hpid: str, action: str, actor: str) -> ApprovalAction:
    return ApprovalAction(
        caseId=case_id, action=action, hospital_id=hpid, actor=actor, timestamp="2026-10-22T05:00:00Z",
    )


def _top(result) -> str:
    return result.hospitals[0].hospitalId


def _gps(lat: float) -> GpsPoint:
    return GpsPoint(lat=lat, lng=126.9780)


def main() -> None:
    # ── 1) 줄 길이: 가까운 지역기관(L, 0.1km) vs 6km 권역(R) — KTAS 3은 μ 5분/레벨이라 센터까지 약 6분 더 갈 뿐 ──
    eng = HubEngine(specialty_matcher=_FakeMatcher())
    eng.update_hospital_info(_hospital("L", 37.5675, "지역응급의료기관"))
    eng.update_hospital_info(_hospital("R", 37.6200, "권역응급의료센터"))
    k3 = eng.process_voice_summary(_voice("k3", 3), SCENE, max_zone=3)
    k2 = eng.process_voice_summary(_voice("k2", 2), SCENE, max_zone=3)
    k4 = eng.process_voice_summary(_voice("k4", 4), SCENE, max_zone=3)
    by = {h.hospitalId: h for h in k2.hospitals}
    print(f"  K3 {[h.hospitalId for h in k3.hospitals]} / K2 {[h.hospitalId for h in k2.hospitals]} "
          f"(L 줄 {by['L'].spiderBlocked or by['L'].spiderLen}, R 줄 {by['R'].spiderLen}) / K4 {[h.hospitalId for h in k4.hospitals]}")
    assert _top(k3) == "L", "KTAS 3(필요 2)은 역량 딱 맞는 가까운 지역기관"
    assert _top(k2) == "R" and by["L"].spiderBlocked, "KTAS 2(필요 3)는 지역기관 역량이 1 모자라 줄 없음 → 권역"
    assert _top(k4) == "L" and {h.hospitalId: h for h in k4.hospitals}["R"].travelBonusMin < 0, "경증은 센터 보존(−λ)"
    print("ok — 줄 길이: K3 가까운 지역기관, K2 권역(지역기관 줄 없음), 경증 센터 회피")

    # ── 2) 질환군 벽: 심근경색은 혈관조영 운영 병원만 ──
    eng = HubEngine(specialty_matcher=_FakeMatcher())
    eng.update_hospital_info(_hospital("A0", 37.5675, "권역응급의료센터", angio="N"))
    eng.update_hospital_info(_hospital("A1", 37.5935, "권역응급의료센터", angio="Y"))
    mi = eng.process_voice_summary(_voice("mi", 2, "심장질환 · 흉통(심장성) · 경색 의심"), SCENE, max_zone=3)
    by = {h.hospitalId: h for h in mi.hospitals}
    assert _top(mi) == "A1" and by["A0"].spiderBlocked == "심근경색 벽", [h.hospitalId for h in mi.hospitals]
    assert len(mi.hospitals) == 2, "벽에 막혀도 후보에서 빼지 않는다"
    print("ok — 질환군 벽: 혈관조영 없는 가까운 센터는 뒤로(후보 유지)")

    # ── 3) τ 창은 표시만 한다(2026-10-22) — 한도가 차도 병원을 건너뛰지 않는다 ──
    # 예전엔 같은 창에 우선하는 사건이 한도(2)만큼 차면 그 병원을 건너뛰고 밀린 사건이 다음 병원(H2)으로
    # 줄을 옮겼다(양보). 실측(창 켜면 거절 증가)과 임상 자문("둘 다 받으려 노력한다")으로 걷어냈다 —
    # 지금은 spiderWindow에 사실만 싣고 수용 판단은 병원이 한다. 근거: poc/CLINICAL_CONVERGENCE.md §3
    eng = HubEngine(specialty_matcher=_FakeMatcher())
    eng.update_hospital_info(_hospital("H", 37.5700, "권역응급의료센터"))
    eng.update_hospital_info(_hospital("H2", 37.6000, "권역응급의료센터"))
    far = eng.process_voice_summary(_voice("far", 2), _gps(37.5300), max_zone=4)   # H까지 가장 멀다(늦게 닿음)
    mid = eng.process_voice_summary(_voice("mid", 2), _gps(37.5500), max_zone=4)
    near = eng.process_voice_summary(_voice("near", 2), _gps(37.5650), max_zone=4)
    assert _top(far) == _top(mid) == _top(near) == "H", "셋 다 줄이 가장 짧은 H"
    # app.py가 하는 것처럼 우선순위대로 다시 계산 — 창 표시는 맞춰지지만 1순위는 아무도 안 바뀐다
    order = eng.spider_priority_order(eng.get_active_case_ids())
    tops = {}
    for cid in order:
        r = eng.refresh_case(cid, {"far": _gps(37.5300), "mid": _gps(37.5500), "near": _gps(37.5650)}[cid])
        tops[cid] = _top(r if r is not None else eng.get_case_result(cid))
    far_h = {h.hospitalId: h for h in eng.get_case_result("far").hospitals}["H"]
    print(f"  재계산 순서 {order} → 1순위 {tops} · far의 H 창 {far_h.spiderWindow}")
    assert order == ["near", "mid", "far"], order
    assert tops == {"near": "H", "mid": "H", "far": "H"}, tops
    assert far_h.spiderWindow and len(far_h.spiderWindow) >= spider_rule.WINDOW_CAP, "창은 그대로 표시된다"
    assert any("순위 영향 없음" in r for r in far_h.bonusReasons), far_h.bonusReasons
    print("ok — τ 창: 한도가 차도 건너뛰지 않고(1순위 유지) 사실만 표시한다")

    # 더 위급한 사건이 들어와도 기존 사건의 줄을 빼앗지 않는다(우선순위 양보 없음)
    eng.process_voice_summary(_voice("crit", 1), _gps(37.5250), max_zone=4)
    order = eng.spider_priority_order(eng.get_active_case_ids())
    for cid in order:
        eng.refresh_case(cid, {"far": _gps(37.5300), "mid": _gps(37.5500), "near": _gps(37.5650), "crit": _gps(37.5250)}[cid])
    tops = {cid: _top(eng.get_case_result(cid)) for cid in order}
    print(f"  K1 추가 뒤 순서 {order} → 1순위 {tops}")
    assert order[0] == "crit" and tops["crit"] == "H", "KTAS 1이 먼저 계산된다(창 표시 순서)"
    assert all(tops[c] == "H" for c in ("near", "mid", "far")), "K1이 들어와도 K2가 밀려나지 않는다"
    print("ok — 우선순위 양보 없음: KTAS 1이 들어와도 기존 사건의 1순위가 그대로다")

    # ── 4) 미선택 병원 통보(2026-10-22): 확정되면 승인한 다른 병원에 notSelected가 선다 ──
    eng = HubEngine(specialty_matcher=_FakeMatcher())
    eng.update_hospital_info(_hospital("P1", 37.5700, "권역응급의료센터"))
    eng.update_hospital_info(_hospital("P2", 37.5750, "권역응급의료센터"))
    eng.process_voice_summary(_voice("sel", 2), _gps(37.5600), max_zone=4)
    for hid in ("P1", "P2"):
        eng.apply_approval_action(_approval("sel", hid, "hospital_approve", "hospital"))
    by = {h.hospitalId: h for h in eng.get_case_result("sel").hospitals}
    assert not by["P1"].notSelected and not by["P2"].notSelected, "확정 전에는 아무도 미선택이 아니다"
    eng.apply_approval_action(_approval("sel", "P1", "final_approval", "paramedic"))
    by = {h.hospitalId: h for h in eng.get_case_result("sel").hospitals}
    print(f"  확정 P1 → P1 {by['P1'].status}/미선택 {by['P1'].notSelected} · P2 {by['P2'].status}/미선택 {by['P2'].notSelected}")
    assert by["P1"].status == "confirmed" and not by["P1"].notSelected
    assert by["P2"].status == "approved" and by["P2"].notSelected, "승인했지만 선택 안 된 병원에 깃발"
    # 재선택으로 확정이 P2로 옮겨가면 깃발도 뒤바뀐다(승인 자체는 둘 다 유효하게 남는다)
    eng.apply_approval_action(_approval("sel", "P2", "final_approval", "paramedic"))
    by = {h.hospitalId: h for h in eng.get_case_result("sel").hospitals}
    print(f"  재선택 P2 → P1 {by['P1'].status}/미선택 {by['P1'].notSelected} · P2 {by['P2'].status}/미선택 {by['P2'].notSelected}")
    assert by["P2"].status == "confirmed" and not by["P2"].notSelected
    assert by["P1"].status == "approved" and by["P1"].notSelected
    print("ok — 미선택 통보: 확정되면 승인한 다른 병원에 깃발, 재선택하면 뒤바뀐다")
    print("\n전부 통과")


if __name__ == "__main__":
    main()
