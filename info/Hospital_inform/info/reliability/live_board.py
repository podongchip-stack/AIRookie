"""라이브 채점 보드 — "E-Gen 값이 지금 믿을 만한가"를 실제 엔진으로 예측하고,
다음 스냅샷이 도착할 때마다 그 예측을 실데이터로 채점한다.

    python -m reliability.live_board          # 자체 검사: 최근 48시간 재생·채점 요약 출력

/verify 재생 채점(replay_demo — 가상 이송 요청 표본)과 다른 점: 표본이 아니라
**창 안의 모든 병원 × 모든 폴링**을 채점하고, 현재 진행형 상태(지금 각 병원 값의
유효 확률·유효기간)까지 내보낸다. 시뮬 수식 복제가 아니라 **서빙과 같은
BedReliabilityEngine**을 빈 상태로 만들어 과거 스냅샷을 한 폴링씩 먹이며
(observe_rows) 그 사이사이 예측(predict)을 떠서 다음 폴링으로 채점한다 —
"화면의 숫자가 실제 엔진 출력이냐"는 질문에 "네"로 답하기 위한 선택.

채점 정의(기존 /verify와 동일한 θ=3):
- 한 claim(병원의 현재 hvec 값)에 대해, 다음 폴링에서 |Δ| >= θ면 "크게 어긋남(break)"
- 캘리브레이션 쌍은 폴링 단위 조건부 확률로 만든다 —
  p_step = S(age+gap)/S(age) (이 한 구간을 더 버틸 확률) vs 실제 break 여부.
  누적 확률을 그대로 쓰면 같은 claim이 매 폴링 중복 집계되는 왜곡이 생긴다.
- 판명 피드에는 값이 바뀐 순간만 남긴다(폴링당 수백 건 방지). 그때 보여주는 확률은
  누적 S(age) — "태어난 지 43분, 모델은 31%까지 내려놨는데 깨짐"의 그 숫자.

산출은 data/verification/live_board.json 캐시로 저장되고(기본 20분 신선도),
ingest.py의 GET /verification/live가 이 모듈을 통해 서빙한다. 창(기본 48시간)이
짧아 리듬 피처의 버전 이력이 서빙 본체(60일 워밍업)보다 얕다는 한계는 meta에 명시.
"""
from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .engine import BedReliabilityEngine, _BED_OP
from .serve import authority as _survival


def survival(pred_t: float, age_sec: float, sigma: float) -> float:
    """S(age) — serve.authority와 동일 수식(조건부 갱신 없이 raw 생존확률)."""
    return float(_survival(pred_t, max(age_sec, 0.0), sigma=sigma))

THETA = 3
WINDOW_HOURS_DEFAULT = 48
CACHE_REFRESH_SEC = 1200          # 스냅샷 주기(20분)와 같게 — 새 폴링이 올 때쯤 다시 만든다
GAP_RESET_MIN = 60.0              # 관측 공백이 이보다 크면 채점을 쉬어 간다(수집 중단 구간)
# 판명 피드는 "큰 어긋남(θ=3석 이상)"만 담는다 — 모든 잔변화를 담으면 48시간에 3만 건이라
# 피드가 최근 30분짜리가 되고, 화면 리플레이가 하루를 덮지 못한다. 잔변화는 headline의
# valueChanges 집계에만 남는다. 4,000건이면 큰 어긋남 기준 하루 이상을 덮는다(실측 ~2,300/일).
FEED_LIMIT = 4000
CALIBRATION_BINS = ((0.0, 0.5), (0.5, 0.8), (0.8, 0.95), (0.95, 1.01))

_BASE = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = _BASE / "data" / "snapshots_nationwide"
CACHE_PATH = _BASE / "data" / "verification" / "live_board.json"


def _load_polls(window_hours: int, snapshot_dir: Path = SNAPSHOT_DIR) -> list[tuple[datetime, dict[str, dict]]]:
    """창 안의 병상 폴링들을 시각순으로. 각 항목은 (ts, {hpid: 원본 item})."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    polls: list[tuple[datetime, dict[str, dict]]] = []
    # 파일은 날짜 단위 — 창 시작 전날 파일부터 본다
    for path in sorted(snapshot_dir.glob("*.jsonl"))[-(window_hours // 24 + 2):]:
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("operation") != _BED_OP or not rec.get("items"):
                    continue
                ts = datetime.fromisoformat(rec["ts"]).astimezone(timezone.utc)
                if ts < cutoff:
                    continue
                polls.append((ts, {it["hpid"]: it for it in rec["items"]}))
    polls.sort(key=lambda p: p[0])
    return polls


def _hvec(item: dict | None) -> int | None:
    if item is None:
        return None
    try:
        return int(item.get("hvec"))
    except (TypeError, ValueError):
        return None


def build(window_hours: int = WINDOW_HOURS_DEFAULT) -> dict:
    """창 전체를 실제 엔진으로 재생·채점해 라이브 보드 JSON을 만든다."""
    started = time.time()
    polls = _load_polls(window_hours)
    if len(polls) < 3:
        raise RuntimeError(f"창 {window_hours}시간 안에 폴링이 {len(polls)}개뿐 — 스냅샷 수집 확인")

    # 빈 폴더를 스냅샷 경로로 줘서 엔진이 아무것도 자동 ingest하지 않게 한 뒤,
    # 창 안의 폴링을 순서대로 직접 먹인다 — 예측은 항상 "그 시점까지만 본" 상태에서 뜬다.
    with tempfile.TemporaryDirectory() as empty:
        engine = BedReliabilityEngine(snapshot_dir=empty)
        serving = engine._fields["hvec"]

        claim_params: dict[str, dict] = {}   # hpid -> {born, predT, sigma, value}
        names: dict[str, str] = {}
        feed: list[dict] = []
        bins = [
            {"range": f"{int(lo*100)}~{int(min(hi,1.0)*100)}%", "predictedSum": 0.0, "survived": 0, "total": 0}
            for lo, hi in CALIBRATION_BINS
        ]
        warned_breaks = missed_breaks = value_changes = 0   # 경고(<50%) 깨짐 / 고신뢰(>=80%) 깨짐 / 전체 값 변화
        prev_ts: datetime | None = None

        for ts, items in polls:
            gap_min = (ts - prev_ts).total_seconds() / 60.0 if prev_ts else None
            # 1) 직전 예측을 이 폴링의 실제 값으로 채점 (수집 공백 구간은 건너뜀)
            if gap_min is not None and gap_min <= GAP_RESET_MIN:
                for hpid, claim in claim_params.items():
                    value = _hvec(items.get(hpid))
                    if value is None:
                        continue
                    age0 = (prev_ts - claim["born"]).total_seconds()
                    age1 = (ts - claim["born"]).total_seconds()
                    s0 = max(survival(claim["predT"], max(age0, 0.0), claim["sigma"]), 1e-9)
                    s1 = survival(claim["predT"], age1, claim["sigma"])
                    p_step = min(s1 / s0, 1.0)          # 이 한 구간을 더 버틸 조건부 확률
                    broke = abs(value - claim["value"]) >= THETA
                    for b, (lo, hi) in zip(bins, CALIBRATION_BINS):
                        if lo <= p_step < hi:
                            b["predictedSum"] += p_step
                            b["survived"] += not broke
                            b["total"] += 1
                            break
                    if value != claim["value"]:
                        value_changes += 1
                    if broke:
                        p_cum = survival(claim["predT"], age1, claim["sigma"])
                        if p_cum < 0.5:
                            warned_breaks += 1
                        elif p_cum >= 0.8:
                            missed_breaks += 1
                        feed.append({
                            "ts": ts.isoformat(timespec="seconds"),
                            "hpid": hpid, "name": names.get(hpid, hpid),
                            "claimValue": claim["value"], "newValue": value,
                            "delta": value - claim["value"],
                            "ageMin": round(age1 / 60.0, 1),
                            "pValid": round(p_cum, 3),
                            "becameFull": value <= 0,
                        })
            # 2) 이 폴링을 엔진에 관측시키고, 3) 새 예측 상태를 뜬다
            rows = list(items.values())
            engine.observe_rows(rows, ts)
            for hpid, item in items.items():
                if "dutyName" in item:
                    names[hpid] = item["dutyName"]
            predictions = engine._predict_field(serving, ts)
            for hpid, pred in predictions.items():
                value = _hvec(items.get(hpid))
                if value is None and hpid in claim_params:
                    value = claim_params[hpid]["value"]  # 이번 폴링에 안 나온 병원은 직전 값 유지
                claim_params[hpid] = {
                    "born": pred.born, "predT": pred.pred_t_sec, "sigma": pred.sigma,
                    "value": value if value is not None else 0,
                }
            prev_ts = ts

        # 현재 보드 — 마지막 폴링 기준의 진행형 상태 (화면이 초 단위 감쇠를 직접 그린다)
        last_ts, last_items = polls[-1]
        board = []
        for hpid, pred in engine._predict_field(serving, last_ts).items():
            value = _hvec(last_items.get(hpid))
            if value is None:
                continue
            board.append({
                "hpid": hpid, "name": names.get(hpid, hpid), "value": value,
                "bornAt": pred.born.isoformat(timespec="seconds"),
                "predictedSurvivalSec": round(pred.pred_t_sec, 1),
                "sigma": round(pred.sigma, 4),
                "authorityAtBuild": round(pred.authority, 4),
                "ttlSec": round(pred.ttl_sec, 1),
            })
        board.sort(key=lambda row: row["authorityAtBuild"])

    for b in bins:
        b["predictedPct"] = round(b["predictedSum"] / b["total"] * 100, 1) if b["total"] else None
        b["actualPct"] = round(b["survived"] / b["total"] * 100, 1) if b["total"] else None
        del b["predictedSum"]

    feed.sort(key=lambda r: r["ts"], reverse=True)
    big_breaks = len(feed)
    return {
        "source": "live_replay",
        "demo": False,  # 표본·가상 요청이 아니라 창 안의 실측 전수 채점
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "windowHours": window_hours,
        "theta": THETA,
        "modelTag": serving.model_tag,
        "polls": len(polls),
        "lastPollTs": polls[-1][0].isoformat(timespec="seconds"),
        "buildSec": round(time.time() - started, 1),
        "board": board,
        "feed": feed[:FEED_LIMIT],
        "calibration": {
            "bins": bins,
            "note": "폴링 단위 조건부 확률 vs 실제 유지 비율 — 같은 claim의 중복 집계를 피한 정의",
        },
        "headline": {
            "valueChanges": value_changes,
            "bigBreaks": big_breaks,
            "warnedBreaks": warned_breaks,     # 깨지기 전에 확률이 이미 50% 밑이었던 수
            "missedBreaks": missed_breaks,     # 80% 이상 고신뢰였는데 깨진 수
        },
        "limits": [
            f"창 {window_hours}시간 재생이라 리듬 피처의 버전 이력이 서빙 본체(60일 워밍업)보다 얕다",
            "실제 수용 여부가 아니라 신고값의 유효성(θ=3석)을 채점한다",
        ],
    }


def cached(window_hours: int = WINDOW_HOURS_DEFAULT, refresh_sec: int = CACHE_REFRESH_SEC) -> dict:
    """캐시가 신선하면 그대로, 아니면 다시 만든다(생성 수십 초 — ingest가 락으로 감싼다)."""
    if CACHE_PATH.is_file() and time.time() - CACHE_PATH.stat().st_mtime < refresh_sec:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    body = build(window_hours)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return body


def _selftest() -> None:
    body = build(window_hours=24)
    h = body["headline"]
    print(f"폴링 {body['polls']}개({body['windowHours']}h, 생성 {body['buildSec']}초) — "
          f"보드 {len(body['board'])}곳, 값 변화 {h['valueChanges']}건(큰 어긋남 {h['bigBreaks']}건)")
    print(f"깨지기 전 경고(확률<50%) {h['warnedBreaks']}건 / 고신뢰(>=80%)인데 깨짐 {h['missedBreaks']}건")
    for b in body["calibration"]["bins"]:
        print(f"  {b['range']:>8}: 예측 {b['predictedPct']}% vs 실제 {b['actualPct']}% (n={b['total']})")
    worst = body["board"][:3]
    print("지금 가장 못 믿을 값:", [f"{r['name']} hvec={r['value']} p={r['authorityAtBuild']:.2f}" for r in worst])
    assert body["board"] and body["calibration"]["bins"][0]["total"] >= 0


if __name__ == "__main__":
    _selftest()
