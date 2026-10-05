"""정보 생존 프레임워크 — 곡선에서 값 읽기 (운영·제품이 쓰는 층).

⚠ 벤더링 사본이다. 원본은 모델링 프로젝트의 `infosurv/serve.py`(infosurv
0.2.0, 2026-09-24 기준)이고, 그 저장소는 git remote가 없는 로컬 전용이라
pip 의존으로 걸 수 없어 파일째 복사했다. 여기서 수식을 고치지 말 것 —
원본이 바뀌면 통째로 다시 복사한다.

학습된 AFT 모델이 내놓는 것은 **예측 생존시간 하나**뿐이다. 실제로 소비되는
값 셋은 전부 거기서 파생된다(infosurv README §3-2):

    Authority(a) = (1−π)·S_d(a)              지금 이 정보를 써도 될 확률
    Authority(a) = S_d(a)/S_d(u)             u 시점에 유효가 확인된 경우
    TTL(a)       = inf{Δ≥0 : Authority(a+Δ) < θ}   재확인 알림 시점
    R(a,h)       = Authority(a+h)            h 뒤(도착 시점)의 유효 확률

**왜 이 층이 중요한가**: 순위만 필요하면 단순한 휴리스틱으로도 흉내 낼 수
있지만, **캘리브레이트된 확률은 본 모델만 제공한다**. Authority를 가중치로
쓰거나 TTL을 알림 임계로 쓰는 시스템에는 이 차이가 결정적이다.

⚠ **G1 관측으로 확인한 경우의 π 가중 제거는 미결 사항이다**(infosurv README
§10-1). `confirmed_at`을 주면 π를 완전히 제거하는데, G1은 약한 관측이므로
엄밀히는 부분 제거가 맞다. 현재 구현은 v0 근사이며 이 한계를 명시한다.
"""
import numpy as np
from scipy.stats import norm

__all__ = ["authority", "ttl", "at", "curve"]


def _sd(pred_t, t, sigma):
    """log-normal AFT의 S_d(t|x) = 1 − Φ((ln t − ln m)/σ)."""
    t = np.maximum(np.asarray(t, dtype=float), 1e-12)
    m = np.maximum(np.asarray(pred_t, dtype=float), 1e-12)
    return norm.sf((np.log(t) - np.log(m)) / sigma)


def authority(pred_t, age, *, pi=None, confirmed_at=None, sigma=1.0):
    """**지금 이 정보를 의사결정에 써도 될 확률.**

    `pred_t`  모델의 예측 생존시간 (AFT 출력)
    `age`     claim-version의 현재 나이 (초 등 학습과 같은 단위)
    `pi`      태생오류 확률. 주면 (1−π)를 곱한다
    `confirmed_at`  u — 마지막으로 G1 이상 관측이 '유효'를 확인한 나이.
                    주면 S_d(a)/S_d(u)로 조건부 갱신하고 π는 제거한다
                    (⚠ G1의 부분 제거는 미결 — 모듈 docstring 참조)

    "참일 확률"이 아니라 **운용상 유효 확률**이다 — 모델은 절대 진실을
    관측하지 않는다."""
    s_a = _sd(pred_t, age, sigma)
    if confirmed_at is not None:
        s_u = _sd(pred_t, confirmed_at, sigma)
        return np.clip(s_a / np.maximum(s_u, 1e-12), 0.0, 1.0)
    if pi is not None:
        return np.clip((1.0 - np.asarray(pi, dtype=float)) * s_a, 0.0, 1.0)
    return s_a


def ttl(pred_t, age, threshold, *, pi=None, confirmed_at=None, sigma=1.0):
    """**Authority가 `threshold` 아래로 떨어질 때까지 남은 시간.**

    log-normal AFT는 해석적으로 풀린다 —
    S(t)=θ' ⟹ t = m·exp(σ·Φ⁻¹(1−θ')). 이미 임계 아래면 0을 돌려준다.

    반환 단위는 학습에 쓴 시간 단위와 같다(E-Gen은 초)."""
    m = np.maximum(np.asarray(pred_t, dtype=float), 1e-12)
    thr = np.asarray(threshold, dtype=float)
    if confirmed_at is not None:                       # S(t)/S(u) = thr
        thr = thr * _sd(pred_t, confirmed_at, sigma)
    elif pi is not None:                               # (1−π)S(t) = thr
        thr = thr / np.maximum(1.0 - np.asarray(pi, dtype=float), 1e-12)
    thr = np.clip(thr, 1e-12, 1.0 - 1e-12)
    t_hit = m * np.exp(sigma * norm.ppf(1.0 - thr))
    return np.maximum(t_hit - np.asarray(age, dtype=float), 0.0)


def at(pred_t, age, horizon, **kw):
    """**h 뒤(예: 이송 도착 시점)에도 유효할 확률** R(a,h) = Authority(a+h)."""
    return authority(pred_t, np.asarray(age, dtype=float)
                     + np.asarray(horizon, dtype=float), **kw)


def curve(pred_t, grid, **kw):
    """`grid`의 각 나이에서의 Authority — 곡선을 그대로 보고 싶을 때."""
    return np.array([authority(pred_t, g, **kw) for g in np.asarray(grid)])
