"""모델 로드·스냅샷 워밍업·예측을 묶은 병상 정보 신뢰도 서빙 엔진.

send_to_hub.py가 사이클마다 이렇게 쓴다 (상태가 사이클 간 이어져야 하므로
프로세스당 인스턴스 하나를 계속 들고 있어야 한다):

    engine = BedReliabilityEngine()          # 프로세스 시작 시 1회 (워밍업 포함)
    engine.ingest_snapshots()                # 사이클마다: 스냅샷 새 줄 증분 반영
    engine.observe_rows(bed_rows, now)       # 사이클마다: 이번 조회 rows 반영
    preds = engine.predict(now)              # hpid -> BedPrediction

관측 소스가 둘인 이유: 이 모델의 피처는 "병원의 평소 갱신 리듬" 같은 이력
통계인데, send_to_hub.py 자체는 30분에 한 번만 조회한다. 같은 장비에서
snapshot_nationwide.bat이 20분 주기로 쌓는 스냅샷 JSONL을 증분으로 읽으면
학습 데이터와 같은 해상도의 이력을 공짜로 얻는다. **단, 스냅샷이 없어도
죽지 않는다** — 그 경우 이번 사이클 rows(30분 해상도)만으로 동작하고,
피처 해상도가 조금 거칠어질 뿐이다(숨은 의존을 만들지 않는다는
send_to_hub.py._build_score_inputs()의 원칙과 같음).

호출 순서 주의: 사이클 안에서 반드시 ingest_snapshots() → observe_rows()
순서여야 한다. ClaimTracker가 과거 관측을 버리는 단조 규칙을 쓰므로,
이번 사이클 rows(현재 시각)를 먼저 넣으면 그보다 과거인 스냅샷 줄들이
전부 무시된다.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import serve
from .features import FEATURES, ClaimTracker

#: Authority가 이 값 아래로 떨어질 때까지 남은 시간을 ttlSec으로 내보낸다
#: (AIROOKIE-EGEN.md §5-1 예제의 임계값).
AUTHORITY_TTL_THRESHOLD = 0.8

#: 서빙 권장 모델 (AIROOKIE-EGEN.md §5 "서빙에는 이쪽 권장"). θ=3은
#: "3병상 이상 어긋나면 무효" 기준으로 학습된 모델이라는 뜻.
_DEFAULT_MODEL = Path(__file__).resolve().parent / "model" / "aft_egen_theta3_ext0923.json"
_DEFAULT_GAP_TABLE = Path(__file__).resolve().parent / "model" / "route_med_gap.json"
_DEFAULT_SNAPSHOT_DIR = (
    Path(__file__).resolve().parents[1] / "data" / "snapshots_nationwide"
)

#: 스냅샷에서 병상 관측으로 읽는 오퍼레이션 (snapshot.py의 REALTIME_OPS 중 병상).
_BED_OP = "getEmrrmRltmUsefulSckbdInfoInqire"


@dataclass
class BedPrediction:
    """병원 1곳의 현재 claim-version에 대한 신뢰도 예측."""

    pred_t_sec: float  #: 모델의 예측 생존시간(초)
    born: datetime  #: 현재 버전 탄생(값이 이 값으로 바뀐 게 관측된) 시각, aware UTC
    age_sec: float  #: 예측 시점 기준 버전 나이(초)
    authority: float  #: 지금 이 병상 숫자를 믿어도 될 확률
    ttl_sec: float  #: authority가 임계(0.8) 아래로 떨어질 때까지 남은 초


class BedReliabilityEngine:
    def __init__(
        self,
        model_path: Path | str = _DEFAULT_MODEL,
        gap_table_path: Path | str = _DEFAULT_GAP_TABLE,
        snapshot_dir: Path | str = _DEFAULT_SNAPSHOT_DIR,
        warmup_days: int = 3,
    ) -> None:
        # xgboost는 이 엔진에만 필요해서 모듈 최상단이 아니라 여기서 import한다
        # — 미설치 환경이면 엔진 생성만 실패하고, send_to_hub.py의 try/except가
        # bedReliability 없이 기존 경로 그대로 동작하게 한다.
        import xgboost as xgb

        self._booster = xgb.Booster()
        self._booster.load_model(str(model_path))
        self.model_tag = Path(model_path).stem

        loaded_names = self._booster.feature_names
        if loaded_names != FEATURES:
            # 재학습 모델을 교체할 때 피처 정의가 어긋나면 예측이 조용히
            # 엉뚱해진다 — 이름 대조로 그 자리에서 실패시킨다.
            raise ValueError(
                f"모델 피처와 서빙 피처가 다르다: model={loaded_names} serving={FEATURES}"
            )

        table = json.loads(Path(gap_table_path).read_text(encoding="utf-8"))
        self._gap_by_hpid: dict[str, float] = {
            k: float(v) for k, v in table["hospitals"].items()
        }
        #: 테이블에 없는(신규) 병원의 fallback — 전국 1개 모델을 신규 병원에
        #: 그대로 적용해도 된다는 실측(AIROOKIE-EGEN.md §6-1, zero-shot 99%)에
        #: 따라 별도 예외 처리 없이 전국 중위값만 쓴다.
        self._gap_national: float = float(table["nationalMedianSec"])

        self._tracker = ClaimTracker()
        self._snapshot_dir = Path(snapshot_dir)
        self._warmup_days = warmup_days
        self._offsets: dict[str, int] = {}  # 파일명 -> 읽은 바이트 수 (증분 읽기)
        self.warmed_up_observations = self.ingest_snapshots()

    # ── 관측 입력 ────────────────────────────────────────────────────────────

    def ingest_snapshots(self) -> int:
        """스냅샷 JSONL의 아직 안 읽은 부분을 tracker에 반영하고, 반영한
        관측(병원×시각) 수를 돌려준다. 스냅샷 폴더가 없으면 0 — 엔진은
        이번 사이클 rows만으로 계속 동작한다."""
        if not self._snapshot_dir.is_dir():
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self._warmup_days)).date()
        fed = 0
        for path in sorted(self._snapshot_dir.glob("*.jsonl")):
            try:
                file_date = datetime.strptime(path.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if file_date < cutoff:
                continue
            fed += self._ingest_file(path)
        return fed

    def _ingest_file(self, path: Path) -> int:
        offset = self._offsets.get(path.name, 0)
        fed = 0
        with path.open("rb") as f:
            f.seek(offset)
            for raw_line in f:
                if not raw_line.endswith(b"\n"):
                    # 수집기가 쓰는 중인 마지막 줄 — 다음 사이클에 다시 읽는다.
                    break
                offset += len(raw_line)
                fed += self._ingest_line(raw_line)
        self._offsets[path.name] = offset
        return fed

    def _ingest_line(self, raw_line: bytes) -> int:
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            return 0
        if record.get("operation") != _BED_OP or "error" in record:
            return 0
        try:
            ts = datetime.fromisoformat(record["ts"]).astimezone(timezone.utc)
        except (KeyError, ValueError):
            return 0
        return self._observe_items(record.get("items") or [], ts)

    def observe_rows(self, bed_rows: list[dict], ts: datetime) -> int:
        """이번 사이클에 실 API에서 받은 병상 rows를 관측으로 반영한다."""
        return self._observe_items(bed_rows, ts.astimezone(timezone.utc))

    def _observe_items(self, items: list[dict], ts: datetime) -> int:
        fed = 0
        for item in items:
            hpid = (item.get("hpid") or "").strip()
            raw = item.get("hvec")
            if not hpid or raw is None or str(raw).strip() == "":
                continue  # 파이프라인과 동일 — hvec 미제공 관측은 건너뛴다
            try:
                value = int(str(raw).strip())
            except ValueError:
                continue
            self._tracker.observe(hpid, ts, value)
            fed += 1
        return fed

    # ── 예측 ────────────────────────────────────────────────────────────────

    def predict(self, now: datetime) -> dict[str, BedPrediction]:
        """추적 중인 모든 병원의 현재 버전에 대한 예측을 돌려준다."""
        hpids: list[str] = []
        rows: list[list[float]] = []
        for hpid in self._tracker.hpids():
            gap = self._gap_by_hpid.get(hpid, self._gap_national)
            row = self._tracker.feature_row(hpid, gap)
            if row is None:
                continue
            hpids.append(hpid)
            rows.append(row)
        if not rows:
            return {}

        import xgboost as xgb

        matrix = xgb.DMatrix(
            np.asarray(rows, dtype=np.float32), missing=np.nan, feature_names=FEATURES
        )
        # infosurv.fit.predict()와 동일한 호출 — early stopping으로 고른
        # best_iteration까지만 쓴다.
        best = getattr(self._booster, "best_iteration", None)
        iteration_range = (0, best + 1) if best is not None else None
        pred_t = self._booster.predict(matrix, iteration_range=iteration_range)

        now_utc = now.astimezone(timezone.utc)
        results: dict[str, BedPrediction] = {}
        for hpid, pred in zip(hpids, pred_t):
            pred = float(pred)
            if not math.isfinite(pred) or pred <= 0:
                continue
            state = self._tracker.get(hpid)
            age = max((now_utc - state.born).total_seconds(), 0.0)
            results[hpid] = BedPrediction(
                pred_t_sec=pred,
                born=state.born,
                age_sec=age,
                authority=float(serve.authority(pred, age)),
                ttl_sec=float(serve.ttl(pred, age, AUTHORITY_TTL_THRESHOLD)),
            )
        return results
