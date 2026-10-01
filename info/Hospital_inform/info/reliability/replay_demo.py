"""시연용 신뢰도 검증 로그 — 실제 E-Gen 스냅샷을 다시 돌려 "도착 때도 병상 숫자가 맞았나"를 채점한다.

    cd info/Hospital_inform/info
    python -m reliability.replay_demo            # data/verification/replay_demo.jsonl 다시 생성 (스냅샷 1장당 10건)
    python -m reliability.replay_demo --n 1000

**시연용이다(2026-10-02).** 요청(어느 시각에 어느 병원으로, 이동 몇 분)은 무작위로 만든 가상 상황이고,
결과(도착 때 병상 숫자)만 실제 E-Gen 스냅샷에서 읽는다. 모든 건에 `demo: true`·`source: "replay"`가 붙는다.
실제 운영 로그가 아니므로 "병원이 실제로 받았는가"는 검증하지 않는다 — 검증하는 건 "도착할 때도 병상 정보가
유효했는가"뿐이다.

절차 (스냅샷 시각순으로 한 번 훑는다):
1. 신뢰도 엔진에 스냅샷을 시각순으로 먹이며, 무작위로 고른 시각 t에 병상이 1석 이상 보이던 병원 몇 곳에
   가상 요청을 낸다(이동 5~25분). 그 순간 모델이 낸 authority·rArrive(도착 때도 유효할 확률)를 기록한다
2. 도착 시각 이후 첫 스냅샷의 실제 값을 본다. 모델의 학습 기준(θ=3)대로 3석 이상 바뀌지 않았으면 "유효",
   도착 때 0석 이하면 결과 BEDS_FULL(도착 후 수용 불가), 아니면 accepted
3. 확률 구간별 실제 유효 비율(캘리브레이션)은 summarize()가 계산한다 — 거절 로그 수신구(5003)가
   GET /verification/summary로 내보내고 hub가 대시보드로 중계한다
"""
from __future__ import annotations

import argparse
import bisect
import json
import random
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import serve
from .engine import _BED_OP, _DEFAULT_SNAPSHOT_DIR, BedReliabilityEngine

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "verification" / "replay_demo.jsonl"
#: 모델 학습 기준과 같다 — 3석 이상 바뀌면 그 병상 정보는 무효(labeling.py의 theta)
THETA = 3
TRAVEL_MIN_RANGE = (5, 25)
#: 도착 시각 뒤 이 시간 안에 스냅샷이 없으면(수집 공백) 채점하지 않는다
MAX_ARRIVAL_GAP = timedelta(minutes=30)
#: 한 시각에 내는 가상 요청 수의 하한. 스냅샷이 적으면 n건을 채우도록 늘린다
MIN_REQUESTS_PER_TICK = 4
BINS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]


def _load_bed_snapshots(snapshot_dir: Path) -> list[tuple[datetime, bytes, dict[str, dict]]]:
    """병상 스냅샷 줄을 시각순으로: (시각, 원본 줄, hpid -> item)."""
    out = []
    for path in sorted(snapshot_dir.glob("*.jsonl")):
        with path.open("rb") as f:
            for raw in f:
                if not raw.endswith(b"\n"):
                    continue
                try:
                    record = json.loads(raw)
                    if record.get("operation") != _BED_OP or "error" in record:
                        continue
                    ts = datetime.fromisoformat(record["ts"]).astimezone(timezone.utc)
                except (ValueError, KeyError):
                    continue
                items = {(i.get("hpid") or "").strip(): i for i in record.get("items") or []}
                out.append((ts, raw, items))
    out.sort(key=lambda r: r[0])
    return out


def _hvec(item: dict | None) -> int | None:
    try:
        return int(str(item["hvec"]).strip()) if item else None
    except (KeyError, ValueError):
        return None


#: --n을 안 주면 스냅샷 1장당 이만큼 — 서버를 켜 둘수록(스냅샷이 쌓일수록) 로그도 늘어난다
REQUESTS_PER_SNAPSHOT = 10


def generate(n: int | None = None, seed: int = 7, snapshot_dir: Path = _DEFAULT_SNAPSHOT_DIR,
             output: Path = OUTPUT_PATH) -> int:
    snapshots = _load_bed_snapshots(snapshot_dir)
    if len(snapshots) < 3:
        raise SystemExit(f"스냅샷이 부족하다({len(snapshots)}개) — {snapshot_dir}")
    times = [s[0] for s in snapshots]
    n = n or REQUESTS_PER_SNAPSHOT * len(snapshots)
    rng = random.Random(seed)
    # 요청을 낼 시각: 앞쪽 몇 시간은 엔진이 병원 리듬을 익히는 구간이라 건너뛰고, 고르게 뽑는다
    candidates = list(range(len(snapshots) // 10, len(snapshots) - 1))
    # 수집 공백 때문에 채점 못 하는 요청이 있어 넉넉히(2배) 내고, 끝에서 n건만 고른다(기간 전체에 고르게)
    per_tick = max(MIN_REQUESTS_PER_TICK, -(-2 * n // max(len(candidates), 1)))
    ticks = set(rng.sample(candidates, min(len(candidates), -(-2 * n // per_tick))))

    with tempfile.TemporaryDirectory() as empty:  # 워밍업 없이 시작 — 스냅샷은 아래에서 시각순으로 먹인다
        engine = BedReliabilityEngine(snapshot_dir=empty)
    records: list[dict] = []
    for index, (ts, raw, items) in enumerate(snapshots):
        engine._ingest_line(raw)
        if index not in ticks:
            continue
        preds = engine.predict(ts).get("hvec", {})
        shown = [h for h, p in preds.items() if (_hvec(items.get(h)) or 0) > 0]
        for hpid in rng.sample(shown, min(per_tick, len(shown))):
            travel = rng.uniform(*TRAVEL_MIN_RANGE)
            arrive_at = ts + timedelta(minutes=travel)
            j = bisect.bisect_left(times, arrive_at)
            if j >= len(snapshots) or snapshots[j][0] - arrive_at > MAX_ARRIVAL_GAP:
                continue
            before, after = _hvec(items.get(hpid)), _hvec(snapshots[j][2].get(hpid))
            if after is None:
                continue
            p = preds[hpid]
            r_arrive = float(serve.at(p.pred_t_sec, p.age_sec, travel * 60, sigma=p.sigma))
            records.append({
                "demo": True, "source": "replay",
                "hospitalId": hpid, "name": (items[hpid].get("dutyName") or "").strip(),
                "requestAt": ts.isoformat(), "travelMin": round(travel, 1),
                "arrivalSnapshotAt": snapshots[j][0].isoformat(),
                "bedsAtRequest": before, "bedsAtArrival": after,
                "bedAuthorityAtRequest": round(p.authority, 4), "bedRArriveAtRequest": round(r_arrive, 4),
                "validAtArrival": abs(after - before) < THETA,
                "outcome": "accepted" if after > 0 else "BEDS_FULL",
                "modelTag": p.model_tag,
            })
    if len(records) > n:
        records = sorted(rng.sample(records, n), key=lambda r: r["requestAt"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(records)


def _biggest_swing(records: list[dict]) -> dict | None:
    """병상 숫자가 짧은 시간에 가장 크게 바뀐 실제 사례 — "왜 신뢰도가 필요한가"의 예시."""
    if not records:
        return None
    r = max(records, key=lambda r: abs(r["bedsAtArrival"] - r["bedsAtRequest"]))
    return {k: r[k] for k in ("name", "requestAt", "arrivalSnapshotAt", "bedsAtRequest", "bedsAtArrival", "travelMin")}


def summarize(path: Path = OUTPUT_PATH) -> dict:
    """대시보드 검증 화면용 집계. 파일이 없으면 count 0."""
    records = []
    if path.is_file():
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    bins = []
    for lo, hi in BINS:
        inside = [r for r in records if lo <= r["bedRArriveAtRequest"] < hi]
        bins.append({
            "from": lo, "to": min(hi, 1.0), "count": len(inside),
            "predicted": round(sum(r["bedRArriveAtRequest"] for r in inside) / len(inside), 3) if inside else None,
            "observed": round(sum(r["validAtArrival"] for r in inside) / len(inside), 3) if inside else None,
        })
    count = len(records)
    ece = sum(b["count"] * abs(b["predicted"] - b["observed"]) for b in bins if b["count"]) / count if count else None
    return {
        "demo": True, "source": "replay",
        "count": count,
        "hospitals": len({r["hospitalId"] for r in records}),
        "period": [min(r["requestAt"] for r in records), max(r["arrivalSnapshotAt"] for r in records)] if records else None,
        "validRate": round(sum(r["validAtArrival"] for r in records) / count, 3) if count else None,
        "bedsFullAtArrival": sum(r["outcome"] == "BEDS_FULL" for r in records),
        "calibrationError": round(ece, 3) if ece is not None else None,
        "bins": bins,
        "biggestSwing": _biggest_swing(records),
        "theta": THETA,
        "generatedAt": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() if path.is_file() else None,
    }


def _selftest() -> None:
    """가짜 스냅샷 3개로 채점 규칙만 확인한다(모델 없이)."""
    base = [{"bedsAtRequest": 5, "bedsAtArrival": a, "bedRArriveAtRequest": p, "requestAt": "t", "arrivalSnapshotAt": "u",
             "hospitalId": "H", "name": "n", "travelMin": 10, "validAtArrival": abs(a - 5) < THETA,
             "outcome": "accepted" if a > 0 else "BEDS_FULL"} for a, p in ((5, 0.9), (0, 0.85), (4, 0.3))]
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "x.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in base), encoding="utf-8")
        s = summarize(path)
    assert s["count"] == 3 and s["bedsFullAtArrival"] == 1
    top = s["bins"][-1]
    assert top["count"] == 2 and top["observed"] == 0.5, top
    assert s["biggestSwing"]["bedsAtArrival"] == 0
    print("replay_demo 자체 검사 통과")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=None)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return
    saved = generate(args.n, args.seed)
    summary = summarize()
    print(f"시연용 검증 로그 {saved}건 → {OUTPUT_PATH}")
    print(json.dumps({k: summary[k] for k in ("count", "hospitals", "validRate", "bedsFullAtArrival", "calibrationError")},
                     ensure_ascii=False))
    for b in summary["bins"]:
        print(f"  예측 {b['from']:.0%}~{b['to']:.0%}: {b['count']:>4}건, 예측 평균 {b['predicted']}, 실제 유효 {b['observed']}")


if __name__ == "__main__":
    main()
