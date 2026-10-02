"""hvec의 -1은 과밀(만실 0), 다른 병상 필드의 -1은 미상인지 확인한다 (2026-10-01).

    cd info/Hospital_inform/info && python -m egen.test_hvec_minus_one
"""
from datetime import datetime, timezone

from egen.mapper import build_beds_by_type, clean_count
from hospital_score.scoring import build_conditions

assert clean_count("-1", "hvec") == -1 and clean_count("-1", "hv2") is None and clean_count("-1") is None
beds = build_beds_by_type({"hvec": "-1", "hv2": "-1", "hvs38": "20"})
assert beds.get("ER_ADULT") == 0, "hvec -1 → 확인된 만실(0)"
assert len(beds) == 1, "hv2 -1은 미상이라 키가 없다"
cond = build_conditions({"hvec": "-1", "hvs38": "20"}, datetime.now(timezone.utc))
assert cond.overcrowded and not cond.bedCountUnknown
print("hvec -1 검사 통과")
