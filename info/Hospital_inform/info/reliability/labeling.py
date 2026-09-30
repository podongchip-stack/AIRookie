"""스냅샷 → claim-version 배치 재구성 (라벨·피처) — calibrate/train 공용.

features.py의 실시간 규칙과 같은 의미를 배치로 재현한다: 값 변화 = 새 버전,
관측 공백 1시간 초과 = 세그먼트 분리, 첫 버전 리듬 피처 NaN, 시각 피처 UTC.
라벨은 학습 파이프라인과 동일: 다음 값 변화의 폭 ≥ θ면 무효화(EVENT,
직전 관측~변화 관측 사이 구간검열), θ 미만 잔변화·공백·데이터 끝은 우측검열.

피처 9종(FULL9)의 마지막 열(route_med_gap — 병원별 평소 버전수명 중위)은
**호출자가 채운다**(NaN으로 돌려줌). 서빙 재보정은 배포된 테이블 값을,
학습은 누수 방지를 위해 train 구간에서 계산한 값을 넣어야 해서다.

hvec 외 필드는 -1이 '미입력'으로 실측 확인돼(egen/mapper.py) 결측 처리한다.
hvec은 음수가 과밀(정원 초과)의 실값이라 그대로 둔다 — 학습 파이프라인과 동일.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .engine import _BED_OP
from .features import SEGMENT_GAP_SEC


@dataclass
class Version:
    hpid: str
    born: datetime
    #: FULL9 순서(features.FEATURES). index 8(route_med_gap)은 NaN — 호출자가 채움
    features: list[float]
    #: EVENT면 (lo, hi] 구간검열 나이(초), 검열이면 lo까지 생존 확인(hi=None)
    lo: float
    hi: float | None
    event: bool


def build_versions(
    snapshot_dir: Path,
    *,
    field: str = "hvec",
    theta: int = 3,
    since_utc: datetime | None = None,
    treat_minus_one_as_missing: bool = False,
) -> list[Version]:
    state: dict[str, tuple[datetime, int]] = {}
    # seg[hpid] = (first_born, version_no, born, prev_lifetime, delta)
    seg: dict[str, tuple[datetime, int, datetime, float, float]] = {}
    open_versions: dict[str, Version] = {}
    done: list[Version] = []

    def close(hpid: str, lo: float, hi: float | None, event: bool) -> None:
        v = open_versions.pop(hpid, None)
        if v is None:
            return
        v.lo, v.hi, v.event = max(lo, 0.0), hi, event
        if (v.hi is not None and v.hi <= 0) or (v.hi is None and v.lo <= 0):
            return  # 탄생 직후 종료 — 정보 없음
        done.append(v)

    def open_version(hpid: str, ts: datetime, version_no: int, first_born: datetime,
                     prev_lifetime: float, delta: float) -> None:
        if since_utc is not None and ts < since_utc:
            open_versions.pop(hpid, None)
            return
        t_since = (ts - first_born).total_seconds()
        mean_interval = t_since / (version_no - 1) if version_no > 1 else math.nan
        open_versions[hpid] = Version(
            hpid=hpid, born=ts,
            features=[
                float(version_no), t_since, prev_lifetime, mean_interval,
                math.nan, delta, float(ts.hour), float(ts.isoweekday()), math.nan,
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
                    raw = item.get(field)
                    if not hpid or raw is None or str(raw).strip() == "":
                        continue
                    try:
                        value = int(str(raw).strip())
                    except ValueError:
                        continue
                    if treat_minus_one_as_missing and value == -1:
                        continue
                    prev = state.get(hpid)
                    if prev is None or (ts - prev[0]).total_seconds() > SEGMENT_GAP_SEC:
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
                        if delta >= theta:
                            close(hpid, age_lo, age_hi, True)
                        else:
                            close(hpid, age_lo, None, False)
                        prev_lifetime = age_hi
                        seg[hpid] = (first_born, version_no + 1, ts, prev_lifetime, float(delta))
                        open_version(hpid, ts, version_no + 1, first_born, prev_lifetime, float(delta))
                    state[hpid] = (ts, value)

    for hpid in list(open_versions):
        if hpid in seg and hpid in state:
            born = seg[hpid][2]
            close(hpid, (state[hpid][0] - born).total_seconds(), None, False)
    return done
