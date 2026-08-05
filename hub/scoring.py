"""거리·진료과 점수를 가중합해 병원 순위를 매긴다. 숫자 계산만 하는 순수 규칙 기반 모듈."""
from __future__ import annotations

W_SPECIALTY = 0.6
W_DISTANCE = 0.4
MAX_SCORING_DISTANCE_KM = 20.0  # 이 거리 이상은 거리 점수 0으로 취급


def distance_score(distance_km: float, max_distance_km: float = MAX_SCORING_DISTANCE_KM) -> float:
    """가까울수록 1.0에 가깝고, max_distance_km 이상이면 0.0."""
    if distance_km >= max_distance_km:
        return 0.0
    return 1.0 - (distance_km / max_distance_km)


def final_score(specialty_score: float, distance_km: float) -> float:
    return W_SPECIALTY * specialty_score + W_DISTANCE * distance_score(distance_km)


def rank(hospitals: list[dict]) -> list[dict]:
    """hospitals의 각 원소는 최소한 finalScore/distanceKm/hospitalId 키를 가져야 한다.
    최종 점수 내림차순 → 동점이면 거리 오름차순 → 그마저 같으면 hospitalId 오름차순으로
    정렬해 결과가 항상 결정적(deterministic)이게 한다.
    """
    return sorted(hospitals, key=lambda h: (-h["finalScore"], h["distanceKm"], h["hospitalId"]))
