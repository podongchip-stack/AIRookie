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
from .severe import SevereTracker

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


def test_severe_tracker() -> bool:
    print("1-1. SevereTracker 신고 추적 규칙")
    t0 = datetime(2026, 9, 23, 3, 0, tzinfo=UTC)
    tracker = SevereTracker()

    # 항목 1(재관류중재술) Y — 첫 관측이라 나이는 하한(좌측검열)
    tracker.observe_row({"hpid": "H1", "MKioskTy1": "Y"}, t0)
    decls = tracker.group_declarations()
    d = decls.get("H1", {}).get("재관류중재술")
    ok = _check(
        "첫 관측 Y: 그룹 등재 + ageIsMin=True",
        d is not None and d.value == "Y" and d.born == t0 and d.age_is_min,
    )

    # Y → 정보미제공: 그룹에서 빠진다
    tracker.observe_row({"hpid": "H1", "MKioskTy1": "정보미제공"}, t0 + timedelta(hours=9))
    ok &= _check(
        "Y→정보미제공: 그룹에서 제외",
        "재관류중재술" not in tracker.group_declarations().get("H1", {}),
    )

    # 미제공 → Y 재신고: born이 재신고 시각으로 새로 잡히고 하한 아님.
    # 재신고는 마지막 관측(9h의 미제공)에서 1시간(세그먼트 공백 규칙) 안에
    # 넣는다 — 실제 스트림은 20분마다 관측이 이어져 공백이 생기지 않는다.
    t_redeclare = t0 + timedelta(hours=9, minutes=40)
    tracker.observe_row({"hpid": "H1", "MKioskTy1": "Y"}, t_redeclare)
    d = tracker.group_declarations()["H1"]["재관류중재술"]
    ok &= _check(
        "재신고: born=재신고 시각, ageIsMin=False",
        d.born == t_redeclare and not d.age_is_min,
    )

    # 같은 그룹에서 Y가 불가능보다 우선 (항목 3 Y, 항목 4 불가능 → 뇌출혈수술=Y)
    tracker.observe_row({"hpid": "H1", "MKioskTy3": "Y", "MKioskTy4": "불가능"}, t_redeclare)
    d = tracker.group_declarations()["H1"]["뇌출혈수술"]
    ok &= _check("그룹 대표값: Y > 불가능", d.value == "Y")

    # 불가능만 있으면 불가능으로 등재
    tracker.observe_row({"hpid": "H2", "MKioskTy19": "불가능"}, t_redeclare)
    d = tracker.group_declarations()["H2"]["중증화상"]
    ok &= _check("불가능 단독 신고도 등재", d.value == "불가능")
    return ok


def test_engine() -> bool:
    print("2. 실데이터 워밍업 → 예측")
    engine = BedReliabilityEngine()
    print(f"  워밍업 관측 {engine.warmed_up_observations:,}건, 추적 병원 수 확인 중...")
    now = datetime.now(UTC)
    all_preds = engine.predict(now)
    ok = _check(
        "다필드 서빙 로드 (hvec + 확장 3종)",
        {"hvec", "hvoc", "hvgc", "hv28"} <= set(engine.fields),
        f"필드: {engine.fields}",
    )
    preds = all_preds.get("hvec", {})
    ok &= _check("hvec 예측 병원 수 > 300", len(preds) > 300, f"{len(preds)}곳")
    for field in ("hvoc", "hvgc"):
        n = len(all_preds.get(field, {}))
        ok &= _check(f"{field} 예측 병원 수 > 300", n > 300, f"{n}곳")
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
        if float(serve.at(p.pred_t_sec, p.age_sec, 600.0, sigma=p.sigma)) > p.authority + 1e-9
    ]
    ok &= _check("10분 뒤 authority ≤ 지금 authority (단조 감소)", not mono_bad, f"위반 {len(mono_bad)}곳")

    sample = sorted(preds.items(), key=lambda kv: kv[1].age_sec)[:3]
    for hpid, p in sample:
        print(
            f"    예시 {hpid}: pred_t={p.pred_t_sec:,.0f}s age={p.age_sec:,.0f}s "
            f"authority={p.authority:.3f} ttl={p.ttl_sec:,.0f}s"
        )

    severe = engine.severe.group_declarations()
    declared_hospitals = len(severe)
    declared_groups = sum(len(g) for g in severe.values())
    ok &= _check("중증신고 추적 병원 > 100", declared_hospitals > 100,
                 f"{declared_hospitals}곳 · 그룹 신고 {declared_groups:,}건")
    fresh = [
        (h, g, d) for h, groups in severe.items() for g, d in groups.items()
        if not d.age_is_min
    ]
    ok &= _check("좌측검열 아닌(추적 중 태어난) 신고 존재", len(fresh) > 0, f"{len(fresh):,}건")
    if fresh:
        h, g, d = max(fresh, key=lambda x: x[2].born)
        age_h = (now - d.born).total_seconds() / 3600
        print(f"    예시 {h} [{g}] {d.value} — 신고 나이 {age_h:.1f}h")
    return ok


def test_hub_math_parity() -> bool:
    print("3. hub 표준 라이브러리 수식 ↔ scipy serve 등가성")
    nd = NormalDist()
    max_err_auth = 0.0
    max_err_ttl = 0.0
    for pred_t in (60.0, 1200.0, 86400.0):
        for age in (1.0, 600.0, 3600.0, 100000.0):
            for sigma in (1.0, 1.7965):  # raw / 잔차 재보정(σR) 양쪽 모두 등가여야 함
                # hub/bed_reliability.py와 같은 수식 (math.erfc / NormalDist.inv_cdf)
                stdlib_auth = 0.5 * math.erfc(
                    (math.log(max(age, 1e-12)) - math.log(max(pred_t, 1e-12)))
                    / (sigma * math.sqrt(2))
                )
                max_err_auth = max(
                    max_err_auth,
                    abs(stdlib_auth - float(serve.authority(pred_t, age, sigma=sigma))),
                )
                thr = min(max(AUTHORITY_TTL_THRESHOLD, 1e-12), 1 - 1e-12)
                stdlib_ttl = max(
                    max(pred_t, 1e-12) * math.exp(sigma * nd.inv_cdf(1.0 - thr)) - age, 0.0
                )
                max_err_ttl = max(
                    max_err_ttl,
                    abs(stdlib_ttl - float(serve.ttl(pred_t, age, thr, sigma=sigma))),
                )
    ok = _check("authority 최대 오차 < 1e-9", max_err_auth < 1e-9, f"{max_err_auth:.2e}")
    ok &= _check("ttl 최대 오차 < 1e-6초", max_err_ttl < 1e-6, f"{max_err_ttl:.2e}")
    return ok


def main() -> None:
    results = [test_tracker(), test_severe_tracker(), test_engine(), test_hub_math_parity()]
    if all(results):
        print("\n전부 통과.")
    else:
        raise SystemExit("\n실패 항목이 있다 — 위 FAIL 참조.")


if __name__ == "__main__":
    main()
