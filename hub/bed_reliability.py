"""feature/info의 bedReliability(병상 정보 신뢰도 예측)를 매칭 시점 값으로 환산.

info의 reliability/(infosurv 서빙 모듈)는 병원마다 "예측 생존시간"
(predictedSurvivalSec)과 현재 claim-version의 탄생 시각(bornAt)을 보내준다.
authority(지금 믿어도 될 확률)는 정보의 나이에 따라 계속 떨어지는 값이라,
info가 전송 시점에 계산한 스냅샷(authorityAtSend)을 그대로 쓰면 재조회
주기(30분)만큼 낡는다 — 그래서 hub가 매칭 시점마다 여기서 재계산한다.

수식은 info 쪽 벤더링 사본(info/Hospital_inform/info/reliability/serve.py,
원본은 모델링 프로젝트 infosurv.serve)의 log-normal AFT 생존함수와 같다:

    S(t) = 1 − Φ((ln t − ln m)/σ),  σ=1 (모델의 aft_loss_distribution_scale)
    authority(a) = S(a)
    r_arrive(a, h) = S(a + h)        h = 도착까지 걸릴 시간
    ttl(a) = m·exp(σ·Φ⁻¹(1−θ)) − a   authority가 θ 아래로 떨어질 때까지

hub는 브랜치 폴더 원칙상 info/를 import할 수 없어 수식을 표준 라이브러리
(math.erfc, statistics.NormalDist)로 따로 들고 있다 — scipy 의존을 새로
얹지 않기 위한 선택이고, 두 구현의 수치 등가성(오차 < 1e-9)은 info 쪽
`python -m reliability.selftest` 3번 항목이 검증한다.

이 값은 순위(finalScore)에 관여하지 않는 설명용 필드다 — ReliabilityInfo
(assessment 기반)와 같은 원칙. 캘리브레이트된 확률이라 랭킹 가중치로
승격할 근거는 있지만(AIROOKIE-EGEN.md §5-1), 실측 로그로 효과를 확인하기
전까지는 노출만 한다.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import NormalDist

from schema import BedReliabilityInput, BedReliabilityMatch

#: 모델 학습 파라미터(aft_loss_distribution_scale=1)와 일치해야 한다.
SIGMA = 1.0

#: ttlSec의 authority 임계 — info 쪽 engine.AUTHORITY_TTL_THRESHOLD와 같은 값.
AUTHORITY_TTL_THRESHOLD = 0.8

#: r_arrive의 도착 시간(horizon) 추정에 쓰는 구급차 시내 평균 속도.
#: 실시간 교통을 반영하는 값이 아니라 "지금이 아니라 도착했을 때"라는
#: 시점 이동을 근사하기 위한 상수다 — 카카오내비 연동 등으로 실제 ETA를
#: 얻게 되면 그 값으로 대체한다.
AVG_AMBULANCE_SPEED_KMH = 40.0

_SQRT2 = math.sqrt(2.0)
_NORMAL = NormalDist()


def survival(pred_t_sec: float, t_sec: float, sigma: float = SIGMA) -> float:
    """log-normal AFT의 S(t) = 1 − Φ((ln t − ln m)/σ). Φ의 보생존은
    math.erfc로 계산한다 (norm.sf(x) = erfc(x/√2)/2)."""
    t = max(t_sec, 1e-12)
    m = max(pred_t_sec, 1e-12)
    return 0.5 * math.erfc((math.log(t) - math.log(m)) / (sigma * _SQRT2))


def ttl_sec(
    pred_t_sec: float, age_sec: float, threshold: float = AUTHORITY_TTL_THRESHOLD
) -> float:
    """authority가 threshold 아래로 떨어질 때까지 남은 초. 이미 아래면 0."""
    thr = min(max(threshold, 1e-12), 1.0 - 1e-12)
    t_hit = max(pred_t_sec, 1e-12) * math.exp(SIGMA * _NORMAL.inv_cdf(1.0 - thr))
    return max(t_hit - age_sec, 0.0)


def _parse_born_at(born_at: str) -> datetime:
    born = datetime.fromisoformat(born_at.replace("Z", "+00:00"))
    if born.tzinfo is None:
        born = born.replace(tzinfo=timezone.utc)
    return born


def evaluate(
    bed_reliability: BedReliabilityInput | None,
    distance_km: float,
    now: datetime | None = None,
) -> BedReliabilityMatch | None:
    """info가 보낸 예측을 매칭 시점의 authority/r_arrive로 환산한다.

    bedReliability를 안 보내는 병원(모델 미연동 구 데이터)이면 None —
    dashboard는 이 경우 해당 표시를 안 하면 된다(reliability와 같은 패턴).
    """
    if bed_reliability is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    born = _parse_born_at(bed_reliability.bornAt)
    age = max((now - born).total_seconds(), 0.0)
    horizon = distance_km / AVG_AMBULANCE_SPEED_KMH * 3600.0
    pred_t = bed_reliability.predictedSurvivalSec
    return BedReliabilityMatch(
        authority=round(survival(pred_t, age), 4),
        rArrive=round(survival(pred_t, age + horizon), 4),
        horizonSec=round(horizon, 1),
        ttlSec=round(ttl_sec(pred_t, age), 1),
        modelTag=bed_reliability.modelTag,
    )
