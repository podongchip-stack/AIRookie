"""병원별 평소 리듬(route_med_gap) 정적 테이블 생성 CLI.

route_med_gap은 "이 병원의 병상 값 버전이 평소 얼마나 오래 사는가"(버전
수명 중위값, 초)로, 모델 피처 9종 중 예측력이 가장 센 리듬 계열의 하나다.
학습 파이프라인(egen_pipeline.py)은 이를 학습 기간 전체에서 집계하는데,
서빙 프로세스는 켜진 뒤의 짧은 이력만 갖고 있어 실시간으로는 이 값을 만들
수 없다 — 그래서 스냅샷 축적본에서 미리 뽑아 모델과 함께 배포하는 정적
테이블로 둔다(월 1회 재학습 때 같이 재생성).

    python -m reliability.build_route_med_gap                # 기본 경로로 생성
    python -m reliability.build_route_med_gap --snapshots <dir> --out <json>

집계 규칙은 features.py(=학습 파이프라인)와 동일하다: 값이 바뀌는 관측마다
버전 탄생, 관측 공백 1시간 초과 시 세그먼트 분리(그 경계의 간격은 수명으로
세지 않음). 학습은 cutoff 이전(train 기간)만 썼지만 여기서는 축적 전체를
쓴다 — 라벨이 아니라 입력 피처라 미래 누수 문제가 없고, 최신 리듬이 더
정확하기 때문. 테이블에 없는 병원은 엔진이 전국 중위값으로 대체한다
(신규 병원 zero-shot 적용 — AIROOKIE-EGEN.md §6-1).

pandas 없이 순수 표준 라이브러리로 돌아간다 (API 호출 0회, 전체 축적 기준
수십 초).
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from .engine import _BED_OP, _DEFAULT_GAP_TABLE, _DEFAULT_SNAPSHOT_DIR
from .features import SEGMENT_GAP_SEC


def collect_lifetimes(snapshot_dir: Path) -> tuple[dict[str, list[float]], int]:
    """스냅샷 전체를 훑어 병원별 버전 수명(초) 목록을 모은다."""
    lifetimes: dict[str, list[float]] = {}
    # hpid -> (마지막 관측시각, 마지막 값, 현재 버전 탄생시각)
    state: dict[str, tuple[datetime, int, datetime]] = {}
    observations = 0

    for path in sorted(snapshot_dir.glob("*.jsonl")):
        with path.open("rb") as f:
            for raw_line in f:
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if record.get("operation") != _BED_OP or "error" in record:
                    continue
                try:
                    ts = datetime.fromisoformat(record["ts"]).astimezone(timezone.utc)
                except (KeyError, ValueError):
                    continue
                for item in record.get("items") or []:
                    hpid = (item.get("hpid") or "").strip()
                    raw = item.get("hvec")
                    if not hpid or raw is None or str(raw).strip() == "":
                        continue
                    try:
                        value = int(str(raw).strip())
                    except ValueError:
                        continue
                    observations += 1
                    prev = state.get(hpid)
                    if prev is None or (ts - prev[0]).total_seconds() > SEGMENT_GAP_SEC:
                        state[hpid] = (ts, value, ts)  # 새 세그먼트 첫 버전
                        continue
                    last_obs, last_value, born = prev
                    if ts <= last_obs:
                        continue
                    if value != last_value:
                        lifetimes.setdefault(hpid, []).append((ts - born).total_seconds())
                        state[hpid] = (ts, value, ts)
                    else:
                        state[hpid] = (ts, last_value, born)
    return lifetimes, observations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshots", type=Path, default=_DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--out", type=Path, default=_DEFAULT_GAP_TABLE)
    args = parser.parse_args()

    lifetimes, observations = collect_lifetimes(args.snapshots)
    hospitals = {
        hpid: round(statistics.median(values), 1)
        for hpid, values in sorted(lifetimes.items())
    }
    if not hospitals:
        raise SystemExit(f"스냅샷에서 버전 수명을 하나도 못 모았다: {args.snapshots}")
    national = round(statistics.median(hospitals.values()), 1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "snapshotDir": str(args.snapshots),
                "observations": observations,
                "nationalMedianSec": national,
                "hospitals": hospitals,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"병원 {len(hospitals)}곳 (관측 {observations:,}건) -> {args.out}\n"
        f"전국 중위 버전수명 {national:,.0f}초 (~{national / 60:.0f}분)"
    )


if __name__ == "__main__":
    main()
