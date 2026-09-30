"""이동 시간·진료과 점수를 가중합해 병원 순위를 매긴다. 숫자 계산만 하는 순수 규칙 기반 모듈."""
from __future__ import annotations

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


def final_score(specialty_score: float, travel_min: float) -> float:
    return W_SPECIALTY * specialty_score + W_DISTANCE * travel_score(travel_min)


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
