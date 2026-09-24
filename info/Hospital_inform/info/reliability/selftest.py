"""서빙 체인 자체검증 CLI — API 호출 0회, 로컬 스냅샷·모델만 사용.

    python -m reliability.selftest

세 가지를 확인한다:
1. ClaimTracker 피처 구성이 학습 파이프라인 규칙과 일치하는지 (합성 관측으로
   기대값 대조 — 버전 판정, 세그먼트 리셋, NaN 규칙, UTC 시각 피처)
2. 실제 스냅샷 워밍업 → 모델 예측이 끝까지 도는지 + 출력 성질
   (authority ∈ [0,1], ttl ≥ 0, 나이가 들수록 authority 단조 감소)
3. hub 쪽이 쓰는 표준 라이브러리 생존함수(erfc 기반, hub/bed_reliability.py)가
   여기 scipy 기반 serve와 수치적으로 같은지 (hub는 이 폴더를 import할 수
   없어 수식을 따로 들고 있다 — 그 등가성을 여기서 못박는다)
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from statistics import NormalDist

from . import serve
from .engine import AUTHORITY_TTL_THRESHOLD, BedReliabilityEngine
from .features import FEATURES, ClaimTracker

UTC = timezone.utc


def _check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def test_tracker() -> bool:
    print("1. ClaimTracker 피처 규칙")
    t0 = datetime(2026, 9, 23, 3, 0, tzinfo=UTC)  # UTC 03시 수요일
    tracker = ClaimTracker()
    tracker.observe("H1", t0, 10)  # 버전 1 탄생
    row = tracker.feature_row("H1", 1200.0)
    ok = _check(
        "첫 버전: version_no=1, 리듬 피처 전부 NaN",
        row[0] == 1.0
        and row[1] == 0.0
        and math.isnan(row[2])
        and math.isnan(row[3])
        and math.isnan(row[4])
        and math.isnan(row[5])
        and row[6] == 3.0
        and row[7] == 3.0  # 수요일 = 3 (월=1)
        and row[8] == 1200.0,
        f"row={row}",
    )

    tracker.observe("H1", t0 + timedelta(minutes=20), 10)  # 같은 값 — 버전 유지
    tracker.observe("H1", t0 + timedelta(minutes=40), 7)  # 값 변화 — 버전 2
    row = tracker.feature_row("H1", 1200.0)
    ok &= _check(
        "버전 2: prev_lifetime=2400s, delta=3, mean_interval=2400s",
        row[0] == 2.0 and row[1] == 2400.0 and row[2] == 2400.0 and row[3] == 2400.0 and row[5] == 3.0,
        f"row={row}",
    )

    tracker.observe("H1", t0 + timedelta(minutes=40), 5)  # 같은 시각 중복 — 무시
    ok &= _check("동일 시각 중복 관측 무시", tracker.get("H1").last_value == 7)

    tracker.observe("H1", t0 + timedelta(hours=3), 7)  # 공백 1h 초과 — 세그먼트 리셋
    row = tracker.feature_row("H1", 1200.0)
    ok &= _check("공백 1시간 초과 시 세그먼트 리셋", row[0] == 1.0 and math.isnan(row[2]), f"row={row}")
    return ok


def test_engine() -> bool:
    print("2. 실데이터 워밍업 → 예측")
    engine = BedReliabilityEngine()
    print(f"  워밍업 관측 {engine.warmed_up_observations:,}건, 추적 병원 수 확인 중...")
    now = datetime.now(UTC)
    preds = engine.predict(now)
    ok = _check("예측 병원 수 > 300", len(preds) > 300, f"{len(preds)}곳")
    if not preds:
        return False
    bad = [
        h
        for h, p in preds.items()
        if not (0.0 <= p.authority <= 1.0) or p.ttl_sec < 0 or p.pred_t_sec <= 0
    ]
    ok &= _check("authority ∈ [0,1], ttl ≥ 0, pred_t > 0 전수", not bad, f"위반 {len(bad)}곳")
    mono_bad = [
        h
        for h, p in preds.items()
        if float(serve.at(p.pred_t_sec, p.age_sec, 600.0)) > p.authority + 1e-9
    ]
    ok &= _check("10분 뒤 authority ≤ 지금 authority (단조 감소)", not mono_bad, f"위반 {len(mono_bad)}곳")

    sample = sorted(preds.items(), key=lambda kv: kv[1].age_sec)[:3]
    for hpid, p in sample:
        print(
            f"    예시 {hpid}: pred_t={p.pred_t_sec:,.0f}s age={p.age_sec:,.0f}s "
            f"authority={p.authority:.3f} ttl={p.ttl_sec:,.0f}s"
        )
    return ok


def test_hub_math_parity() -> bool:
    print("3. hub 표준 라이브러리 수식 ↔ scipy serve 등가성")
    nd = NormalDist()
    max_err_auth = 0.0
    max_err_ttl = 0.0
    for pred_t in (60.0, 1200.0, 86400.0):
        for age in (1.0, 600.0, 3600.0, 100000.0):
            # hub/bed_reliability.py와 같은 수식 (math.erfc / NormalDist.inv_cdf)
            stdlib_auth = 0.5 * math.erfc(
                (math.log(max(age, 1e-12)) - math.log(max(pred_t, 1e-12))) / math.sqrt(2)
            )
            max_err_auth = max(max_err_auth, abs(stdlib_auth - float(serve.authority(pred_t, age))))
            thr = min(max(AUTHORITY_TTL_THRESHOLD, 1e-12), 1 - 1e-12)
            stdlib_ttl = max(max(pred_t, 1e-12) * math.exp(nd.inv_cdf(1.0 - thr)) - age, 0.0)
            max_err_ttl = max(max_err_ttl, abs(stdlib_ttl - float(serve.ttl(pred_t, age, thr))))
    ok = _check("authority 최대 오차 < 1e-9", max_err_auth < 1e-9, f"{max_err_auth:.2e}")
    ok &= _check("ttl 최대 오차 < 1e-6초", max_err_ttl < 1e-6, f"{max_err_ttl:.2e}")
    return ok


def main() -> None:
    results = [test_tracker(), test_engine(), test_hub_math_parity()]
    if all(results):
        print("\n전부 통과.")
    else:
        raise SystemExit("\n실패 항목이 있다 — 위 FAIL 참조.")


if __name__ == "__main__":
    main()
