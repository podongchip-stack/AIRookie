"""E-Gen 신고 ↔ 다른 근거 대조 — 신뢰도 검증 화면용 요약 (2026-10-02).

report.py의 2절(신선도)·7절(전문병원 지정 대조)과 같은 계산을, 가장 최근 스냅샷 하루치로 짧게 JSON으로 낸다.
E-Gen 값은 전부 병원 자신의 신고라 같은 소스 안에서는 틀렸는지 알 수 없다 — 그래서 복지부 전문병원 지정
(심평원, 병원 신고가 아님)과 대조한다. 지정은 "전문성 인증"이지 "지금 받을 수 있다"는 아니므로, 화면에는
"E-Gen에는 안 보인다"로만 말한다.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from . import dataset as D
from . import hira_files as HF
from . import vocabulary as V

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "snapshots_nationwide"
STALE_AFTER = timedelta(days=1)


def summarize(snapshot_dir: Path = SNAPSHOT_DIR) -> dict | None:
    files = sorted(snapshot_dir.glob("*.jsonl"))
    if not files:
        return None
    return _summarize(tuple(str(p) for p in files[-2:]), files[-1].stat().st_mtime)


@lru_cache(maxsize=2)
def _summarize(paths: tuple[str, ...], _mtime: float) -> dict | None:  # 마지막 파일 mtime이 바뀌면 다시 계산
    hospitals = D.load_hospitals([Path(p) for p in paths])
    frames = D.load_frames([Path(paths[-1])])
    if not frames:
        return None
    last = frames[-1]
    now = last.ts.replace(tzinfo=None)

    stale = []
    for hpid, row in last.beds.items():
        updated = D.parse_hvidate(row.get("hvidate"))
        if updated is not None and now - updated > STALE_AFTER:
            stale.append({"name": hospitals[hpid].name if hpid in hospitals else hpid,
                          "days": (now - updated).days, "beds": D.parse_bed_count(row.get("hvec"))})
    stale.sort(key=lambda s: -s["days"])

    values = Counter(v for row in last.accept.values() for v in row.values())
    total = sum(values.values())

    specialty_rows = HF.load_specialty_hospitals() or []
    by_name = {HF.normalize_name(h.name): h for h in hospitals.values()}
    fields = []
    for field, item_nos in HF.FIELD_TO_MKIOSK.items():
        matched = [by_name[HF.normalize_name(r.get("의료기관명"))] for r in specialty_rows
                   if r.get("지정분야") == field and HF.normalize_name(r.get("의료기관명")) in by_name]
        rows = []
        for hospital in matched:
            observed = [v for no, v in (last.accept.get(hospital.hpid) or {}).items() if no in item_nos]
            egen = "가능" if V.ACCEPT_YES in observed else "불가능" if V.ACCEPT_NO in observed else "정보 없음"
            rows.append({"name": hospital.name, "egen": egen})
        if rows:
            fields.append({"field": field, "hospitals": rows, "notShown": sum(r["egen"] != "가능" for r in rows)})

    return {
        "source": "rule",
        "asOf": last.ts.isoformat(),
        "hospitals": len(last.beds),
        "staleBeds": stale[:5], "staleCount": len(stale),
        "severeCells": total, "severeUnknown": values.get(V.ACCEPT_UNKNOWN, 0),
        "specialty": fields,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(summarize(), ensure_ascii=False, indent=1))
