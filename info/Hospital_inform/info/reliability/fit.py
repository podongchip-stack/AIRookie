# >>> 벤더링 사본 — 원본: C:\Dev\Info_Survival\infosurv\fit.py (infosurv 0.2.0, 2026-09-28 복사)
# >>> 수정 금지. 원본이 갱신되면 통째로 재복사할 것 (serve.py와 같은 규약).
"""정보 생존 프레임워크 — 표준 학습과 필수 ablation.

기준 모델은 **XGBoost AFT로 확정**돼 있다(README §5). 이유 세 가지:

1. **검열을 손실함수가 직접 수용한다.** 라벨이 "30분"이 아니라 "20~40분
   사이"(구간검열)나 "3시간 이상"(우측검열) 형태인데 그대로 받는다
2. 표 형태 + 수만~수백만 행에서 안정적이다
3. `log T = βᵀx + σε` 구조라 **전이를 분해해 설명할 수 있다**

실측이 이 선택을 뒷받침한다(§5-7): Cox PH는 심각 오류 영역에서 **C 0.284로
역방향 붕괴**(선형·단조 제약이 비단조 구조를 못 담음), RSF는 15만 행에 55분+로
규모 실격. XGB AFT가 양 θ 최고였다.

## 필수 ablation — 이걸 안 하면 연구가 성립하지 않는다

**"나이 ÷ 평소 갱신 간격"만 쓴 모델과 반드시 비교한다.** 행동 피처가 그보다
의미 있게 좋아야 한다(README §9의 최대 위험). 실측: 버스에서 FULL − INTERVAL
= **+0.43**(INTERVAL은 사실상 무작위 0.51)이었으나 병상에서는 **+0.04~0.09**로
작았다 — 도메인마다 다르므로 매번 확인해야 한다.
"""
import numpy as np

__all__ = ["PARAMS", "train", "ablation"]

#: 확정된 표준 설정 (전 도메인 공통). 바꾸려면 §5-7 비교를 다시 할 것.
PARAMS = {
    "objective": "survival:aft",
    "eval_metric": "aft-nloglik",
    "aft_loss_distribution": "normal",
    "aft_loss_distribution_scale": 1.0,     # σ. serve/evaluate와 반드시 일치
    "tree_method": "hist",
    "max_depth": 8,
    "eta": 0.1,
    "min_child_weight": 50,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "seed": 42,
}
#: 필수 baseline — "나이 ÷ 평소 갱신 간격" 수렴 리스크를 재는 최소 피처
INTERVAL_ONLY = ["mean_interval_so_far", "prev_lifetime"]


def _dmatrix(X, lower, upper, weight=None):
    import xgboost as xgb
    m = xgb.DMatrix(X, weight=weight, missing=np.nan)
    m.set_float_info("label_lower_bound", np.asarray(lower, dtype=float))
    m.set_float_info("label_upper_bound",
                     np.where(np.isfinite(upper), upper, np.inf))
    return m


def train(X_tr, lower_tr, upper_tr, X_te, lower_te, upper_te, *,
          w_tr=None, w_te=None, rounds=300, early_stop=30, params=None,
          pretrained=None, **kw):
    """표준 AFT 학습. `pretrained`를 주면 **파인튜닝**(부스팅 이어가기)이다.

    ⚠ 파인튜닝은 **조건부로만** 작동한다(§5-17): ① 학습 시점에 시간척도를
    무차원화(τ)해야 하고 ② 타깃 도메인의 행동→생존 **부호가 사전학습 풀과
    같아야** 한다. 부호가 반대면 역방향에 고착되어 zero-shot보다 위험하다
    (버스 C 0.22~0.24, 라벨 5,000개를 넣어도 안 고쳐짐). 붙이기 전에
    `infosurv.gate.check`로 판정할 것."""
    import xgboost as xgb
    pr = dict(PARAMS, **(params or {}))
    dtr = _dmatrix(X_tr, lower_tr, upper_tr, w_tr)
    dte = _dmatrix(X_te, lower_te, upper_te, w_te)
    return xgb.train(pr, dtr, num_boost_round=rounds,
                     evals=[(dte, "test")], early_stopping_rounds=early_stop,
                     xgb_model=pretrained, verbose_eval=False, **kw)


def predict(bst, X):
    """예측 생존시간. `serve.authority` 등에 그대로 넣는다."""
    import xgboost as xgb
    return bst.predict(xgb.DMatrix(X, missing=np.nan),
                       iteration_range=(0, bst.best_iteration + 1))


def ablation(X_tr, lower_tr, upper_tr, X_te, lower_te, upper_te,
             t_obs_te, event_te, *, sets=None, **kw):
    """**필수 ablation**을 돌려 {이름: C-index}를 돌려준다.

    기본은 FULL vs INTERVAL — `FULL − INTERVAL`이 0에 가까우면 모델이 사실상
    "나이 ÷ 갱신간격"으로 수렴한 것이라 연구가 성립하지 않는다(README §9).
    옵션 피처(horizon 등)가 있으면 기계결합을 의심해 그것만 뺀 세트도 넣어
    비교할 것 — 버스 θ60에서 HORIZON_ONLY가 0.849였다(§5-1)."""
    from .evaluate import cindex
    sets = sets or {"FULL": list(X_tr.columns), "INTERVAL": INTERVAL_ONLY}
    out = {}
    for name, cols in sets.items():
        cols = [c for c in cols if c in X_tr.columns]
        bst = train(X_tr[cols], lower_tr, upper_tr,
                    X_te[cols], lower_te, upper_te, **kw)
        out[name] = cindex(t_obs_te, event_te, predict(bst, X_te[cols]))
    if "FULL" in out and "INTERVAL" in out:
        out["FULL_minus_INTERVAL"] = out["FULL"] - out["INTERVAL"]
    return out
