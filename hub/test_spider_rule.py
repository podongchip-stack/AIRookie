"""spider 매칭 규칙(2026-10-15, spider_rule.py)이 hub 순위에 들어갔는지 — 임베딩 모델·카카오 없이.

확인하는 것:
  1) 줄 길이 식 — KTAS 2는 상급 병원으로 더 멀리(μ), 경증은 센터를 피함(−λ), 역량이 0.75 넘게 모자라면 줄 없음(뒤로)
  2) 질환군 벽 — 심근경색은 혈관조영 운영 병원만 줄(없는 병원은 뒤로, 후보에서 빼지는 않음)
  3) τ 창 충돌·양보 — 같은 병원·같은 창에 한도(2)를 넘으면 덜 우선하는 사건(같은 KTAS면 늦게 닿는 쪽)이 다음 병원으로.
     더 우선하는 사건이 나중에 들어와도, 다시 계산하면 먼저 있던 덜 우선하는 사건이 양보한다
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
from schema import GpsPoint, HospitalInfo, Specialty, VoiceCallSummaryMessage, VoiceSummary, VoiceTranscript  # noqa: E402

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

    # ── 3) τ 창 충돌·양보: 같은 병원 H(가까움)·대안 H2(조금 멂), 같은 KTAS 2 세 사건 ──
    eng = HubEngine(specialty_matcher=_FakeMatcher())
    eng.update_hospital_info(_hospital("H", 37.5700, "권역응급의료센터"))
    eng.update_hospital_info(_hospital("H2", 37.6000, "권역응급의료센터"))
    far = eng.process_voice_summary(_voice("far", 2), _gps(37.5300), max_zone=4)   # H까지 가장 멀다(늦게 닿음) — 먼저 들어옴
    mid = eng.process_voice_summary(_voice("mid", 2), _gps(37.5500), max_zone=4)
    assert _top(far) == "H" and _top(mid) == "H", "둘까지는 한도(2) 안 — 같은 병원"
    near = eng.process_voice_summary(_voice("near", 2), _gps(37.5650), max_zone=4)  # 가장 먼저 닿는 사건이 나중에 들어옴
    assert _top(near) == "H", "먼저 닿는 사건은 덜 우선하는 사건들이 차지한 창을 신경 쓰지 않는다"
    # app.py가 하는 것처럼 우선순위대로 다시 계산 → 가장 늦게 닿는 far가 양보
    order = eng.spider_priority_order(eng.get_active_case_ids())
    tops = {}
    for cid in order:
        r = eng.refresh_case(cid, {"far": _gps(37.5300), "mid": _gps(37.5500), "near": _gps(37.5650)}[cid])
        tops[cid] = _top(r if r is not None else eng.get_case_result(cid))
    far_h = {h.hospitalId: h for h in eng.get_case_result("far").hospitals}["H"]
    print(f"  재계산 순서 {order} → 1순위 {tops} · far의 H 창 {far_h.spiderWindow}")
    assert order == ["near", "mid", "far"], order
    assert tops == {"near": "H", "mid": "H", "far": "H2"}, tops
    assert far_h.spiderWindow and len(far_h.spiderWindow) >= spider_rule.WINDOW_CAP
    print("ok — τ 창 충돌: 같은 KTAS 셋 중 가장 늦게 닿는 사건이 다음 병원으로 양보")

    # KTAS가 더 위급하면 늦게 닿아도 남는다
    eng.process_voice_summary(_voice("crit", 1), _gps(37.5250), max_zone=4)
    order = eng.spider_priority_order(eng.get_active_case_ids())
    for cid in order:
        eng.refresh_case(cid, {"far": _gps(37.5300), "mid": _gps(37.5500), "near": _gps(37.5650), "crit": _gps(37.5250)}[cid])
    tops = {cid: _top(eng.get_case_result(cid)) for cid in order}
    print(f"  K1 추가 뒤 순서 {order} → 1순위 {tops}")
    assert order[0] == "crit" and tops["crit"] == "H", "KTAS 1은 가장 늦게 닿아도 남는다"
    assert sum(1 for c in ("near", "mid", "far") if tops[c] == "H") == 1, "같은 창 한도 2 — K2 중 하나만 남는다"
    print("ok — 더 위급한(KTAS 1) 사건이 들어오면 KTAS 2가 양보")
    print("\n전부 통과")


if __name__ == "__main__":
    main()
