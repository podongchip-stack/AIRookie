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
    `demote`가 있는 원소는 그 값이 True면 최종 점수와 무관하게 맨 뒤로 밀린다
    (없으면 False로 취급 — 기존 호출부와 하위 호환).

    demote는 hospital_score(assessment)의 관련 질환군이 `declared_no`(병원이
    명시적으로 "수용 불가"라고 신고)일 때 hub_engine.py가 계산해서 넘겨준다.
    이 값 자체는 finalScore 계산에 안 들어간다 — 가중합으로 섞으면 임계값
    검증 없이 임의 비중을 발명해야 하는 문제가 그대로 재현되기 때문이다
    (실험으로 확인: 완전히 안전하려면 신뢰도 가중치가 70%대까지 필요해서
    거리·진료과 반영이 사실상 무의미해짐 — 그럴 바엔 순서로 미는 편이 낫다).
    순위 안에서는 finalScore로 그대로 정렬해, "제거하지 말고 아래로 내릴
    것"(hospital_score README 권장)만 지키고 정보 자체는 안 버린다.
    """
    return sorted(
        hospitals,
        key=lambda h: (bool(h.get("demote", False)), -h["finalScore"], h["distanceKm"], h["hospitalId"]),
    )
