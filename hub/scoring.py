"""이동 시간·진료과 점수를 가중합해 병원 순위를 매긴다. 숫자 계산만 하는 순수 규칙 기반 모듈."""
from __future__ import annotations

import math
import statistics

W_SPECIALTY = 0.6
W_DISTANCE = 0.4

# 이동 시간 점수의 반감기(분). 이동 시간이 이만큼 늘 때마다 점수가 절반이 된다.
# 예전 거리 점수(1 - km/20, 20km 이상이면 0)는 20km 밖 병원끼리 거리 차이를 전혀 구분하지
# 못해, 반경 20km 안에 병원이 없는 지역에서는 순위가 진료과 점수로만 갈렸다(2026-09-28 수정).
# 반감기 방식은 0이 되지 않아 먼 병원끼리도 가까운 쪽이 앞선다. 15분은 "직선 10km를
# 기본 속도로 가는 시간"이라 기본 추정치 기준으로 10km에서 0.5가 되어 예전 곡선(10km → 0.5)과
# 가까운 거리에서는 거의 같다.
TRAVEL_HALF_LIFE_MIN = 15.0

# ETA가 하나도 없을 때(카카오 키 없음·전부 반경 10km 밖) 직선거리 1km당 소요 분.
# 1.5분/km = 직선 기준 시속 40km — bed_reliability.py가 예전부터 쓰던 가정과 같은 값이다.
DEFAULT_MIN_PER_KM = 1.5
# 분/km 보정에서 제외할 초근접 거리. 수백 m 안쪽은 출발·도착 고정 시간 때문에 비율이 튄다.
_CALIBRATION_MIN_KM = 0.5


def travel_score(travel_min: float, half_life_min: float = TRAVEL_HALF_LIFE_MIN) -> float:
    """가까울수록 1.0에 가깝고 이동 시간이 반감기만큼 늘 때마다 절반이 된다(0은 안 됨)."""
    return 0.5 ** (max(travel_min, 0.0) / half_life_min)


# ── 전문성·응급의료기관 등급 가산 (2026-10-01) ─────────────────────────────────────
# 가산은 점수에 더하지 않고 **"이동시간을 몇 분 줄여 준 것으로 친다"**로 환산한다. 점수에 더하면
# 같은 0.05점이 가까운 병원 사이에선 4분, 먼 병원 사이에선 20분의 가치가 되어 "전문성이 거리를
# 얼마나 이길 수 있나"가 거리에 따라 달라진다. 분 단위로 두면 불변식이 정확히 선다:
#   **가산을 다 받아도 MAX_BONUS_MIN분 넘게 먼 병원은 가까운 병원을 이길 수 없다**(같은 진료과 점수일 때).
# 값은 근거 데이터(실제 수용 결과)가 쌓이기 전의 보수적 초기값이다 — 거절 로그로 재보정한다.
DEPTH_BONUS_MAX_MIN = 3.0     # 매칭된 진료과 전문의가 많을수록 최대 3분
DEPTH_FULL_DOCTORS = 20       # 이 인원이면 최대치(log 스케일 — 1명→0.7분, 5명→1.8분, 20명→3분)
LEVEL_BONUS_MIN = {           # 중증(high) 환자에게만: 권역·지역응급의료센터의 최종치료 역량
    "권역응급의료센터": 5.0,
    "지역응급의료센터": 2.0,
}
MAX_BONUS_MIN = DEPTH_BONUS_MAX_MIN + max(LEVEL_BONUS_MIN.values())

# 경증 역가산 (2026-10-03): 경증(low) 환자에게는 권역·지역응급의료센터의 이동시간에
# 거꾸로 분을 **더한다** — "경증은 센터를 아껴라". 중증 가산의 거울상이다. 경증이
# 최근접이라는 이유만으로 센터의 마지막 병상을 차지하면, 뒤에 오는 중증 환자가 최종치료
# 가능한 곳에 못 들어간다(재난의료의 "경증은 멀리" 원칙의 시스템 구현). 제외가 아니라
# 순위 조정이라, 주변에 센터뿐이면 여전히 센터로 간다(뺑뺑이 방지 원칙 유지).
# 값은 팀 합의 초기값(2026-10-03, +3분) — 거절·도착 로그가 쌓이면 재보정한다.
MILD_CENTER_PENALTY_MIN = 3.0


def expertise_bonus_min(
    doctor_count: int | None, emergency_level: str | None, severity: str | None
) -> tuple[float, list[str]]:
    """(이동시간에서 뺄 분, 설명 문구들). 전문의 수·등급을 모르면 0분이다(불리하게 두지 않음).

    경증 역가산은 음수 가산으로 섞여 나간다 — final_score()가 (이동분 − 가산분)으로
    계산하므로 음수 가산 = 이동시간 증가이고, 기존 `travelBonusMin`·`bonusReasons`
    필드로 그대로 노출돼 dashboard 수정이 필요 없다.
    """
    bonus, reasons = 0.0, []
    if doctor_count:
        depth = min(1.0, math.log1p(doctor_count) / math.log1p(DEPTH_FULL_DOCTORS))
        minutes = round(DEPTH_BONUS_MAX_MIN * depth, 1)
        bonus += minutes
        reasons.append(f"전문의 {doctor_count}명 −{minutes}분")
    is_center = (emergency_level or "") in LEVEL_BONUS_MIN
    level_minutes = LEVEL_BONUS_MIN.get(emergency_level or "") if severity == "high" else None
    if level_minutes:
        bonus += level_minutes
        reasons.append(f"중증 · {emergency_level} −{level_minutes:g}분")
    elif severity == "low" and is_center:
        bonus -= MILD_CENTER_PENALTY_MIN
        reasons.append(f"경증 · {emergency_level} +{MILD_CENTER_PENALTY_MIN:g}분(센터 보존)")
    return bonus, reasons


# ── 이송 중 부하 페널티 (2026-10-03) ─────────────────────────────────────────────
# 같은 병원으로 이미 확정돼 이송 중인 환자(TTL 오버레이)가 많을수록, 그 병원의 이동시간에
# 분을 **더해** 순위를 뒤로 민다. 가산과 같은 '분' 통화라 불변식이 똑같이 선다:
#   **페널티를 다 받아도 LOAD_PENALTY_MAX_MIN분 넘게 가까운 병원이 역전당하지 않는다.**
# 평시(이송 중 0건)는 페널티 0이라 기존 순위와 완전히 같고, 대량사고처럼 확정이 연달아
# 쌓일 때만 작동한다 — beds_full(만실 절벽 강등)이 오기 **전에** 연속적으로 분산시키는
# 장치다. 예전엔 병상 20개 병원에 19명을 보내도 20번째 환자에게 1순위로 떴다.
LOAD_PENALTY_MAX_MIN = 10.0


def load_penalty_min(in_flight: int, effective_beds: int, bed_count_unknown: bool = False) -> tuple[float, str | None]:
    """(이동시간에 더할 분, 설명 문구). 압력 = 이송 중 / (이송 중 + 실질 가용).

    실질 가용은 오버레이 차감 후 값(effective_bed_count)을 받는다. 병상 미상이면 압력을
    정의할 수 없어 0분 — 미상을 이유로 불리하게 두지 않는 기존 원칙 그대로다.
    """
    if in_flight <= 0 or bed_count_unknown:
        return 0.0, None
    pressure = in_flight / (in_flight + max(effective_beds, 0))
    minutes = round(LOAD_PENALTY_MAX_MIN * pressure, 1)
    return minutes, f"이송 중 {in_flight}건/남은 병상 {max(effective_beds, 0)} +{minutes:g}분"


def final_score(
    specialty_score: float, travel_min: float, bonus_min: float = 0.0, load_min: float = 0.0
) -> float:
    return W_SPECIALTY * specialty_score + W_DISTANCE * travel_score(max(0.0, travel_min - bonus_min + load_min))


def calibrate_min_per_km(samples: list[tuple[float, float]]) -> float:
    """(직선 km, ETA 분) 쌍들로 이 사건의 "직선 1km당 실제 도로 소요 분"을 추정한다.

    ETA는 카카오 다중 목적지 API의 반경 10km 한도 때문에 가까운 병원만 받는다. 먼 병원은
    직선거리로 추정해야 하는데, 고정 속도를 쓰면 ETA를 받은 병원(실제 교통 반영)과 추정한
    병원이 서로 다른 잣대가 되어 먼 병원이 부당하게 유리해진다. 같은 사건에서 ETA를 받은
    병원들의 비율 중앙값을 쓰면 두 잣대가 맞춰진다. 표본이 없으면 기본값.
    """
    ratios = [eta_min / km for km, eta_min in samples if km >= _CALIBRATION_MIN_KM and eta_min > 0]
    return statistics.median(ratios) if ratios else DEFAULT_MIN_PER_KM


def rank_key(
    final: float,
    distance_km: float,
    hospital_id: str,
    demote_reasons: list[str] | tuple[str, ...] = (),
    status: str = "pending",
) -> tuple:
    """정렬 키. 앞 칸일수록 우선한다.

    0) 이 사건의 이송 확정(confirmed) 병원이 맨 앞, 그다음 병원이 승인(approved)한 병원
       (2026-10-01 — 예전엔 dashboard가 자체 정렬로 올려 줬다. 순위를 hub 한 곳에서만 정하도록
       옮겼다. 병원의 명시적 응답이 점수 추정보다 우선한다는 _demote_reasons()의 원칙과 같다)
    1) 이 사건에서 거절(rejected)한 병원은 맨 뒤
    2) 그 앞은 declared_no(수용 불가 신고)·beds_full(확인된 만실)로 내린 병원
    3) 나머지는 finalScore 내림차순, 같으면 가까운 순·ID 순(결정적 정렬)

    declared_no를 가중합으로 섞지 않는 이유: hospital_score의 5단계 score(0.2~1.0)는
    순서만 의미가 있는 값이라, 임의 비중을 곱해 거리·진료과 점수와 합치면 근거 없는
    정밀함을 만든다(실험상 안전을 보장하려면 신뢰도 가중치가 70%대까지 필요해 거리·진료과가
    사실상 무시됨). 만실도 같은 이유로 가중치 대신 순서로만 내린다. "제거하지 말고 아래로
    내릴 것"(hospital_score README) — 정보 자체는 안 버린다.
    """
    reasons = set(demote_reasons)
    if status == "confirmed":
        bucket = 0
    elif status == "approved":
        bucket = 1
    elif "rejected" in reasons:
        bucket = 4
    else:
        bucket = 3 if reasons else 2
    return (bucket, -final, distance_km, hospital_id)


def rank(hospitals: list[dict]) -> list[dict]:
    """hospitals의 각 원소는 finalScore/distanceKm/hospitalId 키를 가져야 한다.
    `demoteReasons`(없으면 빈 목록)로 뒤로 내린다. 예전 호출부 호환을 위해 `demote=True`도
    declared_no로 취급한다."""

    def _reasons(h: dict) -> list[str]:
        reasons = list(h.get("demoteReasons") or [])
        if h.get("demote") and "declared_no" not in reasons:
            reasons.append("declared_no")
        return reasons

    return sorted(
        hospitals,
        key=lambda h: rank_key(
            h["finalScore"], h["distanceKm"], h["hospitalId"], _reasons(h), h.get("status", "pending")
        ),
    )
