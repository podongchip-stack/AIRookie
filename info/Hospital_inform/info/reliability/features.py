"""claim-version 상태 추적 + 모델 입력 피처 9종 실시간 구성.

모델링 프로젝트의 배치 파이프라인(`explore/egen_pipeline.py`)이 학습 때
정의한 피처를, 배치(전체 parquet 재계산)가 아니라 **관측이 하나 들어올
때마다 상태를 갱신하는 방식**으로 동일하게 재현한다 — 학습·서빙의 피처
정의가 어긋나면 모델이 조용히 엉뚱한 값을 내기 때문에, 이 파일의 규칙은
전부 그 파이프라인의 규칙을 따른다:

- claim = (병원, 가용병상수 hvec). 값이 바뀌는 관측마다 새 버전이 탄생한다.
- 관측 공백이 1시간(SEGMENT_GAP_SEC)을 넘으면 세그먼트를 끊고 버전
  카운터를 리셋한다(수집 중단 전후를 한 이력으로 잇지 않는다).
- 시각 피처(hour_utc/dow)는 **UTC 기준**이다 — KST로 넣으면 C-index가
  실측으로 떨어진다(모델링 프로젝트 REPORT §7-1의 실수 재현 경고).
- version_no==1이면 mean_interval_so_far/prev_lifetime/delta는 **NaN**이다.
  0으로 채우면 안 된다 — XGBoost가 결측(missing=NaN)을 네이티브로 다루며
  학습 때도 NaN이었다.

피처 컬럼명·순서는 학습된 모델 JSON의 `learner.feature_names`와 정확히
일치해야 한다(모델링 프로젝트 `explore/g2_features.py`의 FEATURES와 동일).
⚠ infosurv 패키지의 `features.build()`가 내는 중립 스키마(`hour`,
`src_med_gap` 등)와는 컬럼명 4개가 다르다 — 그쪽을 그대로 쓰면 안 된다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

#: 학습된 모델(aft_egen_theta*_ext0923.json)의 learner.feature_names 그대로.
FEATURES = [
    "version_no",
    "t_since_claim_start",
    "prev_lifetime",
    "mean_interval_so_far",
    "horizon_s",
    "delta_pred_s",
    "hour_utc",
    "dow",
    "route_med_gap",
]

#: 관측 공백이 이 초를 넘으면 세그먼트(클레임 열)를 끊는다 — 파이프라인의 GAP_S.
SEGMENT_GAP_SEC = 3600.0


@dataclass
class ClaimState:
    """병원 1곳의 현재 claim-version 상태. 시각은 전부 aware UTC."""

    last_obs: datetime  #: 마지막 관측 시각 (같은 값이어도 갱신됨)
    last_value: int  #: 마지막 관측된 hvec
    version_no: int  #: 세그먼트 내 몇 번째 버전인지 (1부터)
    first_born: datetime  #: 세그먼트 첫 버전 탄생 시각 (t_since_claim_start 기준점)
    born: datetime  #: 현재 버전 탄생 시각 (age 계산 기준점)
    prev_lifetime_sec: float  #: 직전 버전의 수명(초). 첫 버전이면 NaN
    delta: float  #: 이 버전을 만든 변화폭 |hvec − 직전값|. 첫 버전이면 NaN


class ClaimTracker:
    """병원별 관측 스트림을 받아 ClaimState를 유지한다.

    관측은 시간 순서로 넣어야 한다 — 마지막 관측보다 과거인 관측은 버린다
    (스냅샷 파일과 이번 사이클 rows 두 스트림을 섞어 넣을 때, 이미 반영된
    구간이 다시 들어와도 상태가 역행하지 않게 하는 안전장치).
    """

    def __init__(self) -> None:
        self._states: dict[str, ClaimState] = {}

    def __len__(self) -> int:
        return len(self._states)

    def observe(self, hpid: str, ts: datetime, value: int) -> None:
        """관측 1건을 반영한다. ts는 aware UTC여야 한다."""
        state = self._states.get(hpid)

        if state is None or (ts - state.last_obs).total_seconds() > SEGMENT_GAP_SEC:
            # 첫 관측이거나 공백이 너무 길다 — 새 세그먼트의 첫 버전.
            self._states[hpid] = ClaimState(
                last_obs=ts,
                last_value=value,
                version_no=1,
                first_born=ts,
                born=ts,
                prev_lifetime_sec=math.nan,
                delta=math.nan,
            )
            return

        if ts <= state.last_obs:
            return  # 과거(또는 중복) 관측 — 무시

        if value != state.last_value:
            # 값이 바뀌었다 — 새 버전 탄생.
            state.prev_lifetime_sec = (ts - state.born).total_seconds()
            state.delta = abs(value - state.last_value)
            state.born = ts
            state.version_no += 1
            state.last_value = value

        state.last_obs = ts

    def get(self, hpid: str) -> ClaimState | None:
        return self._states.get(hpid)

    def hpids(self) -> list[str]:
        return list(self._states)

    def feature_row(self, hpid: str, route_med_gap: float) -> list[float] | None:
        """현재 버전의 모델 입력 피처를 FEATURES 순서로 돌려준다.

        route_med_gap은 학습 기간 통계로 미리 뽑아둔 정적 값이라 호출자가
        넣어준다(engine.py가 model/route_med_gap.json에서 조회). 관측이 한
        번도 없던 병원이면 None.
        """
        state = self._states.get(hpid)
        if state is None:
            return None
        t_since_claim_start = (state.born - state.first_born).total_seconds()
        if state.version_no > 1:
            mean_interval = t_since_claim_start / (state.version_no - 1)
        else:
            mean_interval = math.nan
        born_utc = state.born.astimezone(timezone.utc)
        return [
            float(state.version_no),
            t_since_claim_start,
            state.prev_lifetime_sec,
            mean_interval,
            math.nan,  # horizon_s — 상태형 claim이라 학습 때도 항상 NaN
            state.delta,
            float(born_utc.hour),
            float(born_utc.isoweekday()),  # 월=1 … 일=7 (학습의 dayofweek+1과 동일)
            route_med_gap,
        ]
