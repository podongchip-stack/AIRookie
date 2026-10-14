"""레짐 4분할 — E-Gen 병상 필드에 숨은 "살아 있는 유령"을 스냅샷만으로 재는 측정 CLI.

    python -m reliability.probe_regime                          # 스냅샷 전체
    python -m reliability.probe_regime --since 2026-09-07       # 연속 수집 구간만
    python -m reliability.probe_regime --out <json>             # 수치 저장

연속된 두 폴링 사이를 지금까지는 3분할로 봤다 — 값 변화 / 재확인(값은 같고 hvidate는
갱신) / 완전 침묵(hvidate까지 그대로). 그런데 hvidate는 **병원 단위** 생존 신호라서,
피드 전체는 계속 재송출되는데 특정 필드만 고정값을 반복하는 경우(예: 그 병상 유형의 HIS
매핑 오류)는 "재확인" 안에 숨는다. 죽은 피드만 자르는 규칙으로는 이 범주가 안 걸린다.

그래서 재확인을 둘로 쪼갠다 — **값 장기 불변 + 하트비트 생존**("유령")과 나머지.
"장기"는 절대 시간이 아니라 **같은 필드 × 정원 규모 × 값 위치(0 이하/정원 전부 가용/중간)
집단의 분포 대비 이상치**로 정한다. 병상 2개짜리 응급실이나 늘 만실인 병원은 하루 넘게
값이 그대로인 게 정상일 수 있어서, 필드 전체 분포 하나로 자르면 이들이 유령으로 오판된다.

유령인지는 run(값이 같은 연속 구간)이 끝나야 알 수 있으므로 run 단위로 판정한 뒤, 그
run에 속한 재확인 간격에 이름표를 되돌려 붙인다 — 그래야 4칸이 서로 겹치지 않는다.

측정은 판정하지 않고 보고만 한다(probe_severe와 같은 원칙). 함께 보는 것:
- 유령 run이 풀릴 때의 점프 크기 — 오래 고정됐던 값이 크게 한 번에 바뀐다면, 그동안
  E-Gen 값이 현실과 어긋나 있었다는 간접 증거다(E-Gen 데이터만으로 볼 수 있는 유일한 단서)
- 요일 × 시간대 교차표 — 평일 주간 수기 보정 같은 레짐 차이가 있는지
- 교차 확인 — 유령 후보 동안 같은 병원의 다른 병상 필드·중증질환 신고·응급실 활동이
  움직였는지. "정말 환자가 없어서 안 바뀐 것"과 "입력이 멈춘 것"을 가를 단서다. E-Gen과
  독립인 실시간 병상 소스가 공개돼 있지 않아서, 같은 피드 안의 다른 신호로 대신한다

run 분할 규칙은 학습 파이프라인과 같다: 관측 공백 SEGMENT_GAP_SEC(1시간) 초과면 끊는다.
수집 중단 구간에서도 끊기므로 유령 run 길이는 **하한**으로 읽어야 한다.

하트비트 생존은 hvidate 전진만 보지 않고 **병원별 갱신 주기로 보정**한다 — 주기가 폴링(20분)보다
긴 병원은 hvidate가 그대로인 간격이 정상이라, 전진만 세면 생존시간이 깎여 유령 기준(생존시간
분위수)과 유령 판정이 함께 왜곡된다. 주기는 폴링 시점 경과의 p95로 근사한다(`estimate_cadence`).
`--no-cadence`로 보정 전 결과와 비교할 수 있다.
"""
from __future__ import annotations

import argparse
import bisect
import json
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .engine import _BED_OP, _DEFAULT_SNAPSHOT_DIR
from .features import SEGMENT_GAP_SEC
from .probe_severe import SEVERE_OP

KST = timezone(timedelta(hours=9))

#: 가용 병상 필드 → 정원 필드. 전국 스냅샷에서 두 필드의 등장 횟수가 정확히 일치해 짝을 확인했다
FIELDS: dict[str, str] = {
    "hvec": "hvs01",   # 응급실 일반
    "hv28": "hvs02",   # 응급실 소아
    "hvicc": "hvs17",  # 일반 중환자실
    "hvoc": "hvs22",   # 수술실
    "hvgc": "hvs38",   # 입원실
}
#: hvec만 -1이 과밀 실값이고 나머지는 미입력이다 (egen/mapper.py MINUS_ONE_IS_VALUE_FIELDS)
MINUS_ONE_IS_VALUE = frozenset({"hvec"})

CHANGE, RECONFIRM, GHOST, SILENT, MISSING = "change", "reconfirm", "ghost", "silent", "missing"
KINDS = (CHANGE, RECONFIRM, GHOST, SILENT)

#: 유령 판정 — 집단 분포의 이 분위수를 넘고, 최소 GHOST_FLOOR_H 이상이어야 한다
GHOST_QUANTILE = 0.99
GHOST_FLOOR_H = 12.0
#: 집단 run이 이보다 적으면 분위수가 불안정해 필드 전체 분포로 대신한다
STRATUM_MIN_RUNS = 50
#: 민감도 비교용 고정 기준
FIXED_THRESHOLDS_H = (24.0, 48.0)
#: 순위에 끌려 올라갈 만한 값 — 채점 기준 θ와 같다
ATTRACTIVE_MIN = 3

WEEKDAYS = "월화수목금토일"
HOUR_BANDS = ((0, 6, "새벽 00-06"), (6, 9, "아침 06-09"), (9, 18, "주간 09-18"), (18, 24, "저녁 18-24"))

#: 하트비트 생존 판정의 병원별 갱신 주기 보정. hvidate가 전진한 간격만 "살아 있음"으로 세면,
#: 갱신 주기가 폴링(20분)보다 긴 병원(실측 4~10분 89%, 10~20분 10%, 소수는 1~2시간)은 멀쩡히
#: 돌고 있어도 간격 대부분이 침묵으로 찍히고 생존시간이 과소 집계된다. 그래서 hvidate가 그대로여도
#: 폴링 시점의 경과가 그 병원 주기의 ALIVE_FACTOR배 안쪽이면 아직 다음 갱신 차례가 안 온 것으로 본다
ALIVE_FACTOR = 2.0
#: 주기 근사의 하한(분). 폴링 20분이라 20분 미만 주기는 hvidate 간격으로 구분이 안 되므로(에일리어싱)
#: 폴링 시점 경과의 p95로 근사한다 — 경과는 0~주기 사이에서 고르게 나온다
CADENCE_FLOOR_MIN = 5.0
CADENCE_MAX_AGE_MIN = 360.0  # 6시간 넘는 경과는 피드 중단이라 주기 추정에서 제외
CADENCE_MIN_SAMPLES = 200    # 이보다 표본이 적은 병원은 보정 없이 hvidate 전진만 본다
CADENCE_DEFAULT_MIN = CADENCE_FLOOR_MIN * 2


def _parse_hvidate(raw: object) -> datetime | None:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(digits) < 12:
        return None
    try:
        return datetime.strptime((digits + "00")[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _age_minutes(ts: datetime, hvidate: object) -> float | None:
    """폴링 시점의 '마지막 갱신 후 경과(분)'. hvidate는 KST 벽시계다."""
    hv = _parse_hvidate(hvidate)
    if hv is None:
        return None
    return (ts.astimezone(KST).replace(tzinfo=None) - hv).total_seconds() / 60


def _iter_bed_records(snapshot_dir: Path, since: date | None, until: date | None):
    """기간 안의 병상·중증질환 응답 레코드를 (operation, ts(KST), items)로 시각순에 낸다."""
    for path in sorted(snapshot_dir.glob("*.jsonl")):
        day = date.fromisoformat(path.stem) if len(path.stem) == 10 else None
        if day and ((since and day < since) or (until and day > until)):
            continue
        with path.open("rb") as f:
            for raw_line in f:
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                operation = record.get("operation")
                if operation not in (_BED_OP, SEVERE_OP) or "error" in record or not record.get("items"):
                    continue
                try:
                    ts = datetime.fromisoformat(record["ts"]).astimezone(KST)
                except (KeyError, ValueError):
                    continue
                yield operation, ts, record["items"]


def estimate_cadence(snapshot_dir: Path, since: date | None, until: date | None) -> dict[str, float]:
    """병원별 hvidate 갱신 주기(분) 근사 = 폴링 시점 경과의 p95 (CADENCE_FLOOR_MIN 하한)."""
    ages: dict[str, list[float]] = defaultdict(list)
    for operation, ts, items in _iter_bed_records(snapshot_dir, since, until):
        if operation != _BED_OP:
            continue
        for item in items:
            hpid = (item.get("hpid") or "").strip()
            age = _age_minutes(ts, item.get("hvidate"))
            if hpid and age is not None and -5 <= age <= CADENCE_MAX_AGE_MIN:
                ages[hpid].append(age)
    cadence: dict[str, float] = {}
    for hpid, values in ages.items():
        if len(values) >= CADENCE_MIN_SAMPLES:
            values.sort()
            cadence[hpid] = max(values[int(len(values) * 0.95)], CADENCE_FLOOR_MIN)
    return cadence


def _heartbeat_alive(ts: datetime, hvidate, prev_hvidate, cadence_min: float | None) -> bool:
    """hvidate가 전진했거나, 그대로여도 경과가 병원 주기의 ALIVE_FACTOR배 안쪽이면 살아 있음."""
    if hvidate != prev_hvidate:
        return True
    if cadence_min is None:
        return False
    age = _age_minutes(ts, hvidate)
    return age is not None and age <= ALIVE_FACTOR * cadence_min


def _band(hour: int) -> str:
    for lo, hi, name in HOUR_BANDS:
        if lo <= hour < hi:
            return name
    raise ValueError(hour)


def _parse(raw, field: str) -> int | None:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value == -1 and field not in MINUS_ONE_IS_VALUE:
        return None
    return value


#: 정원 0 = 그 병상 유형을 운영하지 않는다(소아 응급실 없는 병원의 hv28=0 등). 값이 안
#: 바뀌는 게 당연하므로 유령 판정에서 뺀다 — 안 빼면 "0/0이 4주째 그대로"가 유령 상위를 채운다
CAP_NOT_OPERATED = "정원0(미운영)"


def _cap_bucket(cap: int | None) -> str:
    if cap == 0:
        return CAP_NOT_OPERATED
    if cap is None or cap < 0:
        return "정원미상"
    if cap <= 5:
        return "정원≤5"
    if cap <= 15:
        return "정원6-15"
    if cap <= 30:
        return "정원16-30"
    return "정원>30"


def _position(value: int, cap: int | None) -> str:
    if value <= 0:
        return "0이하"
    if cap and value >= cap:
        return "전부가용"
    return "중간"


class Run:
    """한 병원·한 필드에서 값이 같은 연속 구간."""

    __slots__ = ("hpid", "name", "field", "value", "cap", "start", "last", "alive_sec",
                 "pairs", "end_delta")

    def __init__(self, hpid: str, name: str, field: str, value: int | None, cap: int | None,
                 ts: datetime) -> None:
        self.hpid, self.name, self.field = hpid, name, field
        self.value, self.cap = value, cap
        self.start = self.last = ts
        self.alive_sec = 0.0  # hvidate가 갱신된 간격의 길이 합 — 하트비트가 살아 있던 시간
        #: 이 run 안의 같은-값 간격들 (KST 요일, 시, 재확인 여부) — 유령 판정 뒤 이름표를 붙인다
        self.pairs: list[tuple[int, int, bool]] = []
        self.end_delta: int | None = None  # 값 변화로 끝났으면 새 값 - 이 값, 검열이면 None

    @property
    def stratum(self) -> tuple[str, str, str]:
        assert self.value is not None
        return (self.field, _cap_bucket(self.cap), _position(self.value, self.cap))

    @property
    def total_h(self) -> float:
        return (self.last - self.start).total_seconds() / 3600


class Signals:
    """교차 확인용 변화 시각 — 유령 후보 run 동안 같은 병원의 다른 신호가 움직였는지 본다."""

    def __init__(self) -> None:
        #: (hpid, 병상 필드) -> 값 변화 시각 (시각순)
        self.bed: dict[tuple[str, str], list[datetime]] = defaultdict(list)
        #: hpid -> 중증질환 신고 28항목 중 하나라도 바뀐 시각 (시각순). 사람이 손으로 바꾸는 신호다
        self.severe: dict[str, list[datetime]] = defaultdict(list)

    @staticmethod
    def count(times: list[datetime], start: datetime, end: datetime) -> int:
        return bisect.bisect_right(times, end) - bisect.bisect_right(times, start)


def collect(snapshot_dir: Path, since: date | None, until: date | None,
            cadence: dict[str, float] | None = None):
    """스냅샷을 시각순으로 훑어 닫힌 run 전부와 값 변화 간격 집계를 돌려준다.

    교차 확인용으로 병상 필드별 값 변화 시각과 중증질환 신고(MKiosk) 변화 시각도 모은다.
    `cadence`(병원별 갱신 주기, 분)를 주면 하트비트 생존 판정에 주기 보정을 적용한다.
    """
    cadence = cadence or {}
    runs: list[Run] = []
    #: 값 변화·미입력 간격은 run 판정과 무관하므로 바로 센다: (필드, 요일, 시, 종류) -> 건수
    direct: Counter[tuple[str, int, int, str]] = Counter()
    state: dict[tuple[str, str], tuple[str | None, Run]] = {}
    signals = Signals()
    severe_state: dict[str, tuple[datetime, tuple]] = {}
    polls = 0
    first_ts = last_ts = None
    hospitals: set[str] = set()

    for operation, ts, items in _iter_bed_records(snapshot_dir, since, until):
        if operation == SEVERE_OP:
            for item in items:
                hpid = (item.get("hpid") or "").strip()
                if not hpid:
                    continue
                declared = tuple(item.get(f"MKioskTy{no}") for no in range(1, 29))
                prev_severe = severe_state.get(hpid)
                if (prev_severe and declared != prev_severe[1]
                        and (ts - prev_severe[0]).total_seconds() <= SEGMENT_GAP_SEC):
                    signals.severe[hpid].append(ts)
                severe_state[hpid] = (ts, declared)
            continue
        polls += 1
        first_ts = first_ts or ts
        last_ts = ts
        for item in items:
            hpid = (item.get("hpid") or "").strip()
            if not hpid:
                continue
            hospitals.add(hpid)
            hvidate = item.get("hvidate")
            name = (item.get("dutyName") or "").strip()
            cadence_min = cadence.get(hpid)
            for field, cap_field in FIELDS.items():
                if field not in item:
                    continue
                value = _parse(item.get(field), field)
                cap = _parse(item.get(cap_field), cap_field)
                key = (hpid, field)
                prev = state.get(key)
                if prev is None or (ts - prev[1].last).total_seconds() > SEGMENT_GAP_SEC:
                    if prev is not None:
                        runs.append(prev[1])
                    state[key] = (hvidate, Run(hpid, name, field, value, cap, ts))
                    continue
                prev_hvidate, run = prev
                if ts <= run.last:
                    continue
                wd, hr = ts.weekday(), ts.hour
                if value != run.value:
                    kind = MISSING if value is None or run.value is None else CHANGE
                    direct[(field, wd, hr, kind)] += 1
                    if kind == CHANGE:
                        run.end_delta = value - run.value
                        signals.bed[key].append(ts)
                    runs.append(run)
                    state[key] = (hvidate, Run(hpid, name, field, value, cap, ts))
                    continue
                if run.value is None:
                    direct[(field, wd, hr, MISSING)] += 1
                else:
                    alive = _heartbeat_alive(ts, hvidate, prev_hvidate, cadence_min)
                    if alive:
                        run.alive_sec += (ts - run.last).total_seconds()
                    run.pairs.append((wd, hr, alive))
                run.last = ts
                state[key] = (hvidate, run)

    runs.extend(run for _, run in state.values())
    return runs, direct, signals, polls, first_ts, last_ts, hospitals


def _quantile(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=1000, method="inclusive")[round(q * 1000) - 1]


def thresholds(runs: list[Run]) -> dict[tuple[str, str, str], dict]:
    """집단별 유령 기준(하트비트 생존 시간, 시간 단위)."""
    by_stratum: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    by_field: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        if run.value is None or run.alive_sec <= 0:
            continue
        h = run.alive_sec / 3600
        by_stratum[run.stratum].append(h)
        by_field[run.field].append(h)
    field_q = {f: _quantile(sorted(v), GHOST_QUANTILE) for f, v in by_field.items()}
    out = {}
    for stratum, values in by_stratum.items():
        values.sort()
        own = len(values) >= STRATUM_MIN_RUNS
        q = _quantile(values, GHOST_QUANTILE) if own else field_q[stratum[0]]
        out[stratum] = {
            "runs": len(values),
            "median_h": statistics.median(values),
            "q_h": q,
            "q_source": "stratum" if own else "field",
            "threshold_h": max(GHOST_FLOOR_H, q),
        }
    return out


def _is_ghost(run: Run, rule: dict, fixed_h: float | None = None) -> bool:
    if run.value is None or run.alive_sec <= 0 or run.stratum[1] == CAP_NOT_OPERATED:
        return False
    limit = fixed_h if fixed_h is not None else rule[run.stratum]["threshold_h"]
    return run.alive_sec / 3600 >= limit


def _shares(counter: Counter) -> dict[str, float]:
    n = sum(counter[k] for k in KINDS)
    return {k: (counter[k] / n if n else 0.0) for k in KINDS} | {"n": n}


def _fmt(shares: dict) -> str:
    return (f"변화 {shares[CHANGE]:6.1%} · 재확인 {shares[RECONFIRM]:6.1%} · "
            f"유령 {shares[GHOST]:6.1%} · 침묵 {shares[SILENT]:6.1%}  (n={shares['n']:,})")


def _jump_stats(deltas: list[int]) -> dict:
    if not deltas:
        return {"n": 0}
    absd = [abs(d) for d in deltas]
    return {
        "n": len(deltas),
        "abs_median": statistics.median(absd),
        "share_abs_ge3": sum(a >= ATTRACTIVE_MIN for a in absd) / len(absd),
        "share_drop": sum(d < 0 for d in deltas) / len(deltas),
    }


#: 응급실이 "평소만큼 바빴다"고 볼 비율 — 후보 run 동안의 hvec 변화율이 그 병원 전체 기간
#: 평균의 이 배수 이상이면, 그동안 환자 흐름이 있었는데 이 필드만 멈춘 것으로 본다
ER_BUSY_RATIO = 0.5


def corroborate(cands: list[Run], signals: Signals, span_days: float) -> dict:
    """후보 run 동안 같은 병원의 다른 신호가 움직였는지.

    - 다른 병상 필드가 움직였다 → 피드는 실제로 갱신 중인데 이 필드만 멈췄다(필드 단위 고정)
    - 병상·신고 모두 안 움직였다 → 병원 전체가 타임스탬프만 갱신(병원 단위 재송출)이거나,
      병원 전체가 정말 조용했다 — 둘은 여기서 못 가른다
    - 응급실이 평소만큼 바빴다(입원실·중환자실·수술실 후보만) → 환자 흐름이 있는데 안 바뀐 것
    """
    if not cands:
        return {"runs": 0}
    other_moved = severe_moved = neither = er_busy = er_eligible = 0
    er_ratios: list[float] = []
    for r in cands:
        other = sum(Signals.count(signals.bed.get((r.hpid, f), []), r.start, r.last)
                    for f in FIELDS if f != r.field)
        severe = Signals.count(signals.severe.get(r.hpid, []), r.start, r.last)
        other_moved += other > 0
        severe_moved += severe > 0
        neither += other == 0 and severe == 0
        if r.field != "hvec" and r.total_h > 0:
            er_times = signals.bed.get((r.hpid, "hvec"), [])
            usual_per_h = len(er_times) / (span_days * 24)
            if usual_per_h > 0:
                er_eligible += 1
                ratio = Signals.count(er_times, r.start, r.last) / r.total_h / usual_per_h
                er_ratios.append(ratio)
                er_busy += ratio >= ER_BUSY_RATIO
    n = len(cands)
    return {
        "runs": n,
        "hospitals": len({r.hpid for r in cands}),
        "otherBedMoved": other_moved / n,
        "severeMoved": severe_moved / n,
        "neitherMoved": neither / n,
        "erEligible": er_eligible,
        "erBusyShare": er_busy / er_eligible if er_eligible else None,
        "erRatioMedian": statistics.median(er_ratios) if er_ratios else None,
    }


def _print_corroboration(label: str, c: dict) -> None:
    if not c["runs"]:
        return
    line = (f"  교차 확인 [{label}] run {c['runs']:,}개/병원 {c['hospitals']:,}곳 · 다른 병상 움직임 "
            f"{c['otherBedMoved']:.0%} · 중증 신고 움직임 {c['severeMoved']:.0%} · 둘 다 정지 "
            f"{c['neitherMoved']:.0%}")
    if c["erEligible"]:
        line += (f" · 응급실 평소의 {ER_BUSY_RATIO:g}배 이상 바쁨 {c['erBusyShare']:.0%} "
                 f"(활동비 중위 {c['erRatioMedian']:.2f})")
    print(line)


def report(runs, direct, rule, signals: Signals, span_days: float) -> dict:
    # (필드, 요일, 시, 종류) 간격 집계 — run 안의 재확인에 유령 이름표를 붙인다
    cells: Counter[tuple[str, int, int, str]] = Counter(direct)
    for run in runs:
        ghost = _is_ghost(run, rule)
        for wd, hr, alive in run.pairs:
            kind = (GHOST if ghost else RECONFIRM) if alive else SILENT
            cells[(run.field, wd, hr, kind)] += 1

    result: dict = {"fields": {}}
    for field in FIELDS:
        total: Counter[str] = Counter()
        by_wd: dict[str, Counter] = defaultdict(Counter)
        by_band: dict[str, Counter] = defaultdict(Counter)
        by_cell: dict[str, Counter] = defaultdict(Counter)
        for (f, wd, hr, kind), n in cells.items():
            if f != field:
                continue
            total[kind] += n
            by_wd[WEEKDAYS[wd]][kind] += n
            by_band[_band(hr)][kind] += n
            weekend = "주말" if wd >= 5 else "평일"
            by_cell[f"{weekend} {_band(hr)}"][kind] += n

        field_runs = [r for r in runs if r.field == field and r.value is not None]
        ghosts = [r for r in field_runs if _is_ghost(r, rule)]
        if not field_runs:
            continue
        print(f"\n══ {field} (정원 {FIELDS[field]}) ══")
        missing_n = total[MISSING]
        print(f"  간격 4분할: {_fmt(_shares(total))} · 미입력 간격 {missing_n:,}")

        not_operated = [r for r in field_runs if r.stratum[1] == CAP_NOT_OPERATED]
        print(f"  정원 0(미운영) run {len(not_operated):,}개 · 병원 "
              f"{len({r.hpid for r in not_operated}):,}곳 — 유령 판정 제외")
        print("  유령 기준 (집단별 하트비트 생존 시간):")
        for stratum, t in sorted(rule.items()):
            if stratum[0] != field or stratum[1] == CAP_NOT_OPERATED:
                continue
            n_ghost = sum(1 for r in ghosts if r.stratum == stratum)
            print(f"    {stratum[1]:<8s} {stratum[2]:<6s} run {t['runs']:>7,} · 중위 "
                  f"{t['median_h']:5.2f}h · p99 {t['q_h']:6.1f}h({t['q_source']}) → 기준 "
                  f"{t['threshold_h']:6.1f}h · 유령 {n_ghost:,}")

        ghost_h = sum(r.alive_sec for r in ghosts) / 3600
        alive_h = sum(r.alive_sec for r in field_runs) / 3600
        ghost_hosp = {r.hpid for r in ghosts}
        attractive = [r for r in ghosts if r.value >= ATTRACTIVE_MIN]
        print(f"  유령 run {len(ghosts):,}개 · 병원 {len(ghost_hosp):,}곳 · 생존시간의 "
              f"{(ghost_h / alive_h if alive_h else 0):.1%} ({ghost_h:,.0f}h / {alive_h:,.0f}h)")
        print(f"  그중 값 ≥{ATTRACTIVE_MIN} (순위로 끌려 올라갈 만한 유령): run {len(attractive):,}개 · "
              f"병원 {len({r.hpid for r in attractive}):,}곳")

        sensitivity = {}
        fixed_cands: dict[str, list[Run]] = {}
        for fixed in FIXED_THRESHOLDS_H:
            g = [r for r in field_runs if _is_ghost(r, rule, fixed)]
            fixed_cands[f"고정 {fixed:g}h"] = g
            sensitivity[f"fixed_{fixed:g}h"] = {"runs": len(g), "hospitals": len({r.hpid for r in g})}
        print("  민감도 (고정 기준): " + " · ".join(
            f"{k} run {v['runs']:,}/병원 {v['hospitals']:,}" for k, v in sensitivity.items()))

        corroboration = {"rule": corroborate(ghosts, signals, span_days)}
        _print_corroboration("상대 기준", corroboration["rule"])
        for label, cands in fixed_cands.items():
            corroboration[label] = corroborate(cands, signals, span_days)
            _print_corroboration(label, corroboration[label])

        ghost_jump = _jump_stats([r.end_delta for r in ghosts if r.end_delta is not None])
        # 비교군: 유령 아닌 run 중 하트비트가 살아 있던 것 (침묵만 하다 끝난 run은 성격이 다르다)
        other_jump = _jump_stats([r.end_delta for r in field_runs
                                  if r.end_delta is not None and r.alive_sec > 0 and not _is_ghost(r, rule)])
        ghost_censored = sum(1 for r in ghosts if r.end_delta is None)
        for label, js in (("유령", ghost_jump), ("비교군", other_jump)):
            if js["n"]:
                print(f"  풀릴 때 점프 [{label}] {js['n']:,}건 · |Δ| 중위 {js['abs_median']} · "
                      f"|Δ|≥{ATTRACTIVE_MIN} {js['share_abs_ge3']:.1%} · 감소 {js['share_drop']:.1%}")
        print(f"  유령 중 끝까지 안 풀림(검열) {ghost_censored:,}개")

        top: dict[str, list[Run]] = defaultdict(list)
        for r in ghosts:
            top[r.hpid].append(r)
        ranked = sorted(top.values(), key=lambda rs: -sum(r.alive_sec for r in rs))[:10]
        if ranked:
            print("  유령 생존시간 상위 병원:")
        top_rows = []
        for rs in ranked:
            longest = max(rs, key=lambda r: r.alive_sec)
            row = {
                "hpid": longest.hpid, "name": longest.name,
                "ghost_h": round(sum(r.alive_sec for r in rs) / 3600, 1),
                "runs": len(rs), "longest_h": round(longest.alive_sec / 3600, 1),
                "longest_value": longest.value, "cap": longest.cap,
                "longest_start": longest.start.isoformat(timespec="minutes"),
            }
            top_rows.append(row)
            print(f"    {row['hpid']} {row['name'][:14]:<14s} 유령 {row['ghost_h']:7.1f}h · "
                  f"최장 {row['longest_h']:6.1f}h (값 {row['longest_value']}/정원 {row['cap']})")

        print("  요일별:")
        for wd in WEEKDAYS:
            if by_wd[wd]:
                print(f"    {wd}  {_fmt(_shares(by_wd[wd]))}")
        print("  평일/주말 × 시간대:")
        for key in sorted(by_cell):
            print(f"    {key:<14s} {_fmt(_shares(by_cell[key]))}")

        result["fields"][field] = {
            "capacityField": FIELDS[field],
            "pairs": _shares(total) | {"missing": missing_n},
            "notOperated": {"runs": len(not_operated),
                            "hospitals": len({r.hpid for r in not_operated})},
            "thresholds": {" / ".join(s[1:]): t for s, t in rule.items()
                           if s[0] == field and s[1] != CAP_NOT_OPERATED},
            "ghost": {
                "runs": len(ghosts), "hospitals": len(ghost_hosp),
                "aliveShare": ghost_h / alive_h if alive_h else 0.0,
                "attractiveRuns": len(attractive),
                "attractiveHospitals": len({r.hpid for r in attractive}),
                "censored": ghost_censored,
                "top": top_rows,
            },
            "sensitivity": sensitivity,
            "corroboration": corroboration,
            "jump": {"ghost": ghost_jump, "comparison": other_jump},
            "byWeekday": {k: _shares(v) for k, v in by_wd.items()},
            "byBand": {k: _shares(v) for k, v in by_band.items()},
            "byWeekendBand": {k: _shares(v) for k, v in by_cell.items()},
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshots", type=Path, default=_DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--since", type=date.fromisoformat, default=None, help="KST 날짜 (포함)")
    parser.add_argument("--until", type=date.fromisoformat, default=None, help="KST 날짜 (포함)")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-cadence", action="store_true",
                        help="병원별 갱신 주기 보정 없이 hvidate 전진만 하트비트로 본다 (보정 전과 비교용)")
    args = parser.parse_args()

    cadence: dict[str, float] = {}
    cadence_summary: dict | None = None
    if not args.no_cadence:
        cadence = estimate_cadence(args.snapshots, args.since, args.until)
        if cadence:
            cad_vals = sorted(cadence.values())
            slow = sum(1 for c in cad_vals if c > 20)
            cadence_summary = {
                "hospitals": len(cadence),
                "medianMin": round(statistics.median(cad_vals), 1),
                "p90Min": round(cad_vals[int(len(cad_vals) * 0.9)], 1),
                "maxMin": round(cad_vals[-1], 1),
                "over20Min": slow,
                "aliveFactor": ALIVE_FACTOR,
            }

    runs, direct, signals, polls, first_ts, last_ts, hospitals = collect(
        args.snapshots, args.since, args.until, cadence)
    if polls == 0 or first_ts is None:
        raise SystemExit(f"병상 응답을 하나도 못 읽었다: {args.snapshots}")
    span_days = (last_ts - first_ts).total_seconds() / 86400
    print(f"병상 폴링 {polls:,}회 · {first_ts:%m-%d %H:%M} ~ {last_ts:%m-%d %H:%M} KST "
          f"({span_days:.1f}일) · 병원 {len(hospitals)}곳 · run {len(runs):,}개")
    if cadence_summary:
        print(f"갱신 주기 근사(경과 p95) {cadence_summary['hospitals']}곳: 중위 {cadence_summary['medianMin']}분 · "
              f"p90 {cadence_summary['p90Min']}분 · 최대 {cadence_summary['maxMin']:.0f}분 · "
              f"20분 초과 {cadence_summary['over20Min']}곳 — hvidate 그대로여도 경과가 주기 "
              f"{ALIVE_FACTOR:g}배 안쪽이면 살아 있음")
    else:
        print("갱신 주기 보정 없음 — hvidate 전진만 하트비트로 본다")
    print(f"유령 기준: 집단 p{GHOST_QUANTILE * 100:g} 하트비트 생존시간, 최소 {GHOST_FLOOR_H:g}h")

    rule = thresholds(runs)
    result = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshotDir": str(args.snapshots),
        "since": args.since.isoformat() if args.since else None,
        "until": args.until.isoformat() if args.until else None,
        "polls": polls,
        "spanDays": round(span_days, 2),
        "hospitals": len(hospitals),
        "ghostRule": {"quantile": GHOST_QUANTILE, "floorH": GHOST_FLOOR_H,
                      "stratumMinRuns": STRATUM_MIN_RUNS},
        "cadence": cadence_summary,
    } | report(runs, direct, rule, signals, span_days)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n수치 저장: {args.out}")


if __name__ == "__main__":
    main()
