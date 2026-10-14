"""도착 기준 재채점 — "도착했을 때 E-Gen이 말한 병상이 남아 있었나"로 모델과 기준선을 같이 잰다.

    python -m reliability.arrival_eval                       # 기본: 9/7~9/28 기준선 학습, 9/29~ 채점
    python -m reliability.arrival_eval --eval-since 2026-09-29 --out <json>

기존 채점(live_board·replay_demo)의 구멍을 메우려고 만들었다. 기존 방식은
  1) 실패를 |Δ|≥3(양방향)으로 봐서 병상이 늘어난 것도 실패로 치고, 2석→0석(만실)은
     |Δ|=2라 "유지"로 쳤다 — 구급대원에게 가장 중요한 실패가 빠졌다
  2) 지표가 적중률이라 그냥 "안 바뀐다"고 찍어도 94%가 나왔다
  3) 기준선이 "E-Gen 100% 신뢰"뿐이라, 단순한 확률 기준선을 이기는지는 몰랐다
  4) 정답이 E-Gen 자신이라 살아 있는 유령(probe_regime)이 쉬운 정답으로 섞였다

여기서는
- 실패 정의 3가지를 나란히 낸다 — `full`(도착 때 0석 이하, **새 주 정의**),
  `drop`(θ석 이상 감소), `sym`(|Δ|≥θ, 모델 학습 라벨 — 비교용)
- 표본은 요청 시점 E-Gen 값이 1석 이상인 병원 × 필드(구급대원이 실제로 고를 만한 것)
- 도착 시각은 폴링 간격의 배수(20·40·60분)로 둬서 도착 스냅샷이 정확히 맞게 한다
- 예측기: E-Gen 그대로(실패확률 0) / 전체 평균 / 요청 때 병상 수별 평균 / 병원별 평균 /
  모델(1 − rArrive, 화면 값 그대로) / 조건부 모델(1 − S(a+h)/S(a)). 평균류는 **기준선
  학습 구간**에서만 구한다
- 지표: 실패율 · Brier · Brier skill(전체 평균 대비) · AUC · 상위 10% 경고로 잡은 실패 비율
- 유령 구간(probe_regime 상대 기준) 포함 / 제외 / 유령만으로 나눠 낸다

⚠ 모델은 `sym` 라벨로 학습됐다. `full`·`drop`에 대한 모델 확률은 그 목적으로 만든
값이 아니므로 Brier(확률 정직성)보다 AUC(순위)를 먼저 볼 것. 유령은 run이 끝나야
판정되는 사후 이름표라 분석용 분할이지, 서빙 시점에 쓸 수 있는 정보가 아니다.
"""
from __future__ import annotations

import argparse
import bisect
import json
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import serve
from .engine import _BED_OP, _DEFAULT_SNAPSHOT_DIR, BedReliabilityEngine
from .probe_regime import FIELDS, KST, MINUS_ONE_IS_VALUE, _is_ghost, collect, thresholds

THETA = 3
#: 폴링 간격(20분)의 배수 — 도착 스냅샷이 요청 뒤 정확히 k번째 폴링이 되게 한다
HORIZONS_MIN = (20, 40, 60)
#: 도착 스냅샷이 목표 시각에서 이만큼 넘게 벗어나면(수집 공백) 채점하지 않는다
ARRIVAL_TOLERANCE = timedelta(minutes=8)
ALERT_SHARE = 0.10
#: 병원별 평균을 전체 평균 쪽으로 당기는 강도(가상 표본 수) — 표본 적은 병원이 0/1로 튀지 않게
HOSPITAL_PRIOR_N = 20
LABELS = ("full", "drop", "sym")
SUBSETS = ("all", "noGhost", "ghostOnly")
DEFAULT_FIT_SINCE = date(2026, 9, 7)
#: 모델(hvec ext0923, 다필드 cutoff 9/22)·재보정(9/23~9/28 적합)이 모두 9/28까지의 데이터를 썼다
DEFAULT_EVAL_SINCE = date(2026, 9, 29)


def _value(item: dict | None, field: str) -> int | None:
    if not item or field not in item:
        return None
    try:
        v = int(str(item[field]).strip())
    except ValueError:
        return None
    return None if v == -1 and field not in MINUS_ONE_IS_VALUE else v


def _label(before: int, after: int) -> dict[str, bool]:
    return {"full": after <= 0, "drop": before - after >= THETA, "sym": abs(after - before) >= THETA}


def _bucket(before: int) -> str:
    if before <= 2:
        return str(before)
    if before <= 5:
        return "3-5"
    if before <= 10:
        return "6-10"
    return ">10"


def _bed_lines(snapshot_dir: Path, since: date):
    """병상 폴링 줄을 파일 순서대로: (UTC 시각, 원본 줄, 레코드). 원본 줄을 전부 들고 있으면
    28일치로 1GB 가까이 돼서, 값을 읽을 때와 엔진에 먹일 때 두 번 흘려 읽는다."""
    for path in sorted(snapshot_dir.glob("*.jsonl")):
        if len(path.stem) == 10 and date.fromisoformat(path.stem) < since:
            continue
        with path.open("rb") as f:
            for raw in f:
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if record.get("operation") != _BED_OP or "error" in record or not record.get("items"):
                    continue
                yield datetime.fromisoformat(record["ts"]).astimezone(timezone.utc), raw, record


def load(snapshot_dir: Path, since: date):
    """병상 폴링을 시각순으로: (UTC 시각, {필드: {hpid: 값}})."""
    polls = []
    for ts, _, record in _bed_lines(snapshot_dir, since):
        values = {field: {} for field in FIELDS}
        for item in record["items"]:
            hpid = (item.get("hpid") or "").strip()
            for field in FIELDS:
                v = _value(item, field)
                if hpid and v is not None:
                    values[field][hpid] = v
        polls.append((ts, values))
    if any(a[0] > b[0] for a, b in zip(polls, polls[1:])):
        raise SystemExit("스냅샷 줄이 시각순이 아니다 — 엔진에 순서대로 먹일 수 없다")
    return polls


def _arrival_index(times: list[datetime], i: int, minutes: int) -> int | None:
    target = times[i] + timedelta(minutes=minutes)
    j = bisect.bisect_left(times, target - ARRIVAL_TOLERANCE)
    if j >= len(times) or abs(times[j] - target) > ARRIVAL_TOLERANCE:
        return None
    return j


def ghost_intervals(snapshot_dir: Path, since: date) -> dict[tuple[str, str], list[tuple[datetime, datetime]]]:
    runs, *_ = collect(snapshot_dir, since, None)
    rule = thresholds(runs)
    out: dict[tuple[str, str], list[tuple[datetime, datetime]]] = defaultdict(list)
    for run in runs:
        if _is_ghost(run, rule):
            out[(run.hpid, run.field)].append((run.start, run.last))
    return out


def _in_ghost(spans: list[tuple[datetime, datetime]], ts: datetime) -> bool:
    return any(start <= ts <= last for start, last in spans)


def fit_baselines(polls, times, fit_until: datetime):
    """기준선 학습 구간의 실패율: (필드, 라벨, 도착분) → 전체 / 병상 수 구간별 / 병원별."""
    counts: dict = defaultdict(lambda: [0, 0])  # key -> [실패, 표본]
    for i, (ts, values) in enumerate(polls):
        if ts >= fit_until:
            break
        for minutes in HORIZONS_MIN:
            j = _arrival_index(times, i, minutes)
            if j is None or times[j] >= fit_until:
                continue
            for field, now in values.items():
                later = polls[j][1][field]
                for hpid, before in now.items():
                    after = later.get(hpid)
                    if before < 1 or after is None:
                        continue
                    for name, failed in _label(before, after).items():
                        for key in ((field, name, minutes), (field, name, minutes, "b", _bucket(before)),
                                    (field, name, minutes, "h", hpid)):
                            counts[key][0] += failed
                            counts[key][1] += 1
    return counts


def _rate(counts, key, fallback: float, prior_n: int = 0) -> float:
    failed, n = counts.get(key, (0, 0))
    return (failed + prior_n * fallback) / (n + prior_n) if n + prior_n else fallback


def _auc(score: np.ndarray, y: np.ndarray) -> float | None:
    n1 = int(y.sum())
    n0 = len(y) - n1
    if not n1 or not n0:
        return None
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score))
    sorted_score = score[order]
    # 동점은 평균 순위 — 상수 예측기가 정확히 0.5가 되게
    _, start, counts = np.unique(sorted_score, return_index=True, return_counts=True)
    avg = start + (counts - 1) / 2.0 + 1
    ranks[order] = np.repeat(avg, counts)
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _capture(score: np.ndarray, y: np.ndarray, rng: np.random.Generator) -> float | None:
    """위험 점수 상위 ALERT_SHARE에 경고를 걸었을 때 실제 실패 중 잡힌 비율(동점은 무작위)."""
    if not y.sum():
        return None
    k = max(1, int(round(len(y) * ALERT_SHARE)))
    order = np.lexsort((rng.random(len(y)), -score))
    return float(y[order[:k]].sum() / y.sum())


def metrics(preds: dict[str, np.ndarray], y: np.ndarray, clim_brier: float, seed: int) -> dict:
    out = {"n": int(len(y)), "failRate": float(y.mean()) if len(y) else None, "predictors": {}}
    if not len(y):
        return out
    rng = np.random.default_rng(seed)
    for name, p in preds.items():
        brier = float(np.mean((p - y) ** 2))
        out["predictors"][name] = {
            "brier": brier,
            "bss": 1 - brier / clim_brier if clim_brier else None,
            "auc": _auc(p, y),
            "capture": _capture(p, y, rng),
        }
    return out


def build_tables(snapshot_dir: Path, fit_since: date, eval_since: date) -> tuple[dict, set[str]]:
    """채점 표본을 (필드, 도착분)별 배열 묶음으로 만든다 — 채점(score)과 분리해 둬야 부트스트랩·
    손 계산 대조 같은 검증이 같은 표본을 그대로 쓸 수 있다."""
    polls = load(snapshot_dir, fit_since)
    if len(polls) < 10:
        raise SystemExit(f"병상 폴링이 부족하다({len(polls)}회) — {snapshot_dir}")
    times = [p[0] for p in polls]
    eval_from = datetime.combine(eval_since, datetime.min.time(), KST).astimezone(timezone.utc)
    print(f"폴링 {len(polls):,}회 · 기준선 학습 {times[0]:%m-%d} ~ {eval_from:%m-%d %H:%M}Z · "
          f"채점 {eval_from:%m-%d %H:%M}Z ~ {times[-1]:%m-%d %H:%M}Z")

    counts = fit_baselines(polls, times, eval_from)
    ghosts = ghost_intervals(snapshot_dir, fit_since)

    # 엔진은 빈 상태에서 시작해 기준선 학습 구간부터 시각순으로 먹인다(리듬 피처 워밍업)
    with tempfile.TemporaryDirectory() as empty:
        engine = BedReliabilityEngine(snapshot_dir=empty)
    served = set(engine.fields)
    # rows[(필드, 도착분)] = 리스트 of (before, after, hpid, pred_t, age, sigma, ghost, 요청 시각)
    rows: dict[tuple[str, int], list] = defaultdict(list)
    for i, (ts, raw, _) in enumerate(_bed_lines(snapshot_dir, fit_since)):
        if i >= len(polls) or ts != polls[i][0]:
            raise SystemExit(f"두 번째 읽기의 {i}번째 폴링이 첫 읽기와 다르다 — 값과 예측이 어긋난다")
        engine._ingest_line(raw)
        if ts < eval_from:
            continue
        values = polls[i][1]
        preds = engine.predict(ts)
        for minutes in HORIZONS_MIN:
            j = _arrival_index(times, i, minutes)
            if j is None:
                continue
            for field, now in values.items():
                later = polls[j][1][field]
                field_preds = preds.get(field, {})
                for hpid, before in now.items():
                    after = later.get(hpid)
                    if before < 1 or after is None:
                        continue
                    p = field_preds.get(hpid)
                    rows[(field, minutes)].append((
                        before, after, hpid,
                        p.pred_t_sec if p else np.nan, p.age_sec if p else np.nan,
                        p.sigma if p else 1.0,
                        _in_ghost(ghosts.get((hpid, field), []), ts.astimezone(KST)),
                        ts,
                    ))

    tables: dict = {}
    for (field, minutes), recs in sorted(rows.items()):
        before = np.array([r[0] for r in recs])
        after = np.array([r[1] for r in recs])
        hpids = [r[2] for r in recs]
        pred_t = np.array([r[3] for r in recs], dtype=float)
        age = np.array([r[4] for r in recs], dtype=float)
        sigma = np.array([r[5] for r in recs], dtype=float)
        ghost = np.array([r[6] for r in recs], dtype=bool)
        has_model = ~np.isnan(pred_t)
        safe_t, safe_age = np.nan_to_num(pred_t, nan=1.0), np.nan_to_num(age)
        r_arrive = np.where(has_model, serve.at(safe_t, safe_age, minutes * 60.0, sigma=sigma), np.nan)
        # 화면의 rArrive는 무조건부 S(a+h)라 "오래 안 바뀐 값은 현실에선 틀렸을 수 있다"를 담는다.
        # E-Gen 다음 값으로 채점하는 여기서는 "지금까지 버텼다"를 조건으로 건 S(a+h)/S(a)가 공정한
        # 비교 대상이다(live_board의 캘리브레이션 쌍과 같은 이유) — 둘 다 낸다
        s_now = serve.authority(safe_t, safe_age, sigma=sigma)
        r_cond = np.where(has_model, np.clip(r_arrive / np.maximum(s_now, 1e-12), 0.0, 1.0), np.nan)
        table = {
            "ts": [r[7] for r in recs], "before": before, "after": after, "hpid": hpids,
            "age": age, "ghost": ghost, "hasModel": has_model, "rArrive": r_arrive, "rCond": r_cond,
            "y": {}, "clim": {}, "preds": {},
        }
        for label in LABELS:
            y = np.array([_label(b, a)[label] for b, a in zip(before, after)], dtype=float)
            clim = _rate(counts, (field, label, minutes), float(y.mean()))
            preds = {
                "egen": np.zeros(len(y)),
                "global": np.full(len(y), clim),
                "byBeds": np.array([_rate(counts, (field, label, minutes, "b", _bucket(b)), clim) for b in before]),
                "byHospital": np.array([_rate(counts, (field, label, minutes, "h", h), clim, HOSPITAL_PRIOR_N)
                                        for h in hpids]),
            }
            if field in served:
                preds["model"] = 1.0 - r_arrive
                preds["modelCond"] = 1.0 - r_cond
            table["y"][label], table["clim"][label], table["preds"][label] = y, clim, preds
        tables[(field, minutes)] = table
    return tables, served


def subset_mask(table: dict, subset: str, served: bool) -> np.ndarray:
    ghost = table["ghost"]
    mask = {"all": np.ones(len(ghost), bool), "noGhost": ~ghost, "ghostOnly": ghost}[subset]
    # 모델이 있는 필드는 모델 예측이 있는 행만 — 모든 예측기를 같은 표본으로 비교한다
    return mask & table["hasModel"] if served else mask


def score(tables: dict, served: set[str], seed: int) -> dict:
    result: dict = {"fields": {}, "servedFields": sorted(served)}
    for (field, minutes), table in tables.items():
        per_field = result["fields"].setdefault(field, {})
        for label in LABELS:
            y, clim, preds = table["y"][label], table["clim"][label], table["preds"][label]
            for subset in SUBSETS:
                mask = subset_mask(table, subset, field in served)
                ys = y[mask]
                clim_brier = float(np.mean((clim - ys) ** 2)) if len(ys) else 0.0
                per_field.setdefault(f"{minutes}m", {}).setdefault(label, {})[subset] = metrics(
                    {k: v[mask] for k, v in preds.items()}, ys, clim_brier, seed)
    return result


def _print(result: dict) -> None:
    for field, by_h in result["fields"].items():
        print(f"\n══ {field} {'(모델 서빙)' if field in result['servedFields'] else '(모델 없음 — 기준선만)'} ══")
        for horizon, by_label in by_h.items():
            for label, by_subset in by_label.items():
                for subset, m in by_subset.items():
                    if not m["n"]:
                        continue
                    head = f"  {horizon:>3s} {label:<4s} {subset:<9s} n={m['n']:>7,} 실패 {m['failRate']:6.2%} │"
                    cells = []
                    for name, s in m["predictors"].items():
                        auc = f"{s['auc']:.3f}" if s["auc"] is not None else "  -  "
                        cap = f"{s['capture']:.0%}" if s["capture"] is not None else " - "
                        bss = f"{s['bss']:+.3f}" if s["bss"] is not None else "  -   "
                        cells.append(f"{name} BSS {bss} AUC {auc} 포착 {cap}")
                    print(head + " │ ".join(cells))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshots", type=Path, default=_DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--fit-since", type=date.fromisoformat, default=DEFAULT_FIT_SINCE)
    parser.add_argument("--eval-since", type=date.fromisoformat, default=DEFAULT_EVAL_SINCE)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    result = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fitSince": args.fit_since.isoformat(),
        "evalSince": args.eval_since.isoformat(),
        "theta": THETA,
        "horizonsMin": list(HORIZONS_MIN),
        "alertShare": ALERT_SHARE,
    } | score(*build_tables(args.snapshots, args.fit_since, args.eval_since), args.seed)
    _print(result)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n수치 저장: {args.out}")


if __name__ == "__main__":
    main()
