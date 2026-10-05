# >>> 벤더링 사본 — 원본: C:\Dev\Info_Survival\infosurv\evaluate.py (infosurv 0.2.0, 2026-09-28 복사)
# >>> 수정 금지. 원본이 갱신되면 통째로 재복사할 것 (serve.py와 같은 규약).
"""정보 생존 프레임워크 — 평가 지표 (도메인 중립).

이 모듈은 **어떤 도메인에도 그대로 이전되는 자산**이다(FINDINGS §5-18:
"범용인 것은 프레임워크·절차이고 가중치는 도메인 내부 한정"). 도메인 어댑터가
공통 스키마로 사상해 주기만 하면 아래 지표는 수정 없이 쓴다.

**지표 삼중화** (REPORT §4 검증 체계):
  - 판별력   `cindex`                      순위를 맞히는가
  - 종합     `ipcw_ibs`                    검열 보정 확률 예측 품질
  - 정직성   `dcal` · `calibration_table` · `binary_ece`   확률이 정직한가

⚠ **세 가지를 함께 봐야 한다** — 어느 하나로 대체되지 않는다:
  · 순위는 단순한 방법도 흉내 내지만 **캘리브레이트된 확률은 본 모델만**
    제공한다(§5-12: 출처 단위 shelf-life는 C 0.73 vs 0.76인데 D-cal은 300배 열세)
  · 반대로 **이벤트가 희소하면 IBS·D-cal이 역방향 모델을 놓친다**
    (§5-17: 버스 파인튜닝이 C 0.233(역방향)인데 IBS 0.00024·D-cal 0.00000으로
    완벽해 보였다). **게이트 판정은 반드시 C-index로 할 것**
"""
import numpy as np

__all__ = ["survival_prob", "cindex", "weighted_km", "km_eval", "ipcw_ibs",
           "dcal", "calibration_table", "binary_ece"]


def survival_prob(pred_t, t_star, sigma=1.0):
    """AFT-normal S(t*|x) = P(T > t*) = 1 − Φ((ln t* − ln pred_t)/σ)."""
    from scipy.stats import norm
    return norm.sf((np.log(t_star) - np.log(pred_t)) / sigma)


def cindex(t_obs, event, pred, n_pairs=400_000, seed=0):
    """Harrell C-index (쌍 샘플링 근사).

    0.5 = 무작위 · 1.0 = 완벽 · **0.0 = 완전히 거꾸로**.
    0.5 미만은 "신호 없음"이 아니라 **방향이 반대**라는 뜻이다(§5-17 버스 0.233).
    비교 가능 쌍이 없으면 nan을 돌려준다 — 소표본에서 조용히 0으로 나누던
    버그를 막기 위함(2026-09-21 수정)."""
    rng = np.random.default_rng(seed)
    ev_idx = np.flatnonzero(event)
    if len(ev_idx) == 0:
        return float("nan")
    i = rng.choice(ev_idx, n_pairs)
    j = rng.integers(0, len(t_obs), n_pairs)
    ok = t_obs[i] < t_obs[j]
    i, j = i[ok], j[ok]
    if len(i) == 0:
        return float("nan")
    conc = (pred[i] < pred[j]).sum() + 0.5 * (pred[i] == pred[j]).sum()
    return conc / len(i)


def weighted_km(t, event, w):
    """가중 Kaplan–Meier. 반환: (사건시각 오름차순, 해당 시각 직후 S값)."""
    order = np.argsort(t, kind="stable")
    t, event, w = t[order], event[order], w[order]
    at_risk = w.sum()
    times, surv = [], []
    s = 1.0
    i, n = 0, len(t)
    while i < n:
        j = i
        d = c = 0.0
        while j < n and t[j] == t[i]:
            if event[j]:
                d += w[j]
            else:
                c += w[j]
            j += 1
        if d > 0 and at_risk > 0:
            s *= max(0.0, 1.0 - d / at_risk)
            times.append(t[i])
            surv.append(s)
        at_risk -= d + c
        i = j
    return np.array(times), np.array(surv)


def km_eval(times, surv, q, before=False):
    """S(q) (before=True면 S(q⁻)) — 계단함수 조회."""
    if len(times) == 0:
        return np.ones_like(np.asarray(q, dtype=float))
    idx = np.searchsorted(times, q, side=("left" if before else "right"))
    out = np.ones_like(np.asarray(q, dtype=float))
    m = idx > 0
    out[m] = surv[idx[m] - 1]
    return out


def ipcw_ibs(surv_fn, t_obs, event, w, t_grid, g_floor=0.05):
    """IPCW Brier Score를 t_grid에서 사다리꼴 적분 (÷ 구간 길이).

    검열분포 G는 가중 KM, `g_floor`로 가중치 폭주 방지.
    `surv_fn(t)` → 각 표본의 S(t|x) 벡터.

    ⚠ 시간축이 무차원(τ 정규화)이면 **절대값을 다른 도메인·모드와 비교하면
    안 된다** — 같은 (도메인, 모드) 안의 모델 비교만 유효하다(§5-17 한계 6)."""
    ct, cs = weighted_km(t_obs, ~event, w)
    g_at_t = np.maximum(km_eval(ct, cs, t_grid), g_floor)
    g_at_ti = np.maximum(km_eval(ct, cs, t_obs, before=True), g_floor)
    bs = np.empty(len(t_grid))
    wsum = w.sum()
    for gi, tg in enumerate(t_grid):
        s = surv_fn(tg)
        died = event & (t_obs <= tg)
        alive = t_obs > tg
        term = (died * (s ** 2) / g_at_ti
                + alive * ((1.0 - s) ** 2) / g_at_t[gi])
        bs[gi] = float(np.sum(w * term) / wsum)
    return float(np.trapezoid(bs, t_grid) / (t_grid[-1] - t_grid[0]))


def dcal(surv_at_obs, event, w, bins=10):
    """Haider D-calibration. Σ(p_b − 1/bins)². 검열 행은 [0, S(c|x)]에 균등 분산."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    mass = np.zeros(bins)
    u = np.clip(surv_at_obs, 1e-12, 1.0)
    for b in range(bins):
        lo, hi = edges[b], edges[b + 1]
        in_bin = event & (u > lo) & (u <= hi)
        mass[b] += float(np.sum(w[in_bin]))
        cen = ~event
        overlap = np.clip(np.minimum(u[cen], hi) - lo, 0.0, None)
        mass[b] += float(np.sum(w[cen] * overlap / u[cen]))
    p_b = mass / mass.sum()
    return float(np.sum((p_b - 1.0 / bins) ** 2)), p_b.tolist()


def calibration_table(pred_t, y_lo, y_hi, w, t_star, sigma=1.0, bins=10):
    """t* 시점 생존확률 캘리브레이션.

    판정 가능한 행만 사용: lower ≥ t* → 생존(1), 이벤트이고 upper ≤ t* → 사망(0),
    그 외(구간이 t*에 걸침)는 제외. 반환: (사용비율, ECE, 분위별 표)."""
    p = survival_prob(pred_t, t_star, sigma)
    alive = y_lo >= t_star
    dead = np.isfinite(y_hi) & (y_hi <= t_star)
    use = alive | dead
    if use.sum() == 0:
        return 0.0, float("nan"), []
    p_u, obs_u, w_u = p[use], alive[use].astype(float), w[use]
    idx_bins = np.array_split(np.argsort(p_u), bins)
    rows, ece, wsum = [], 0.0, w_u.sum()
    for b in idx_bins:
        if len(b) == 0:
            continue
        wp = np.average(p_u[b], weights=w_u[b])
        wo = np.average(obs_u[b], weights=w_u[b])
        ece += (w_u[b].sum() / wsum) * abs(wp - wo)
        rows.append((wp, wo, len(b)))
    return use.mean(), ece, rows


def binary_ece(p, y, w, bins=10):
    """이진 확률 예측의 가중 ECE (확률 분위 bins등분). π(x) 평가용."""
    idx_bins = np.array_split(np.argsort(p), bins)
    rows, ece, wsum = [], 0.0, w.sum()
    for b in idx_bins:
        if len(b) == 0:
            continue
        wp = np.average(p[b], weights=w[b])
        wo = np.average(y[b], weights=w[b])
        ece += (w[b].sum() / wsum) * abs(wp - wo)
        rows.append((float(wp), float(wo), len(b)))
    return float(ece), rows
