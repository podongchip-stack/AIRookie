"""이송 중 활력징후 판정 규칙 엔진 (2.5단계, 2026-10-04) — 표준 라이브러리만, 순수 규칙 기반.

위험도 점수는 자체 기준을 만들지 않고 **공개 표준 NEWS2**(Royal College of Physicians,
National Early Warning Score 2, 2017)를 그대로 쓴다 — "그 숫자 어디서 났나"에 출처로
답하기 위해서다. 보조 지표로 쇼크지수(SI = 맥박/수축기혈압, ≥1.0 주의 — Allgöwer 1967,
외상·출혈 평가에 널리 쓰이는 공개 지표)를 쓴다. 행동은 아래 규칙표로 정한다
(hub/TRANSPORT_TRIAGE.md — 기준값은 전문의 검토 전 초안).

| 티어      | 조건                                                        | 행동(hub가 수행)        |
|-----------|-------------------------------------------------------------|-------------------------|
| record    | 기준 미달                                                   | 추세 기록만             |
| hold      | 기준 초과 1회째 (지속 미확인)                                | 경보 없음, 다음 측정 대기|
| notify    | 기준 초과 연속 PERSIST_COUNT회, 또는 NEWS2 ≥ 7 1회          | 확정 병원에 상태 변화 전달|
| review    | notify 조건 + 필요 치료 변화 신호(AVPU P/U, SpO2<85, SI≥1.3)| 대체 병원 후보 제안(사람 결정)|

"지속"을 시간이 아니라 **측정 횟수**로 정의한 이유: 이송 중 활력징후는 재통화·음성
입력이라 측정 간격이 불규칙해서, "10분간 지속" 같은 시간 기준은 측정이 한 번뿐이면
판정 불능이 된다. 예외로 NEWS2 ≥ 7(응급 대응 수준)은 다음 측정을 기다리는 비용이
더 커서 1회로 전달한다.

오경보 필터(시나리오 "일시적 튐"): 기준 초과 1회째는 hold로 묶어 두고, 다음 측정이
정상이면 record로 소거한다 — 설계 원칙 "오경보보다 침묵".

음성 추출 활력징후는 필드가 빠질 수 있다(혈압만 말하고 호흡수는 안 말하는 통화).
NEWS2는 **있는 항목만으로 부분 점수**를 내고 어떤 항목이 빠졌는지 함께 보고한다 —
부분 점수는 실제보다 낮게만 나올 수 있으므로(과소평가) 경보 방향으로는 안전하다.
산소 투여 여부는 수집 항목에 없어 실내 공기(0점)로 가정한다(초안 한계, 문서 명시).

헬기 권고는 이 엔진이 정하지 않는다 — review는 "대체가 필요하다"까지만 말하고,
시간 안에 갈 병원이 있는지는 매칭 정보를 가진 hub(app.py)가 판단한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SOURCE = "rule"

# ── 규칙표 상수 (전문의 검토 전 초안 — TRANSPORT_TRIAGE.md와 함께 바꾼다) ──────
PERSIST_COUNT = 2          # "지속" = 기준 초과 연속 측정 횟수
NEWS2_URGENT = 5           # NEWS2 5~6: 긴급 검토 수준 (RCP 2017 escalation threshold)
NEWS2_EMERGENCY = 7        # NEWS2 ≥7: 응급 대응 수준 — 1회로 전달
NEWS2_JUMP = 2             # 직전 측정 대비 급등 폭 — 절대값이 낮아도 추세 악화로 본다
SI_BREACH = 1.0            # 쇼크지수 주의선
SI_REVIEW = 1.3            # 쇼크지수 재검토선 (중증 출혈성 쇼크 의심)
SPO2_REVIEW = 85           # 이 미만이 지속되면 기도·호흡 치료 역량 재검토

TIERS = ("record", "hold", "notify", "review")


@dataclass(frozen=True)
class VitalObservation:
    """입력 구멍으로 들어오는 활력징후 1회 측정. 값이 없는 항목은 None.

    measured_at·source(voice/manual/monitor/demo)를 반드시 남긴다 — 활력징후도 병상
    정보처럼 출처마다 신뢰가 다르고 시간이 지나면 낡는 정보라서다(입력 구멍 원칙).
    """
    measured_at: str                 # ISO 8601
    source: str                      # "voice" | "manual" | "monitor" | "demo"
    rr: int | None = None            # 호흡수 (/분)
    spo2: int | None = None          # 산소포화도 (%)
    sbp: int | None = None           # 수축기혈압 (mmHg)
    hr: int | None = None            # 맥박 (/분)
    bt: float | None = None          # 체온 (℃)
    avpu: str | None = None          # "A" | "V" | "P" | "U"


# NEWS2 항목별 점수 (RCP 2017, Scale 1). (하한, 상한, 점수) — 상한 None은 무한대.
_NEWS2_BANDS: dict[str, list[tuple[float, float | None, int]]] = {
    "rr": [(0, 8, 3), (9, 11, 1), (12, 20, 0), (21, 24, 2), (25, None, 3)],
    "spo2": [(0, 91, 3), (92, 93, 2), (94, 95, 1), (96, None, 0)],
    "sbp": [(0, 90, 3), (91, 100, 2), (101, 110, 1), (111, 219, 0), (220, None, 3)],
    "hr": [(0, 40, 3), (41, 50, 1), (51, 90, 0), (91, 110, 1), (111, 130, 2), (131, None, 3)],
    "bt": [(0, 35.0, 3), (35.1, 36.0, 1), (36.1, 38.0, 0), (38.1, 39.0, 1), (39.1, None, 2)],
}


def _band_score(bands: list[tuple[float, float | None, int]], value: float) -> int:
    for low, high, score in bands:
        if value >= low and (high is None or value <= high):
            return score
    return 0


def news2_score(obs: VitalObservation) -> tuple[int, list[str], list[str]]:
    """(부분 점수, 점수에 들어간 항목, 빠진 항목). 의식은 A=0, V/P/U=3 (RCP 2017)."""
    total, present, missing = 0, [], []
    for name in ("rr", "spo2", "sbp", "hr", "bt"):
        value = getattr(obs, name)
        if value is None:
            missing.append(name)
            continue
        total += _band_score(_NEWS2_BANDS[name], float(value))
        present.append(name)
    if obs.avpu is None:
        missing.append("avpu")
    else:
        total += 0 if obs.avpu.upper() == "A" else 3
        present.append("avpu")
    return total, present, missing


def shock_index(obs: VitalObservation) -> float | None:
    if obs.hr is None or obs.sbp is None or obs.sbp <= 0:
        return None
    return round(obs.hr / obs.sbp, 2)


@dataclass
class Assessment:
    """측정 1회에 대한 판정 — 같은 입력 수열에는 항상 같은 결과가 나온다."""
    tier: str                        # record | hold | notify | review
    news2: int
    news2_params: list[str]          # 점수에 들어간 항목 (빠진 항목은 과소평가 방향)
    news2_missing: list[str]
    si: float | None
    reasons: list[str]               # 사람이 읽는 판정 근거 (dashboard 그대로 표시)
    consecutive_breach: int
    source: str = SOURCE


@dataclass
class TransportTriage:
    """사건(caseId) 하나의 이송 중 판정 상태. 측정이 올 때마다 evaluate()를 부른다."""
    history: list[tuple[VitalObservation, int]] = field(default_factory=list)  # (관측, NEWS2)
    consecutive_breach: int = 0
    notified: bool = False           # notify 이상을 이미 보냈는지 — hub가 중복 전송을 줄이는 데 참고

    def evaluate(self, obs: VitalObservation) -> Assessment:
        score, present, missing = news2_score(obs)
        si = shock_index(obs)
        prev_score = self.history[-1][1] if self.history else None
        reasons: list[str] = []

        # ── 기준 초과 판정 ──
        breach = False
        if score >= NEWS2_URGENT:
            breach = True
            reasons.append(f"NEWS2 {score}점(긴급 검토 기준 {NEWS2_URGENT} 이상)")
        if prev_score is not None and score - prev_score >= NEWS2_JUMP and score >= 1:
            breach = True
            reasons.append(f"NEWS2 급등 +{score - prev_score} (직전 {prev_score} → {score})")
        if si is not None and si >= SI_BREACH:
            breach = True
            reasons.append(f"쇼크지수 {si} (주의선 {SI_BREACH} 이상)")

        # ── 필요 치료 변화 신호 (notify를 review로 올리는 조건) ──
        review_signals: list[str] = []
        if obs.avpu is not None and obs.avpu.upper() in ("P", "U"):
            review_signals.append(f"의식 {obs.avpu.upper()} (통증 반응 이하)")
        if si is not None and si >= SI_REVIEW:
            review_signals.append(f"쇼크지수 {si} (재검토선 {SI_REVIEW} 이상)")
        if obs.spo2 is not None and obs.spo2 < SPO2_REVIEW and self.consecutive_breach >= 1:
            review_signals.append(f"SpO2 {obs.spo2}% 지속 (기준 {SPO2_REVIEW}% 미만)")

        # ── 티어 결정 ──
        if breach:
            self.consecutive_breach += 1
        else:
            if self.consecutive_breach == 1:
                reasons.append("직전 측정의 기준 초과가 이번 측정에서 정상화 — 일시적 튐으로 소거")
            self.consecutive_breach = 0

        if score >= NEWS2_EMERGENCY:
            # 응급 수준은 지속 확인 없이 즉시 — 다음 측정을 기다리는 비용이 더 크다
            reasons.append(f"NEWS2 {score}점(응급 대응 기준 {NEWS2_EMERGENCY} 이상) — 1회로 즉시 전달")
            tier = "review" if review_signals else "notify"
        elif breach and self.consecutive_breach >= PERSIST_COUNT:
            tier = "review" if review_signals else "notify"
        elif breach:
            tier = "hold"
            reasons.append(f"기준 초과 {self.consecutive_breach}회째 — 연속 {PERSIST_COUNT}회부터 전달(오경보 필터)")
        else:
            tier = "record"

        if tier == "review":
            reasons.extend(review_signals)
        if missing:
            reasons.append(f"미측정 항목 {len(missing)}개({', '.join(missing)}) 제외한 부분 점수 — 실제는 이보다 높을 수 있음")

        if tier in ("notify", "review"):
            self.notified = True
        self.history.append((obs, score))
        return Assessment(
            tier=tier, news2=score, news2_params=present, news2_missing=missing,
            si=si, reasons=reasons, consecutive_breach=self.consecutive_breach,
        )
