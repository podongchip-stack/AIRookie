"""모델 로드·스냅샷 워밍업·예측을 묶은 병상 정보 신뢰도 서빙 엔진.

send_to_hub.py가 사이클마다 이렇게 쓴다 (상태가 사이클 간 이어져야 하므로
프로세스당 인스턴스 하나를 계속 들고 있어야 한다):

    engine = BedReliabilityEngine()          # 프로세스 시작 시 1회 (워밍업 포함)
    engine.ingest_snapshots()                # 사이클마다: 스냅샷 새 줄 증분 반영
    engine.observe_rows(bed_rows, now)       # 사이클마다: 이번 조회 rows 반영
    preds = engine.predict(now)              # field -> (hpid -> BedPrediction)

**다필드(2026-09-28 확장)**: 응급실 일반병상(hvec) 외에 train_field.py가
채택 관문을 통과시킨 필드들(수술실 hvoc·입원실 hvgc·소아 hv28 등)을
model/ 폴더에서 자동 발견해 같이 서빙한다 — 필드마다 전용 모델·리듬
테이블·(있으면) 재보정 상수와 독립 tracker를 가진다. 관문에서 기각된
필드(중환자실 hvicc — 이벤트 부족, 축적 후 재시도)는 파일이 없으므로
자연히 빠진다.

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
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from . import serve
from .features import FEATURES, ClaimTracker
from .severe import SEVERE_OP, SevereTracker

#: Authority가 이 값 아래로 떨어질 때까지 남은 시간을 ttlSec으로 내보낸다
#: (AIROOKIE-EGEN.md §5-1 예제의 임계값).
AUTHORITY_TTL_THRESHOLD = 0.8

_MODEL_DIR = Path(__file__).resolve().parent / "model"

#: hvec(응급실 일반병상) 서빙 권장 모델 (AIROOKIE-EGEN.md §5 "서빙에는 이쪽 권장").
#: θ=3은 "3병상 이상 어긋나면 무효" 기준으로 학습된 모델이라는 뜻.
_DEFAULT_MODEL = _MODEL_DIR / "aft_egen_theta3_ext0923.json"
_DEFAULT_GAP_TABLE = _MODEL_DIR / "route_med_gap.json"
#: hvec 잔차 재보정 상수 (calibrate.py가 생성). 없으면 raw로 동작 — fail-soft.
_DEFAULT_RECAL = _MODEL_DIR / "recalibration.json"
_DEFAULT_SNAPSHOT_DIR = (
    Path(__file__).resolve().parents[1] / "data" / "snapshots_nationwide"
)

#: train_field.py 산출 모델 파일명 규칙 — 여기 맞는 파일이 있으면 그 필드를 서빙한다.
_FIELD_MODEL_RE = re.compile(r"^aft_egen_(hv\w+?)_theta(\d)\.json$")

#: 스냅샷에서 병상 관측으로 읽는 오퍼레이션 (snapshot.py의 REALTIME_OPS 중 병상).
_BED_OP = "getEmrrmRltmUsefulSckbdInfoInqire"


@dataclass
class BedPrediction:
    """병원 1곳 × 필드 1개의 현재 claim-version에 대한 신뢰도 예측."""

    pred_t_sec: float  #: 예측 생존시간(초) — 재보정 상수가 있으면 μR 반영된 값
    born: datetime  #: 현재 버전 탄생(값이 이 값으로 바뀐 게 관측된) 시각, aware UTC
    age_sec: float  #: 예측 시점 기준 버전 나이(초)
    authority: float  #: 지금 이 병상 숫자를 믿어도 될 확률
    ttl_sec: float  #: authority가 임계(0.8) 아래로 떨어질 때까지 남은 초
    sigma: float  #: 생존곡선 척도 — raw면 1.0, 재보정이 있으면 σR
    model_tag: str  #: 이 예측을 만든 모델 식별자 (+recal 접미 포함)


@dataclass
class _FieldServing:
    """필드 하나의 서빙 자산 묶음."""

    field: str
    booster: Any
    model_tag: str
    mu_r: float
    sigma: float
    gap_by_hpid: dict[str, float]
    gap_national: float
    tracker: ClaimTracker
    minus_one_missing: bool  #: hvec 외 필드는 -1이 미입력(실측, egen/mapper.py)


def _load_recal(path: Path, model_tag: str) -> tuple[float, float, str]:
    """재보정 상수 로드. 없거나 다른 모델 것이면 raw(0, 1)."""
    if not path.is_file():
        return 0.0, 1.0, ""
    recal = json.loads(path.read_text(encoding="utf-8"))
    if recal.get("modelTag") != model_tag:
        print(f"  [reliability] {path.name}이 다른 모델({recal.get('modelTag')}) 것이라"
              f" 무시 — calibrate.py 재실행 필요")
        return 0.0, 1.0, ""
    return float(recal["muR"]), float(recal["sigmaR"]), "+recal"


class BedReliabilityEngine:
    def __init__(
        self,
        model_path: Path | str = _DEFAULT_MODEL,
        gap_table_path: Path | str = _DEFAULT_GAP_TABLE,
        snapshot_dir: Path | str = _DEFAULT_SNAPSHOT_DIR,
        # 축적 전체를 읽는다(60일이면 현재 축적을 전부 덮고, 파싱 수 분).
        # 예전 기본값 3일은 3일 넘게 이어진 세그먼트의 version_no를 절단해
        # 학습 분포와 어긋나는 문제가 있었다(2026-09-28 검토에서 확인).
        warmup_days: int = 60,
    ) -> None:
        # xgboost는 이 엔진에만 필요해서 모듈 최상단이 아니라 여기서 import한다
        # — 미설치 환경이면 엔진 생성만 실패하고, send_to_hub.py의 try/except가
        # bedReliability 없이 기존 경로 그대로 동작하게 한다.
        self._fields: dict[str, _FieldServing] = {}
        self._fields["hvec"] = self._load_field(
            "hvec", Path(model_path), Path(gap_table_path), _DEFAULT_RECAL,
            minus_one_missing=False,
        )
        self._discover_extra_fields()

        #: hvec 모델 식별자 — 기존 로그·호출부 호환용 별칭.
        self.model_tag = self._fields["hvec"].model_tag

        #: 중증질환 수용가능 신고 추적 — 모델 없음, 규칙 기반 신선도 전용
        #: (severe.py 모듈 docstring 참고). 같은 스냅샷 증분 패스에서 같이 읽는다.
        self.severe = SevereTracker()
        self._snapshot_dir = Path(snapshot_dir)
        self._warmup_days = warmup_days
        self._offsets: dict[str, int] = {}  # 파일명 -> 읽은 바이트 수 (증분 읽기)
        self.warmed_up_observations = self.ingest_snapshots()

    def _load_field(self, field: str, model_path: Path, gap_path: Path,
                    recal_path: Path, *, minus_one_missing: bool) -> _FieldServing:
        import xgboost as xgb

        booster = xgb.Booster()
        booster.load_model(str(model_path))
        if booster.feature_names != FEATURES:
            # 재학습 모델을 교체할 때 피처 정의가 어긋나면 예측이 조용히
            # 엉뚱해진다 — 이름 대조로 그 자리에서 실패시킨다.
            raise ValueError(
                f"{field} 모델 피처와 서빙 피처가 다르다: "
                f"model={booster.feature_names} serving={FEATURES}"
            )
        model_tag = model_path.stem
        mu_r, sigma, suffix = _load_recal(recal_path, model_tag)
        table = json.loads(gap_path.read_text(encoding="utf-8"))
        return _FieldServing(
            field=field,
            booster=booster,
            model_tag=model_tag + suffix,
            mu_r=mu_r,
            sigma=sigma,
            gap_by_hpid={k: float(v) for k, v in table["hospitals"].items()},
            # 테이블에 없는(신규) 병원은 전국 중위값 — 전국 1개 모델을 신규
            # 병원에 zero-shot 적용해도 native의 99%라는 실측(§6-1)에 따름.
            gap_national=float(table["nationalMedianSec"]),
            tracker=ClaimTracker(),
            minus_one_missing=minus_one_missing,
        )

    def _discover_extra_fields(self) -> None:
        """model/ 폴더에서 train_field.py 산출 모델을 찾아 서빙에 올린다.
        리듬 테이블이 없으면 그 필드만 건너뛴다(경고만)."""
        for path in sorted(_MODEL_DIR.glob("aft_egen_hv*_theta*.json")):
            match = _FIELD_MODEL_RE.match(path.name)
            if not match:
                continue
            field = match.group(1)
            gap_path = _MODEL_DIR / f"route_med_gap_{field}.json"
            if not gap_path.is_file():
                print(f"  [reliability] {field} 모델은 있는데 리듬 테이블이 없어 건너뜀"
                      f" — train_field.py 재실행 필요")
                continue
            self._fields[field] = self._load_field(
                field, path, gap_path, _MODEL_DIR / f"recalibration_{field}.json",
                minus_one_missing=True,
            )

    @property
    def fields(self) -> list[str]:
        return list(self._fields)

    # ── 관측 입력 ────────────────────────────────────────────────────────────

    def ingest_snapshots(self) -> int:
        """스냅샷 JSONL의 아직 안 읽은 부분을 tracker에 반영하고, 반영한
        관측(병원×필드×시각) 수를 돌려준다. 스냅샷 폴더가 없으면 0 — 엔진은
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
        operation = record.get("operation")
        if operation not in (_BED_OP, SEVERE_OP) or "error" in record:
            return 0
        try:
            ts = datetime.fromisoformat(record["ts"]).astimezone(timezone.utc)
        except (KeyError, ValueError):
            return 0
        items = record.get("items") or []
        if operation == _BED_OP:
            return self._observe_items(items, ts)
        return sum(self.severe.observe_row(row, ts) for row in items)

    def observe_rows(self, bed_rows: list[dict], ts: datetime) -> int:
        """이번 사이클에 실 API에서 받은 병상 rows를 관측으로 반영한다."""
        return self._observe_items(bed_rows, ts.astimezone(timezone.utc))

    def observe_severe_rows(self, severe_rows: list[dict], ts: datetime) -> int:
        """이번 사이클에 실 API에서 받은 중증질환 rows를 관측으로 반영한다."""
        ts_utc = ts.astimezone(timezone.utc)
        return sum(self.severe.observe_row(row, ts_utc) for row in severe_rows)

    def _observe_items(self, items: list[dict], ts: datetime) -> int:
        fed = 0
        for item in items:
            hpid = (item.get("hpid") or "").strip()
            if not hpid:
                continue
            for serving in self._fields.values():
                raw = item.get(serving.field)
                if raw is None or str(raw).strip() == "":
                    continue  # 학습 파이프라인과 동일 — 미제공 관측은 건너뛴다
                try:
                    value = int(str(raw).strip())
                except ValueError:
                    continue
                if serving.minus_one_missing and value == -1:
                    continue
                serving.tracker.observe(hpid, ts, value)
                fed += 1
        return fed

    # ── 예측 ────────────────────────────────────────────────────────────────

    def predict(self, now: datetime) -> dict[str, dict[str, BedPrediction]]:
        """필드별 × 병원별 현재 버전 예측: {field: {hpid: BedPrediction}}."""
        return {
            field: self._predict_field(serving, now)
            for field, serving in self._fields.items()
        }

    def _predict_field(self, serving: _FieldServing, now: datetime) -> dict[str, BedPrediction]:
        hpids: list[str] = []
        rows: list[list[float]] = []
        for hpid in serving.tracker.hpids():
            gap = serving.gap_by_hpid.get(hpid, serving.gap_national)
            row = serving.tracker.feature_row(hpid, gap)
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
        best = getattr(serving.booster, "best_iteration", None)
        iteration_range = (0, best + 1) if best is not None else None
        pred_t = serving.booster.predict(matrix, iteration_range=iteration_range)

        now_utc = now.astimezone(timezone.utc)
        results: dict[str, BedPrediction] = {}
        for hpid, pred in zip(hpids, pred_t):
            pred = float(pred)
            if not math.isfinite(pred) or pred <= 0:
                continue
            # 재보정: 위치 이동(μR)은 예측 생존시간에 흡수하고, 척도(σR)는
            # 생존곡선 계산에 넘긴다 — hub도 같은 σ를 받아 같은 곡선을 그린다.
            pred = pred * math.exp(serving.mu_r)
            state = serving.tracker.get(hpid)
            age = max((now_utc - state.born).total_seconds(), 0.0)
            results[hpid] = BedPrediction(
                pred_t_sec=pred,
                born=state.born,
                age_sec=age,
                authority=float(serve.authority(pred, age, sigma=serving.sigma)),
                ttl_sec=float(serve.ttl(pred, age, AUTHORITY_TTL_THRESHOLD, sigma=serving.sigma)),
                sigma=serving.sigma,
                model_tag=serving.model_tag,
            )
        return results
