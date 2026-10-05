"""관제 지도용 전체 병원 주입 — info 프로세스 없이, 저장소의 실측 캐시로 채운다.

- 좌표·이름: sim/data/egen_coords.json (전국 529곳, 커밋됨)
- 가용 병상·등급: info 스냅샷(snapshots_nationwide)의 최신 기록 — 없으면 병상 미상으로만 주입
실행:  python seed_all_hospitals.py   (conda rookie_info)
"""
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import NormalDist

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "sim"))  # .claude/skills/run-demo → 저장소 루트
from data_load import COORDS_DIR, SNAPSHOT_DIR, load_beds, load_coords, load_levels  # noqa: E402

HUB = "http://127.0.0.1:5001"

coords = load_coords()
dates = sorted(p.stem for p in SNAPSHOT_DIR.glob("*.jsonl"))
beds, levels, snapshot_ts = {}, {}, None
if dates:
    snapshot_ts, beds = load_beds(dates[-1], "12:00")
    levels = load_levels(dates[-1])

now_dt = datetime.now(timezone.utc)
now = now_dt.isoformat(timespec="seconds")

_NORMAL = NormalDist()


def _demo_reliability(key: str, rel: dict | None) -> dict:
    """병상 신뢰도(bedReliability)를 데모용으로 채운다 — 이게 없으면 첫 후보 리스트의
    "AI · 도착 시 유효 N%" 칩과 첫 연락 추천이 시연에서 아예 안 뜬다.

    - 캐시에 실모델 값이 있으면: 곡선 파라미터(predictedSurvivalSec·sigma)는 그대로 두고
      bornAt만 데모 시점 기준(병원별 고정 5~114분 전)으로 재날인한다. 수집 시점 bornAt을
      그대로 보내면 나이가 며칠로 계산돼 유효 확률이 0%로 뜨기 때문(그래서 한동안
      떼어냈는데, 그러면 칩이 안 보인다). modelTag에 reseed 표시로 실측 전송과 구분.
    - 캐시에 없으면(이 장비 캐시는 reliability 엔진 미기동 상태에서 저장돼 전부 없음):
      병원별 고정 가상 곡선(예측 수명 1~8시간)을 만든다. modelTag "demo-가상값".

    스냅샷 필드(authorityAtSend·ttlSec)는 hub와 같은 수식으로 재계산한다
    (hub/bed_reliability.py — hub는 어차피 매칭 시점마다 재계산하므로 로그·대조용)."""
    digest = int(hashlib.md5(key.encode()).hexdigest(), 16)
    age_min = digest % 110 + 5
    if rel is None:
        rel = {"predictedSurvivalSec": (digest // 110 % 29 + 4) * 900.0,  # 1~8시간
               "sigma": 1.0, "modelTag": "demo-가상값", "source": "ai"}
    else:
        rel = {**rel, "modelTag": f"{rel.get('modelTag') or 'aft'}+demo-reseed"}
    born = now_dt - timedelta(minutes=age_min)
    pred = max(float(rel.get("predictedSurvivalSec") or 3600.0), 1e-9)
    sigma = max(float(rel.get("sigma") or 1.0), 1e-9)
    age_sec = age_min * 60.0
    authority = 0.5 * math.erfc((math.log(age_sec) - math.log(pred)) / (sigma * math.sqrt(2)))
    ttl = max(pred * math.exp(sigma * _NORMAL.inv_cdf(0.2)) - age_sec, 0.0)
    return {**rel, "bornAt": born.isoformat(timespec="seconds"),
            "authorityAtSend": round(authority, 4), "ttlSec": round(ttl, 1)}

# 구급대 — 발생 지점에 따라 다른 구급대가 출동하는 실무 흐름을 재현한다
# (콘솔 ①이 발생 지점에서 기지가 가장 가까운 대기 구급차를 자동 선정, 전부 출동 중이면 폴백).
#
# 실제 현장 적용: 실시간 구급차 위치·출동 상태의 공공 API는 없다(소방 내부망) — 공개된 건
# 공공데이터포털의 정적 현황이다: "소방청_전국 119안전센터 현황"(주소·좌표),
# "소방청_시도 소방본부별 구급차 보유 현황". 활용신청 후 받아서 이 폴더의
# **stations.json**([{"apid","name","lat","lng"}, ...])으로 두면 그 목록이 유한한 실제
# fleet이 된다 — 무한정 출동이 아니라 "센터 수 × 보유 대수"가 상한. 없으면 기본 3곳.
AMBULANCES = [
    {"apid": "A0000001", "name": "회현 구급대 1호차", "gps": {"lat": 37.5586, "lng": 126.9784}},  # 중구
    {"apid": "A0000002", "name": "성산 구급대 2호차", "gps": {"lat": 37.5664, "lng": 126.9023}},  # 마포
    {"apid": "A0000003", "name": "역삼 구급대 3호차", "gps": {"lat": 37.5006, "lng": 127.0364}},  # 강남
]
stations_path = Path(__file__).with_name("stations.json")
if stations_path.exists():
    import json as _json
    rows = _json.loads(stations_path.read_text(encoding="utf-8"))
    AMBULANCES = [
        {"apid": r["apid"], "name": r["name"], "gps": {"lat": r["lat"], "lng": r["lng"]}} for r in rows
    ]
    print(f"stations.json — 실제 안전센터 {len(AMBULANCES)}곳을 fleet으로 사용")
for ambulance in AMBULANCES:
    requests.post(f"{HUB}/info/ambulances", json={**ambulance, "voicePort": 6001, "updatedAt": now},
                  timeout=10).raise_for_status()
print(f"구급대 {len(AMBULANCES)}곳 주입")

# 치과·한방 계열은 뺀다 — E-Gen 목록에 '응급실운영신고기관'으로 실재하지만(실측:
# A1107402 서울대학교치과병원, hvec 보고 없음) 치과 응급진료 신고라 일반 환자 이송
# 후보·관제 지도에 뜨면 시연에서 오해를 부른다. 실운영 필터 정책(info 피드 제외 vs
# hub 강등)은 팀 결정 사항 — 이건 데모 시드 전용 필터다.
def _is_acute(name: str) -> bool:
    return not any(word in name for word in ("치과", "한방", "한의"))

# 서울 55곳은 info의 실제 상세 캐시(data/output/<hpid>.json — 진료과·심평원 전문의 수·
# assessment까지 실측 HospitalInfo 전문)를 그대로 쓴다(2026-10-04). 병상·갱신시각은 오늘
# 스냅샷으로 덮고, bedReliability류는 bornAt만 데모 시점으로 재날인한다(_restamp_reliability
# — 예전엔 낡은 값이라 통째로 떼어냈는데, 그러면 신뢰도 칩·첫 연락 추천이 시연에서 안 보인다).
detailed: dict[str, dict] = {}
for path in sorted(COORDS_DIR.glob("*.json")):
    d = json.loads(path.read_text(encoding="utf-8"))
    detailed[d["hospitalId"]] = d

ok, failed = 0, 0
for hpid, (name, lat, lng) in coords.items():
    if not _is_acute(name):
        continue
    if hpid in detailed:
        body = dict(detailed[hpid])
        body["updatedAt"] = now
        if hpid in beds or "ER_ADULT" in (body.get("bedsByType") or {}):
            # 병상 수가 확인된 병원만 — "이 숫자가 유효할 확률"이라 미상 병원엔 의미가 없다
            body["bedReliability"] = _demo_reliability(hpid, body.get("bedReliability"))
        else:
            body.pop("bedReliability", None)
        if body.get("bedReliabilityByType"):
            body["bedReliabilityByType"] = {
                field: _demo_reliability(hpid + field, rel)
                for field, rel in body["bedReliabilityByType"].items()
            }
        else:
            body.pop("bedReliabilityByType", None)
        if hpid in beds:
            body["availableBedCount"] = max(beds[hpid], 0)
            body["bedsByType"] = {**(body.get("bedsByType") or {}), "ER_ADULT": max(beds[hpid], 0)}
        if levels.get(hpid) and not body.get("emergencyLevel"):
            body["emergencyLevel"] = levels[hpid]
    else:
        body = {
            "hospitalId": hpid, "name": name, "gps": {"lat": lat, "lng": lng},
            "availableBedCount": max(beds.get(hpid, 0), 0),
            "nightDutyAvailable": False, "specialties": [], "updatedAt": now,
        }
        if hpid in beds:
            # 키가 있어야 '확인된 값'으로 읽힌다 — 없으면 hub가 병상 미상으로 분류(올바른 동작)
            body["bedsByType"] = {"ER_ADULT": max(beds[hpid], 0)}
            body["bedReliability"] = _demo_reliability(hpid, None)
        if levels.get(hpid):
            body["emergencyLevel"] = levels[hpid]
    try:
        requests.post(f"{HUB}/info/hospitals", json=body, timeout=10).raise_for_status()
        ok += 1
    except Exception as e:  # noqa: BLE001
        failed += 1
        if failed <= 3:
            print(f"  실패 {hpid} {name}: {e}")
print(f"{ok}곳 주입({failed} 실패) — 병상 출처 스냅샷 {snapshot_ts or '없음(전부 미상)'}")

# 전체 목록(roster)을 보내 이번 필터에 걸렸거나 이전 시드가 남긴 병원(치과·데모 등)을
# hub에서 걷어낸다 — info 상시 프로세스의 한 주기 끝 신호와 같은 메커니즘.
roster = [hpid for hpid, (name, _, _) in coords.items() if _is_acute(name)]
r = requests.post(f"{HUB}/info/hospitals/roster", json={"hospitalIds": roster}, timeout=30)
removed = r.json().get("removed", [])
if removed:
    print(f"roster 정리 — 제거 {len(removed)}곳: {', '.join(removed[:5])}{' …' if len(removed) > 5 else ''}")
