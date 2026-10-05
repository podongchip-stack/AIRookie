"""이송 중 판정 규칙 엔진 검증 — 시연 시나리오 5종이 그대로 픽스처다.

    python test_transport_triage.py

시나리오별 의도한 동작 일치율(검증 지표)을 코드로 고정한다: 같은 입력 수열에는
항상 같은 티어가 나와야 하고, 시연 당일에도 이 결과 그대로 재현된다.
"""
from __future__ import annotations

from transport_triage import TransportTriage, VitalObservation


def _obs(seq: int, **vitals) -> VitalObservation:
    return VitalObservation(measured_at=f"2026-10-04T10:{seq:02d}:00+09:00", source="demo", **vitals)


def run_sequence(observations: list[VitalObservation]) -> list[str]:
    triage = TransportTriage()
    return [triage.evaluate(o).tier for o in observations]


def test_scenario_1_stable() -> None:
    """안정적인 경증 — 전부 기록만, 알림 없음."""
    tiers = run_sequence([
        _obs(0, rr=16, spo2=98, sbp=120, hr=80, bt=36.5, avpu="A"),
        _obs(5, rr=15, spo2=98, sbp=118, hr=82, bt=36.6, avpu="A"),
        _obs(10, rr=16, spo2=97, sbp=121, hr=79, bt=36.5, avpu="A"),
    ])
    assert tiers == ["record", "record", "record"], tiers
    print(f"  시나리오1 안정 경증: {tiers} — 쓸데없이 알리지 않음 ✓")


def test_scenario_2_progressing_shock() -> None:
    """이송 중 쇼크 진행 — 지속 확인(연속 2회) 뒤 전달."""
    tiers = run_sequence([
        _obs(0, rr=18, spo2=97, sbp=115, hr=95, avpu="A"),    # NEWS2 2, SI 0.83 — 기록
        _obs(5, rr=20, spo2=96, sbp=100, hr=115, avpu="A"),   # SI 1.15 — 초과 1회째, 보류
        _obs(10, rr=20, spo2=96, sbp=98, hr=118, avpu="A"),   # SI 1.2 — 연속 2회, 전달
    ])
    assert tiers == ["record", "hold", "notify"], tiers
    print(f"  시나리오2 쇼크 진행: {tiers} — 연속 2회 확인 뒤 도착 병원에 전달 ✓")


def test_scenario_3_destination_mismatch() -> None:
    """흉통 악화 + 재검토 신호(쇼크지수 ≥ 1.3) — 대체 병원 제안 티어."""
    triage = TransportTriage()
    first = triage.evaluate(_obs(0, rr=22, spo2=94, sbp=100, hr=105, avpu="A"))   # NEWS2 6 — 보류
    second = triage.evaluate(_obs(5, rr=24, spo2=92, sbp=95, hr=130, avpu="A"))   # NEWS2 8 + SI 1.37
    assert first.tier == "hold", first.tier
    assert second.tier == "review", second.tier
    assert any("쇼크지수" in r for r in second.reasons), second.reasons
    print(f"  시나리오3 목적지 부적합: [hold, review] — 제안만, 결정은 사람 ✓")


def test_scenario_4_consciousness_drop() -> None:
    """의식 저하 — NEWS2 ≥ 7은 지속 확인 없이 1회로 즉시, AVPU P는 재검토 신호."""
    triage = TransportTriage()
    first = triage.evaluate(_obs(0, rr=14, spo2=96, sbp=125, hr=88, avpu="A"))
    second = triage.evaluate(_obs(5, rr=8, spo2=90, sbp=125, hr=88, avpu="P"))    # 3+3+3 = 9
    assert first.tier == "record"
    assert second.tier == "review", second.tier
    assert second.news2 >= 7, second.news2
    print(f"  시나리오4 의식 저하: NEWS2 {second.news2} — 1회로 즉시 재검토 티어 ✓")


def test_scenario_5_transient_spike() -> None:
    """측정값 일시적 튐 — 1회 초과는 보류, 다음 측정 정상이면 소거. 경보 없음."""
    triage = TransportTriage()
    tiers, assessments = [], []
    for obs in [
        _obs(0, rr=16, spo2=97, sbp=120, hr=85, avpu="A"),
        _obs(5, rr=16, spo2=97, sbp=110, hr=116, avpu="A"),   # SI 1.05 — 튐
        _obs(10, rr=16, spo2=97, sbp=120, hr=85, avpu="A"),   # 정상 복귀
    ]:
        a = triage.evaluate(obs)
        tiers.append(a.tier)
        assessments.append(a)
    assert tiers == ["record", "hold", "record"], tiers
    assert any("일시적 튐" in r for r in assessments[2].reasons), assessments[2].reasons
    assert not triage.notified, "튐만으로는 어떤 알림도 나가면 안 된다"
    print(f"  시나리오5 일시적 튐: {tiers} — 오경보 걸러냄 ✓")


def test_partial_vitals_from_voice() -> None:
    """음성 추출은 필드가 빠질 수 있다 — 있는 항목만으로 부분 점수, 빠진 항목 보고."""
    triage = TransportTriage()
    a = triage.evaluate(_obs(0, sbp=150, hr=110, spo2=96))    # 통화에서 혈압·맥박·SpO2만 말함
    assert a.news2_missing == ["rr", "bt", "avpu"], a.news2_missing
    assert any("부분 점수" in r for r in a.reasons), a.reasons
    print(f"  부분 활력징후: NEWS2 {a.news2} (빠짐 {a.news2_missing}) — 과소평가 방향으로만 안전 ✓")


def test_deterministic() -> None:
    """같은 입력 수열 → 같은 결과 (시연 고정성)."""
    seq = [
        _obs(0, rr=18, spo2=97, sbp=115, hr=95, avpu="A"),
        _obs(5, rr=20, spo2=96, sbp=100, hr=115, avpu="A"),
        _obs(10, rr=20, spo2=96, sbp=98, hr=118, avpu="A"),
    ]
    assert run_sequence(seq) == run_sequence(seq)
    print("  결정성: 같은 입력 수열에 같은 결과 ✓")


if __name__ == "__main__":
    print("[이송 중 판정 규칙 엔진]")
    test_scenario_1_stable()
    test_scenario_2_progressing_shock()
    test_scenario_3_destination_mismatch()
    test_scenario_4_consciousness_drop()
    test_scenario_5_transient_spike()
    test_partial_vitals_from_voice()
    test_deterministic()
    print("전부 통과")
