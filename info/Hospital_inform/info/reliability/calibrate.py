"""잔차 재보정 (μR, σR) 적합 CLI — 서빙 확률의 캘리브레이션 층.

    python -m reliability.calibrate                       # 기본: 09-23 이후 홀드아웃
    python -m reliability.calibrate --since 2026-10-23T00:00:00+09:00   # 재학습 후

왜 필요한가 — 모델의 raw 생존확률은 순위(판별)는 정직하지만, "도착 시점에도
유효할 확률 82%"처럼 **숫자를 문자 그대로 소비**하는 결정 프레이밍에서는
뒤틀림이 실측됐다(연구 DCA 실험: raw ECE 0.083 → 재보정 후 0.020). 화면에
%를 노출하기 전에 이 층이 전제다. 방법은 연구 쪽 §5-44가 확립한 잔차 재보정:
예측 생존시간 m을 위치로 둔 로그정규를 홀드아웃에 다시 적합해 전역 상수
2개(μR: 시간 스케일 보정, σR: 분포 폭 보정)를 얻는다.

    S_recal(t) = 1 − Φ((ln t − (ln m + μR)) / σR)

적합 데이터는 **모델 학습 창 이후의 스냅샷**만 쓴다(누수 방지 — 서빙 모델
ext0923은 2026-09-22까지의 데이터로 학습됨). 라벨 의미는 학습 파이프라인과
동일: θ=3(3병상 이상 어긋나면 무효화=EVENT, 구간검열), θ 미만 잔변화·관측
공백·창 끝은 우측검열. 검열을 무시하면 수명이 짧은 쪽으로 편향된다.

산출물 `model/recalibration.json`은 서빙이 기동 시 읽어 적용한다(engine.py).
없으면 raw로 동작 — fail-soft. 월 1회 모델 재학습 시 --since를 새 경계로
바꿔 같이 재적합할 것.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.stats import norm

from .engine import _BED_OP, _DEFAULT_GAP_TABLE, _DEFAULT_MODEL, _DEFAULT_SNAPSHOT_DIR
from .features import FEATURES, SEGMENT_GAP_SEC

#: 학습 파이프라인과 동일한 무효화 임계 (서빙 모델 aft_egen_theta3과 짝)
THETA = 3

#: 서빙 모델(ext0923)의 학습 데이터 상한 다음 날 00시 KST — 홀드아웃 시작 기본값
DEFAULT_SINCE = "2026-09-23T00:00:00+09:00"

_RECAL_PATH = Path(__file__).resolve().parent / "model" / "recalibration.json"

#: ECE 평가 지평(초). 30분 = DCA 실험의 주 지평이자 재조회 주기의 절반
ECE_TAU_SEC = 1800.0


@dataclass
class Version:
    features: list[float]
    #: EVENT면 (lo, hi] 구간검열 나이(초), CENSOR면 (c, None)
    lo: float
    hi: float | None
    event: bool


def build_versions(snapshot_dir: Path, gap_by_hpid: dict[str, float], gap_national: float,
                   since_utc: datetime) -> list[Version]:
    """스냅샷에서 claim-version + FULL9 피처 + θ3 라벨을 재구성한다.

    features.py의 실시간 규칙과 같은 의미를 배치로 재현한다 — 값 변화=새 버전,
    공백 1h=세그먼트 분리, 첫 버전 리듬 피처 NaN, 시각 피처 UTC.
    """
    # hpid -> (last_obs, last_val, prev_obs_of_current_value 아님 — 아래 참조)
    state: dict[str, tuple[datetime, int]] = {}
    seg: dict[str, tuple[datetime, int, datetime, float, float]] = {}
    # seg[hpid] = (first_born, version_no, born, prev_lifetime, delta)
    open_versions: dict[str, Version] = {}  # 아직 라벨이 안 정해진 현재 버전
    done: list[Version] = []

    def close(hpid: str, lo: float, hi: float | None, event: bool) -> None:
        v = open_versions.pop(hpid, None)
        if v is None:
            return
        v.lo, v.hi, v.event = max(lo, 0.0), hi, event
        if v.hi is not None and v.hi <= 0:
            return  # 태어나자마자 기록 종료 — 정보 없음
        if v.hi is None and v.lo <= 0:
            return
        done.append(v)

    def open_version(hpid: str, ts: datetime, version_no: int, first_born: datetime,
                     prev_lifetime: float, delta: float) -> None:
        if ts < since_utc:
            open_versions.pop(hpid, None)  # 홀드아웃 이전 탄생 — 적합에서 제외
            return
        t_since = (ts - first_born).total_seconds()
        mean_interval = t_since / (version_no - 1) if version_no > 1 else math.nan
        open_versions[hpid] = Version(
            features=[
                float(version_no), t_since, prev_lifetime, mean_interval,
                math.nan, delta, float(ts.hour), float(ts.isoweekday()),
                gap_by_hpid.get(hpid, gap_national),
            ],
            lo=0.0, hi=None, event=False,
        )

    for path in sorted(snapshot_dir.glob("*.jsonl")):
        with path.open("rb") as f:
            for raw_line in f:
                try:
                    rec = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if rec.get("operation") != _BED_OP or "error" in rec:
                    continue
                ts = datetime.fromisoformat(rec["ts"]).astimezone(timezone.utc)
                for item in rec.get("items") or []:
                    hpid = (item.get("hpid") or "").strip()
                    raw = item.get("hvec")
                    if not hpid or raw is None or str(raw).strip() == "":
                        continue
                    try:
                        value = int(str(raw).strip())
                    except ValueError:
                        continue
                    prev = state.get(hpid)
                    if prev is None or (ts - prev[0]).total_seconds() > SEGMENT_GAP_SEC:
                        # 공백 — 진행 중이던 버전은 마지막 관측에서 우측검열
                        if prev is not None and hpid in open_versions and hpid in seg:
                            born = seg[hpid][2]
                            close(hpid, (prev[0] - born).total_seconds(), None, False)
                        else:
                            open_versions.pop(hpid, None)
                        seg[hpid] = (ts, 1, ts, math.nan, math.nan)
                        open_version(hpid, ts, 1, ts, math.nan, math.nan)
                        state[hpid] = (ts, value)
                        continue
                    last_obs, last_val = prev
                    if ts <= last_obs:
                        continue
                    if value != last_val:
                        first_born, version_no, born, _, _ = seg[hpid]
                        delta = abs(value - last_val)
                        age_lo = (last_obs - born).total_seconds()
                        age_hi = (ts - born).total_seconds()
                        if delta >= THETA:
                            close(hpid, age_lo, age_hi, True)   # EVENT, 구간검열
                        else:
                            close(hpid, age_lo, None, False)    # 교체 — 우측검열
                        prev_lifetime = age_hi
                        seg[hpid] = (first_born, version_no + 1, ts, prev_lifetime, float(delta))
                        open_version(hpid, ts, version_no + 1, first_born, prev_lifetime, float(delta))
                    state[hpid] = (ts, value)

    # 데이터 끝 — 진행 중 버전은 마지막 관측에서 우측검열
    for hpid in list(open_versions):
        if hpid in seg and hpid in state:
            born = seg[hpid][2]
            close(hpid, (state[hpid][0] - born).total_seconds(), None, False)
    return done


def fit_residual(pred_t: np.ndarray, versions: list[Version]) -> tuple[float, float]:
    """검열 로그정규 잔차 MLE — 위치 ln m + μR, 척도 σR."""
    log_m = np.log(np.maximum(pred_t, 1e-12))
    lo = np.array([v.lo for v in versions])
    hi = np.array([v.hi if v.hi is not None else np.nan for v in versions])
    event = np.array([v.event for v in versions])

    def nll(params: np.ndarray) -> float:
        mu, log_sigma = params
        sigma = math.exp(log_sigma)
        loc = log_m + mu

        def surv(t: np.ndarray, loc_subset: np.ndarray) -> np.ndarray:
            with np.errstate(divide="ignore"):
                z = (np.log(np.maximum(t, 1e-12)) - loc_subset) / sigma
            return np.where(t <= 0, 1.0, norm.sf(z))

        ev = event
        ll_event = np.log(np.maximum(surv(lo[ev], loc[ev]) - surv(hi[ev], loc[ev]), 1e-300))
        ll_censor = np.log(np.maximum(surv(lo[~ev], loc[~ev]), 1e-300))
        return -float(ll_event.sum() + ll_censor.sum())

    result = minimize(nll, x0=np.array([0.0, 0.0]), method="Nelder-Mead",
                      options={"xatol": 1e-4, "fatol": 1e-3, "maxiter": 2000})
    mu, log_sigma = result.x
    return float(mu), float(math.exp(log_sigma))


def ece_brier(pred_t: np.ndarray, versions: list[Version], mu: float, sigma: float,
              tau: float = ECE_TAU_SEC, bins: int = 10) -> tuple[float, float, int]:
    """탄생 기준 τ초 시점 유효 여부로 ECE·Brier. 상태 모호(τ가 검열 너머,
    또는 이벤트 구간 안)는 제외한다."""
    probs, outcomes = [], []
    for m, v in zip(pred_t, versions):
        if v.event and v.hi is not None:
            if v.hi <= tau:
                valid = 0
            elif v.lo >= tau:
                valid = 1
            else:
                continue  # 이벤트 구간이 τ를 걸침 — 모호
        else:
            if v.lo >= tau:
                valid = 1
            else:
                continue  # τ 이전 검열 — 상태 미상
        z = (math.log(tau) - (math.log(max(m, 1e-12)) + mu)) / sigma
        probs.append(float(norm.sf(z)))
        outcomes.append(valid)
    p = np.array(probs)
    y = np.array(outcomes, dtype=float)
    brier = float(np.mean((p - y) ** 2))
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    for i in range(bins):
        mask = (p >= edges[i]) & (p < edges[i + 1] if i < bins - 1 else p <= 1.0)
        if mask.sum() == 0:
            continue
        ece += mask.sum() / len(p) * abs(p[mask].mean() - y[mask].mean())
    return float(ece), brier, len(p)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default=DEFAULT_SINCE,
                        help="홀드아웃 시작(ISO 8601) — 서빙 모델 학습 데이터 이후여야 함")
    parser.add_argument("--snapshots", type=Path, default=_DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--model", type=Path, default=_DEFAULT_MODEL)
    parser.add_argument("--out", type=Path, default=_RECAL_PATH)
    args = parser.parse_args()

    since_utc = datetime.fromisoformat(args.since).astimezone(timezone.utc)
    table = json.loads(Path(_DEFAULT_GAP_TABLE).read_text(encoding="utf-8"))
    gap_by_hpid = {k: float(v) for k, v in table["hospitals"].items()}
    gap_national = float(table["nationalMedianSec"])

    print(f"홀드아웃: {since_utc.isoformat()} 이후 탄생한 claim-version")
    versions = build_versions(args.snapshots, gap_by_hpid, gap_national, since_utc)
    n_event = sum(1 for v in versions if v.event)
    print(f"버전 {len(versions):,}개 (EVENT {n_event:,} · 검열 {len(versions) - n_event:,})")
    if n_event < 500:
        raise SystemExit("이벤트가 500개 미만 — 홀드아웃 창이 너무 짧다. --since 확인.")

    import xgboost as xgb

    booster = xgb.Booster()
    booster.load_model(str(args.model))
    matrix = xgb.DMatrix(
        np.asarray([v.features for v in versions], dtype=np.float32),
        missing=np.nan, feature_names=FEATURES,
    )
    best = getattr(booster, "best_iteration", None)
    pred_t = booster.predict(matrix, iteration_range=(0, best + 1) if best is not None else None)

    mu_r, sigma_r = fit_residual(pred_t, versions)
    ece_raw, brier_raw, n_eval = ece_brier(pred_t, versions, 0.0, 1.0)
    ece_recal, brier_recal, _ = ece_brier(pred_t, versions, mu_r, sigma_r)
    print(f"잔차 재보정: μR={mu_r:+.4f} (시간 스케일 ×{math.exp(mu_r):.3f}) · σR={sigma_r:.4f}")
    print(f"τ=30분 유효 확률 (평가 표본 {n_eval:,}):")
    print(f"  raw   : ECE {ece_raw:.4f} · Brier {brier_raw:.4f}")
    print(f"  recal : ECE {ece_recal:.4f} · Brier {brier_recal:.4f}")

    if ece_recal >= ece_raw:
        print("⚠ 재보정이 ECE를 개선하지 못했다 — 산출물을 저장하지 않는다(정직 관문).")
        raise SystemExit(1)

    args.out.write_text(json.dumps({
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "modelTag": Path(args.model).stem,
        "muR": round(mu_r, 6),
        "sigmaR": round(sigma_r, 6),
        "fittedOn": {
            "since": since_utc.isoformat(),
            "versions": len(versions),
            "events": n_event,
        },
        "metrics": {
            "tauSec": ECE_TAU_SEC,
            "eceRaw": round(ece_raw, 5), "eceRecal": round(ece_recal, 5),
            "brierRaw": round(brier_raw, 5), "brierRecal": round(brier_recal, 5),
            "evalSamples": n_eval,
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {args.out}")


if __name__ == "__main__":
    main()
