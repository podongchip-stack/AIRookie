"""열린 질문 ①: "수집 주기 20~30분인데 유지시간 중앙값 20분을 어떻게 측정했나"

    python openq_lifetime.py            # 최근 14일 스냅샷으로 재계산
    python openq_lifetime.py --days 30

핵심: 폴링 관측은 구간검열(interval censoring)이다 — 값이 바뀐 정확한 순간은 모르고
"마지막으로 같았던 시각(lo)과 처음 달라진 시각(hi) 사이"만 안다. 이 스크립트는
수명을 점이 아니라 구간 (lo, hi]로 취급해 **중앙값의 하한·상한을 따로** 추정한다:

- 상한 추정: 모든 변화가 hi(다음 폴링 시각)에 일어났다고 가정한 생존곡선의 중앙값
- 하한 추정: 모든 변화가 lo(마지막 동일 관측) 직후 일어났다고 가정한 중앙값

진짜 중앙값은 그 사이 어딘가다. 학습(AFT)은 애초에 구간 (lo, hi] 그대로 넣으므로
(infosurv labeling과 동일 규칙: 관측 공백 60분 초과·데이터 끝 = 우측검열) 이 문제가
없고, 이 스크립트는 "요약 문장용 숫자"가 해상도에 어떻게 걸리는지 보여주는 용도다.

대상 필드는 hvec(응급실 가용 일반병상), 값 비교는 "임의 변화"(교체) 기준 —
AIROOKIE-EGEN.md §2의 "수명 중위 20분" 문장과 같은 정의다.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from data_load import BED_OPERATION, SNAPSHOT_DIR

GAP_RESET_MIN = 60.0  # 관측 공백이 이보다 크면 세그먼트 리셋(우측검열) — 학습 파이프라인과 동일


def load_series(days: int) -> dict[str, list[tuple[float, int]]]:
    """최근 N일 스냅샷에서 병원별 (시각[분], hvec) 시계열을 만든다."""
    files = sorted(SNAPSHOT_DIR.glob("*.jsonl"))[-days:]
    series: dict[str, list[tuple[float, int]]] = {}
    epoch: datetime | None = None
    for path in files:
        with path.open(encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("operation") != BED_OPERATION or not rec.get("items"):
                    continue
                ts = datetime.fromisoformat(rec["ts"])
                if epoch is None:
                    epoch = ts
                minutes = (ts - epoch).total_seconds() / 60.0
                for item in rec["items"]:
                    raw = item.get("hvec")
                    if raw is None:
                        continue
                    try:
                        value = int(raw)
                    except (TypeError, ValueError):
                        continue
                    series.setdefault(item["hpid"], []).append((minutes, value))
    for rows in series.values():
        rows.sort()
    return series


def collect_intervals(series: dict[str, list[tuple[float, int]]]) -> tuple[list[tuple[float, float]], list[float], list[float]]:
    """claim별 수명 구간을 모은다.

    반환: (변화 관측 (lo, hi] 목록, 우측검열 lo 목록, 관측된 폴링 간격 목록)
    """
    observed: list[tuple[float, float]] = []   # (lo, hi]
    censored: list[float] = []                 # 수명 >= lo
    gaps: list[float] = []
    for rows in series.values():
        birth = last_same = rows[0][0]
        value = rows[0][1]
        prev_t = rows[0][0]
        for t, v in rows[1:]:
            gap = t - prev_t
            if gap > GAP_RESET_MIN:
                # 수집 공백 — 지금 claim은 우측검열로 닫고 새로 시작
                censored.append(last_same - birth)
                birth = last_same = t
                value = v
                prev_t = t
                continue
            gaps.append(gap)
            if v != value:
                observed.append((last_same - birth, t - birth))
                birth = last_same = t
                value = v
            else:
                last_same = t
            prev_t = t
        censored.append(last_same - birth)
    return observed, censored, gaps


def km_median(durations: list[tuple[float, bool]]) -> float | None:
    """Kaplan-Meier 중앙값. durations = (시간, 사건 여부). 0.5에 못 닿으면 None."""
    events = sorted(durations)
    n = len(events)
    at_risk, survival = n, 1.0
    i = 0
    while i < n:
        t = events[i][0]
        deaths = risks = 0
        while i < n and events[i][0] == t:
            risks += 1
            deaths += events[i][1]
            i += 1
        if at_risk > 0 and deaths:
            survival *= 1.0 - deaths / at_risk
        at_risk -= risks
        if survival <= 0.5:
            return t
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()

    series = load_series(args.days)
    observed, censored, gaps = collect_intervals(series)
    gaps.sort()
    gap_median = gaps[len(gaps) // 2] if gaps else 0.0
    total = len(observed) + len(censored)

    # 상한: 변화가 hi에 일어났다고 보고 KM. 하한: lo 직후에 일어났다고 보고 KM.
    upper = km_median([(hi, True) for _, hi in observed] + [(lo, False) for lo in censored])
    lower = km_median([(lo, True) for lo, _ in observed] + [(lo, False) for lo in censored])
    naive = sorted(hi for _, hi in observed)
    naive_median = naive[len(naive) // 2] if naive else None
    # 폴링 1주기 생존율: 다음 관측에서 값이 그대로일 확률 (관측 단위)
    changes = len(observed)
    same_observations = sum(len(r) - 1 for r in series.values()) - changes

    print(f"스냅샷 {args.days}일 — 병원 {len(series)}곳, claim {total:,}개 "
          f"(변화 관측 {changes:,} / 우측검열 {len(censored):,}), 폴링 간격 중앙값 {gap_median:.1f}분")
    print(f"관측 1회당 값 변화 비율: {changes / max(changes + same_observations, 1) * 100:.1f}%")
    print(f"수명 중앙값 — 구간검열 하한 추정: {lower:.1f}분 / 상한 추정: {upper:.1f}분"
          if lower is not None and upper is not None else "중앙값이 0.5에 도달하지 않음")
    print(f"naive(변화를 다음 폴링 시각으로 간주) 중앙값: {naive_median:.1f}분" if naive_median else "")
    print("\n해석: 진짜 중앙값은 [하한, 상한] 사이 어딘가다. 상한이 폴링 간격과 같게 나오면")
    print("'중앙값 20분'은 해상도에 걸린 요약이라는 뜻 — 학습은 구간 (lo, hi] 그대로(AFT")
    print("구간검열)라 이 문제가 없고, 요약 문장은 '폴링 1주기 안에 절반가량 바뀐다'로 쓴다.")


if __name__ == "__main__":
    main()
