"""병원 한 곳의 "우리 병원" 검증 화면용 집계 (2026-10-02).

전체 화면(reliability.replay_demo)은 무작위로 뽑은 가상 요청이라 병원 한 곳당 몇 건뿐이다. 여기서는 그 병원의
스냅샷 기록을 **전부** 쓴다 — 기록된 모든 시각에 구급차가 출발했다고 치고(이동 TRAVEL_MIN분), 도착 시각 뒤 첫
스냅샷의 실제 값과 비교한다. 거기에 그 병원의 E-Gen 중증질환 신고, 심평원 전문병원 지정·전문의 수, 거절 로그를 붙인다.
hub가 의사결정 로그(승인·거절·확인)와 지금의 신뢰도를 덧붙여 대시보드로 보낸다.

    python -m hospital_score.hospital_view A1100009
"""
from __future__ import annotations

import bisect
import json
from collections import Counter
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from . import hira_files as HF
from . import rejection as R
from . import vocabulary as V
from .dataset import OP_ACCEPT, OP_BEDS, OP_LIST, parse_hvidate

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "snapshots_nationwide"
SPECIALISTS_PATH = Path(__file__).resolve().parents[1] / "data" / "hira" / "specialists.json"
TRAVEL_MIN = 15  # 전체 화면의 평균 이동 시간과 같게
MAX_ARRIVAL_GAP = timedelta(minutes=30)
THETA = 3  # 3석 이상 바뀌면 "틀림" — 신뢰도 모델 학습 기준
MAX_CHART_POINTS = 360
#: 최근 이만큼만 쓴다 — 예전 하루치 스냅샷(8월 13일)이 그래프 가로축을 끊지 않게
WINDOW = timedelta(days=7)
#: 화면에 보일 응급 수용 과 (egen/mapper.ACUTE_HIRA_DEPARTMENTS와 같은 목록 — info 바깥 모듈 import를 피해 복사)
ACUTE_DEPARTMENTS = frozenset({
    "내과", "외과", "정형외과", "신경외과", "신경과", "산부인과", "소아청소년과", "응급의학과",
    "비뇨의학과", "심장혈관흉부외과", "정신건강의학과", "이비인후과", "성형외과", "안과",
})


def _hvec(raw) -> int | None:
    """hvec 정수. -1도 과밀 1명이라 값으로 둔다(egen/mapper.MINUS_ONE_IS_VALUE_FIELDS)."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _index(paths: tuple[str, ...], _mtime: float) -> dict:
    """스냅샷 전체를 한 번 훑어 병원별 (시각, hvec, hvidate)만 남긴다. 마지막 파일 mtime이 바뀌면 다시 만든다."""
    series: dict[str, list[tuple[datetime, int, str]]] = {}
    accept: dict[str, dict] = {}
    names: dict[str, dict] = {}
    for path in paths:
        with open(path, "rb") as f:
            for raw in f:
                if not raw.endswith(b"\n"):
                    continue
                try:
                    record = json.loads(raw)
                    op = record.get("operation")
                    if op not in (OP_BEDS, OP_ACCEPT, OP_LIST) or "error" in record:
                        continue
                    ts = datetime.fromisoformat(record["ts"])
                except (ValueError, KeyError):
                    continue
                for row in record.get("items") or []:
                    hpid = (row.get("hpid") or "").strip()
                    if not hpid:
                        continue
                    if op == OP_BEDS:
                        value = _hvec(row.get("hvec"))
                        if value is not None:
                            series.setdefault(hpid, []).append((ts, value, str(row.get("hvidate") or "")))
                    elif op == OP_ACCEPT:
                        accept[hpid] = row  # 시각순이라 마지막이 최신
                    else:
                        names[hpid] = {"name": (row.get("dutyName") or "").strip(),
                                       "emcls": (row.get("dutyEmclsName") or "").strip() or None}
    for rows in series.values():
        rows.sort(key=lambda r: r[0])
    return {"series": series, "accept": accept, "names": names}


def _departures(rows: list[tuple[datetime, int, str]]) -> dict:
    """기록된 모든 시각에 출발했다고 치고(빈 병상이 1석 이상 보였을 때만), TRAVEL_MIN분 뒤 실제 값과 비교."""
    times = [r[0] for r in rows]
    kinds: Counter = Counter()
    worst = None
    for ts, before, _ in rows:
        if before <= 0:
            continue
        arrive = ts + timedelta(minutes=TRAVEL_MIN)
        j = bisect.bisect_left(times, arrive)
        if j >= len(rows) or rows[j][0] - arrive > MAX_ARRIVAL_GAP:
            continue
        after = rows[j][1]
        d = after - before
        kinds["becameFull" if after <= 0 else "changedBig" if abs(d) >= THETA else "changedSmall" if d else "same"] += 1
        if d < 0 and (worst is None or d < worst["bedsAtArrival"] - worst["bedsAtRequest"]):
            worst = {"requestAt": ts.isoformat(), "arrivalAt": rows[j][0].isoformat(), "bedsAtRequest": before, "bedsAtArrival": after}
    return {"travelMin": TRAVEL_MIN, "theta": THETA,
            **{k: kinds.get(k, 0) for k in ("same", "changedSmall", "changedBig", "becameFull")},
            "worst": worst}


def _rhythm(rows: list[tuple[datetime, int, str]]) -> dict:
    """수집할 때마다 병원이 숫자를 새로 고쳐 두었나(hvidate가 바뀐 횟수 — 20분 수집 주기보다 잘게는 못 잰다)와
    만실·과밀이던 시간 비율."""
    stamps = {parse_hvidate(r[2]) for r in rows} - {None}
    full = sum(1 for r in rows if r[1] <= 0)
    last = rows[-1]
    updated = parse_hvidate(last[2])
    return {
        "updates": len(stamps),
        "fullShare": round(full / len(rows), 3),
        "minBeds": min(r[1] for r in rows), "maxBeds": max(r[1] for r in rows),
        "lastValue": last[1], "lastAt": last[0].isoformat(),
        "lastUpdateAgeMin": round((last[0].replace(tzinfo=None) - updated).total_seconds() / 60, 1) if updated else None,
    }


def _chart(rows: list[tuple[datetime, int, str]]) -> list[dict]:
    step = max(1, len(rows) // MAX_CHART_POINTS)
    return [{"t": ts.isoformat(), "v": v} for ts, v, _ in rows[::step]]


def _severe(row: dict | None) -> list[dict]:
    """15개 질환군별 최신 신고: 하나라도 Y면 가능, 불가능이 있으면 불가, 아니면 정보 없음."""
    out = []
    for group in V.GROUPS:
        values = [V.normalize_accept(row.get(item.field)) for item in V.ITEMS if item.group == group] if row else []
        status = "가능" if V.ACCEPT_YES in values else "불가능" if V.ACCEPT_NO in values else "정보 없음"
        out.append({"group": group, "egen": status})
    return out


def summarize(hpid: str, snapshot_dir: Path = SNAPSHOT_DIR) -> dict | None:
    files = sorted(snapshot_dir.glob("*.jsonl"))
    if not files:
        return None
    index = _index(tuple(str(p) for p in files), files[-1].stat().st_mtime)
    rows = index["series"].get(hpid)
    if rows:
        rows = [r for r in rows if r[0] >= rows[-1][0] - WINDOW]
    meta = index["names"].get(hpid, {})
    severe = _severe(index["accept"].get(hpid))

    designated = []
    name_key = HF.normalize_name(meta.get("name"))
    for spec in HF.load_specialty_hospitals() or []:
        if name_key and HF.normalize_name(spec.get("의료기관명")) == name_key:
            field = spec.get("지정분야")
            item_nos = HF.FIELD_TO_MKIOSK.get(field, ())
            groups = {item.group for item in V.ITEMS if item.no in item_nos}
            shown = any(s["egen"] == "가능" for s in severe if s["group"] in groups)
            designated.append({"field": field, "egen": "가능" if shown else "정보 없음"})

    specialists = []
    if SPECIALISTS_PATH.is_file():
        for row in json.loads(SPECIALISTS_PATH.read_text(encoding="utf-8")).get(hpid, []):
            name, count = row.get("dgsbjtCdNm"), int(row.get("dtlSdrCnt") or 0)
            if name in ACUTE_DEPARTMENTS and count > 0:
                specialists.append({"department": name, "count": count})
        specialists.sort(key=lambda s: -s["count"])

    rejections = [r for r in R.load_all() if r.get("hospitalId") == hpid]
    return {
        "hospitalId": hpid,
        "name": meta.get("name"),
        "emergencyLevel": meta.get("emcls"),
        "snapshots": len(rows or []),
        "period": [rows[0][0].isoformat(), rows[-1][0].isoformat()] if rows else None,
        "chart": _chart(rows) if rows else [],
        "departures": _departures(rows) if rows else None,
        "rhythm": _rhythm(rows) if rows else None,
        "severe": severe,
        "designated": designated,
        "specialists": specialists[:8],
        "rejections": {
            "count": len(rejections),
            "byReason": [{"code": c, "label": R.REASON_AXIS.get(c, (None, c))[1], "count": n}
                         for c, n in Counter(r.get("reasonCode") or "UNSPECIFIED" for r in rejections).most_common()],
            "recent": [{"timestamp": r.get("timestamp"), "code": r.get("reasonCode"),
                        "label": R.REASON_AXIS.get(r.get("reasonCode"), (None, r.get("reasonCode")))[1]}
                       for r in sorted(rejections, key=lambda r: r.get("timestamp") or "")[-6:]],
        },
    }


def _selftest() -> None:
    t0 = datetime(2026, 10, 1, 12, 0)
    rows = [(t0 + timedelta(minutes=20 * i), v, f"2026100112{i:02d}00") for i, v in enumerate([5, 5, 1, -1, 4, 8])]
    d = _departures(rows)
    # 5→5 그대로, 5→1 크게, 1→-1 만실, (-1 출발 안 함), 4→8 크게
    assert (d["same"], d["changedSmall"], d["changedBig"], d["becameFull"]) == (1, 0, 2, 1), d
    assert d["worst"]["bedsAtArrival"] == 1, "가장 크게 줄어든 5→1"
    r = _rhythm(rows)
    assert r["fullShare"] == round(1 / 6, 3) and r["minBeds"] == -1
    assert [s["egen"] for s in _severe(None)] == ["정보 없음"] * len(V.GROUPS)
    print("hospital_view 자체 검사 통과")


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--selftest"]:
        _selftest()
    else:
        result = summarize(sys.argv[1])
        if result:
            result["chart"] = f"{len(result['chart'])}점"
        print(json.dumps(result, ensure_ascii=False, indent=1))
