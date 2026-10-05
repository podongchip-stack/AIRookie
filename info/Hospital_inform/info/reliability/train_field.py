"""필드별 infosurv 모델 학습 CLI — 저장소 자급 학습 + 채택 관문 내장.

    python -m reliability.train_field --field hvoc          # 수술실
    python -m reliability.train_field --field hvicc         # 중환자실 일반
    python -m reliability.train_field --field hvgc          # 입원실 일반
    python -m reliability.train_field --field hv28          # 응급실 소아

hvec(응급실 일반병상) 모델은 연구 저장소에서 학습돼 벤더링됐지만, 수평 확장
필드들은 이 CLI로 이 저장소 안에서 학습한다 — infosurv의 학습 본체는 도메인
중립(벤더링된 fit.py·evaluate.py)이고, E-Gen 고유의 것은 데이터와 얇은
파서(labeling.py)뿐이기 때문. 아키텍처·라벨 의미(θ 무효화·구간검열)·피처
9종은 hvec 학습 파이프라인과 동일하다.

## 채택 관문 (연구 문화의 이식 — 미달이면 모델을 저장하지 않는다)

1. **리듬 단독 baseline을 이겨야 한다**: FULL(9피처) C-index가
   INTERVAL(mean_interval_so_far·prev_lifetime만) baseline보다 **시드 3종
   전부에서** 높을 것. 행동 피처가 "나이÷평소 갱신 간격"으로 수렴했다면
   모델을 얹을 이유가 없다(infosurv README 필수 ablation).
2. 학습 이벤트 ≥ 2,000 (infosurv check 모듈의 실측 임계).

시간 분할: --cutoff 이전 탄생 버전으로 학습, 이후로 평가(early stopping의
eval set 겸용 — hvec의 ext0923 프로토콜과 동일). route_med_gap 피처는 누수
방지를 위해 **train 구간에서만** 계산해 train/test 양쪽에 주입한다.

산출물(관문 통과 시): model/aft_egen_{field}_theta{θ}.json (FULL9 피처명
그대로라 서빙 빌더 공유), model/route_med_gap_{field}.json (서빙용 — 전체
축적 기준), model/train_results_{field}.json (관문 수치 기록 — 기각도 기록).
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import fit
from .engine import _DEFAULT_SNAPSHOT_DIR
from .evaluate import cindex
from .features import FEATURES
from .labeling import Version, build_versions

#: hvec ext0923 프로토콜과 같은 분할 경계(학습 09-21까지 / 평가 09-22부터)
DEFAULT_CUTOFF = "2026-09-22T00:00:00+09:00"
SEEDS = (42, 43, 44)
EVENT_MIN_TRAIN = 2000

_MODEL_DIR = Path(__file__).resolve().parent / "model"

#: 확장 대상 필드와 용도 (egen/mapper.py BED_FIELD_MAP과 실측 필드 주석 기준)
FIELD_LABELS = {
    "hvoc": "수술실",
    "hvicc": "중환자실 일반",
    "hvgc": "입원실 일반",
    "hv28": "응급실 소아",
    "hv29": "음압 격리",
    "hv34": "중환자실 심장(CCU)",
    "hv2": "중환자실 내과",
    "hv3": "중환자실 외과",
    "hvncc": "신생아 중환자",
}


def _median_gap_by_hpid(versions: list[Version]) -> tuple[dict[str, float], float]:
    """병원별 버전수명(prev_lifetime 피처) 중위값과 전국 fallback."""
    lifetimes: dict[str, list[float]] = defaultdict(list)
    for v in versions:
        pl = v.features[2]
        if not math.isnan(pl):
            lifetimes[v.hpid].append(pl)
    med = {h: statistics.median(ls) for h, ls in lifetimes.items() if ls}
    national = statistics.median(med.values()) if med else float("nan")
    return med, national


def _frame(versions: list[Version]) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    X = pd.DataFrame([v.features for v in versions], columns=FEATURES, dtype=np.float32)
    lower = np.array([v.lo for v in versions], dtype=float)
    upper = np.array([v.hi if v.event else np.inf for v in versions], dtype=float)
    event = np.array([v.event for v in versions])
    t_obs = np.where(event, np.array([v.hi if v.hi is not None else v.lo for v in versions]),
                     lower)
    return X, lower, upper, event, t_obs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--field", required=True, choices=sorted(FIELD_LABELS))
    parser.add_argument("--theta", type=int, default=3)
    parser.add_argument("--cutoff", default=DEFAULT_CUTOFF)
    parser.add_argument("--snapshots", type=Path, default=_DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--rounds", type=int, default=300)
    args = parser.parse_args()

    cutoff_utc = datetime.fromisoformat(args.cutoff).astimezone(timezone.utc)
    label = FIELD_LABELS[args.field]
    print(f"=== {args.field} ({label}) · θ={args.theta} · cutoff {cutoff_utc.isoformat()} ===")

    versions = build_versions(
        args.snapshots, field=args.field, theta=args.theta,
        treat_minus_one_as_missing=True,  # hvec 외 필드는 -1이 미입력(실측)
    )
    train = [v for v in versions if v.born < cutoff_utc]
    test = [v for v in versions if v.born >= cutoff_utc]
    n_ev_train = sum(1 for v in train if v.event)
    n_ev_test = sum(1 for v in test if v.event)
    print(f"버전 train {len(train):,}(EVENT {n_ev_train:,}) / test {len(test):,}(EVENT {n_ev_test:,})")

    results: dict = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "field": args.field, "label": label, "theta": args.theta,
        "cutoff": cutoff_utc.isoformat(),
        "train": {"versions": len(train), "events": n_ev_train},
        "test": {"versions": len(test), "events": n_ev_test},
        "seeds": {},
    }
    results_path = _MODEL_DIR / f"train_results_{args.field}.json"

    def record(adopted: bool, reason: str) -> None:
        results["adopted"] = adopted
        results["reason"] = reason
        results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"기록: {results_path}")

    if n_ev_train < EVENT_MIN_TRAIN or n_ev_test < 100:
        record(False, f"이벤트 부족 (train {n_ev_train} < {EVENT_MIN_TRAIN} 또는 test {n_ev_test} < 100)")
        raise SystemExit(f"관문 미달 — 이벤트 부족. θ를 낮추거나 축적 후 재시도.")

    # route_med_gap: 누수 방지를 위해 train 구간에서만 계산해 양쪽에 주입
    gap_train, national_train = _median_gap_by_hpid(train)
    for v in versions:
        v.features[8] = gap_train.get(v.hpid, national_train)

    X_tr, lo_tr, up_tr, _, _ = _frame(train)
    X_te, lo_te, up_te, ev_te, t_obs_te = _frame(test)

    gate_pass = True
    final_booster = None
    for seed in SEEDS:
        full = fit.train(X_tr, lo_tr, up_tr, X_te, lo_te, up_te,
                         rounds=args.rounds, params={"seed": seed})
        c_full = cindex(t_obs_te, ev_te, fit.predict(full, X_te))
        cols = fit.INTERVAL_ONLY
        interval = fit.train(X_tr[cols], lo_tr, up_tr, X_te[cols], lo_te, up_te,
                             rounds=args.rounds, params={"seed": seed})
        c_interval = cindex(t_obs_te, ev_te, fit.predict(interval, X_te[cols]))
        win = bool(c_full > c_interval)
        gate_pass &= win
        results["seeds"][str(seed)] = {
            "cFull": round(float(c_full), 4), "cInterval": round(float(c_interval), 4), "win": win,
        }
        print(f"  seed {seed}: FULL C {c_full:.4f} vs INTERVAL {c_interval:.4f} → {'승' if win else '패'}")
        if seed == SEEDS[0]:
            final_booster = full

    mean_full = statistics.mean(r["cFull"] for r in results["seeds"].values())
    results["meanCFull"] = round(mean_full, 4)
    if not gate_pass:
        record(False, "FULL이 INTERVAL baseline을 전 시드에서 이기지 못함 — 모델 저장 거부")
        raise SystemExit("관문 미달 — 리듬 단독과 구별되지 않는 모델은 얹지 않는다.")

    model_path = _MODEL_DIR / f"aft_egen_{args.field}_theta{args.theta}.json"
    final_booster.save_model(str(model_path))

    # 서빙용 리듬 테이블은 전체 축적 기준(입력 피처라 미래 누수 문제 없음 —
    # build_route_med_gap.py의 hvec 테이블과 같은 원칙)
    gap_all, national_all = _median_gap_by_hpid(versions)
    gap_path = _MODEL_DIR / f"route_med_gap_{args.field}.json"
    gap_path.write_text(json.dumps({
        "generatedAt": results["generatedAt"], "field": args.field,
        "nationalMedianSec": round(national_all, 1),
        "hospitals": {h: round(s, 1) for h, s in sorted(gap_all.items())},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    record(True, f"관문 통과 (시드 {len(SEEDS)}종 전승, 평균 FULL C {mean_full:.4f})")
    print(f"모델 저장: {model_path}\n리듬 테이블: {gap_path}")


if __name__ == "__main__":
    main()
