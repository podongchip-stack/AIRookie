"""데모 준비: 병원 3곳·구급차 1대 주입 → 통화 신호(사건 바인딩) → 가짜 voice 요약 →
병원 승인 → 이송 확정. 이후 /vitals로 시나리오를 틀면 구급차 탭에서 패널이 보인다."""
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from statistics import NormalDist

import requests
from simple_websocket import Client

HUB = "http://localhost:5001"
WS = "ws://127.0.0.1:5001/ws/dashboard"
APID = "A0000001"
CASE_ID = "case-demo-transport"
now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")

_NORMAL = NormalDist()


def demo_bed_reliability(age_min: float, pred_hours: float) -> dict:
    """데모용 병상 신뢰도(infosurv 입력 형식, 가상값). 이게 없으면 첫 후보 리스트의
    "AI · 도착 시 유효 N%" 칩과 첫 연락 추천 배지가 아예 안 뜬다. hub는
    predictedSurvivalSec·bornAt·sigma로 매칭 시점마다 재계산하므로
    authorityAtSend·ttlSec은 전송 시점 스냅샷일 뿐이다(hub/bed_reliability.py와 같은 수식)."""
    born = datetime.now(timezone.utc) - timedelta(minutes=age_min)
    pred_sec = pred_hours * 3600.0
    age_sec = max(age_min * 60.0, 1e-9)
    authority = 0.5 * math.erfc((math.log(age_sec) - math.log(pred_sec)) / math.sqrt(2))
    ttl = max(pred_sec * math.exp(_NORMAL.inv_cdf(0.2)) - age_sec, 0.0)
    return {
        "predictedSurvivalSec": pred_sec, "bornAt": born.isoformat(timespec="seconds"),
        "sigma": 1.0, "authorityAtSend": round(authority, 4), "ttlSec": round(ttl, 1),
        "modelTag": "demo-가상값", "source": "ai",
    }

# ── 1. 레지스트리 주입 ──
requests.post(f"{HUB}/info/ambulances", json={
    "apid": APID, "name": "구급 1호차", "gps": {"lat": 37.5665, "lng": 126.9780},
    "voicePort": 6001, "updatedAt": now(),
}, timeout=10).raise_for_status()

hospitals = [
    {"hospitalId": "H001", "name": "서울중앙병원(데모)", "gps": {"lat": 37.5700, "lng": 126.9850},
     "availableBedCount": 5, "nightDutyAvailable": True, "emergencyLevel": "지역응급의료센터",
     "specialties": [{"department": "흉부외과", "doctorCount": 8}, {"department": "응급의학과", "doctorCount": 12}],
     "bedReliability": demo_bed_reliability(age_min=25, pred_hours=4.0),
     "updatedAt": now()},
    {"hospitalId": "H002", "name": "한강종합병원(데모)", "gps": {"lat": 37.5560, "lng": 126.9720},
     "availableBedCount": 3, "nightDutyAvailable": True, "emergencyLevel": "권역응급의료센터",
     "specialties": [{"department": "순환기내과", "doctorCount": 10}, {"department": "응급의학과", "doctorCount": 15}],
     "bedReliability": demo_bed_reliability(age_min=8, pred_hours=6.0),
     "updatedAt": now()},
    {"hospitalId": "H003", "name": "남산병원(데모)", "gps": {"lat": 37.5510, "lng": 126.9880},
     "availableBedCount": 2, "nightDutyAvailable": True,
     "specialties": [{"department": "내과", "doctorCount": 4}],
     # 일부러 낡은 값(2.5시간 전 탄생·예측 수명 1.2시간) — 낮은 확률 칩의 색 구분 확인용
     "bedReliability": demo_bed_reliability(age_min=150, pred_hours=1.2),
     "updatedAt": now()},
]
for h in hospitals:
    requests.post(f"{HUB}/info/hospitals", json=h, timeout=10).raise_for_status()
print("레지스트리 주입 완료")

# ── 2. 구급차 소켓: 통화 시작(사건-구급차 바인딩) ──
amb = Client.connect(WS)
amb.send(json.dumps({"type": "identify", "role": "ambulance", "id": APID}))
amb.send(json.dumps({"type": "call_signal", "signal": "call_started", "timestamp": now(),
                     "apid": APID, "caseId": CASE_ID, "device": "tablet"}))
time.sleep(1.0)
amb.send(json.dumps({"type": "call_signal", "signal": "call_ended", "timestamp": now(),
                     "apid": APID, "caseId": CASE_ID, "device": "tablet"}))

# ── 3. 가짜 voice 요약(v1 6필드) → 매칭 ──
requests.post(f"{HUB}/voice/summary", json={
    "caseId": CASE_ID,
    "transcript": {"raw_text": "환자 62세 남성, 흉통 호소, 혈압 150에 90 맥박 110.",
                   "filtered_text": "62세 남성, 흉통, 혈압 150/90, 맥박 110."},
    "summary": {"patient": "62세 남성", "mechanism": "흉통(심장성) — 경색 의심",
                "symptoms": ["흉통", "호흡 곤란"], "treatment": ["산소 공급", "ECG"],
                "severity_tag": "high", "required_department": "순환기내과"},
    "source": "ai",
}, timeout=10).raise_for_status()
print("voice 요약 전송 — 매칭 대기")
time.sleep(5.0)  # 매칭(임베딩 로드 포함) 대기

# ── 4. 병원 승인 → 구급대원 이송 확정 ──
hosp = Client.connect(WS)
hosp.send(json.dumps({"type": "identify", "role": "hospital", "id": "H002"}))
time.sleep(0.5)
hosp.send(json.dumps({"action": "hospital_approve", "hospital_id": "H002", "actor": "hospital",
                      "timestamp": now(), "caseId": CASE_ID}))
time.sleep(1.5)
amb.send(json.dumps({"action": "final_approval", "hospital_id": "H002", "actor": "paramedic",
                     "timestamp": now(), "caseId": CASE_ID}))
time.sleep(1.5)

# 확정 반영 확인 — 받은 메시지에서 confirmed를 찾는다
confirmed = False
try:
    while True:
        msg = amb.receive(timeout=2)
        if msg is None:
            break
        data = json.loads(msg)
        if data.get("type") == "match_result" and data.get("caseId") == CASE_ID:
            statuses = {h["hospitalId"]: h["status"] for h in data["hospitals"]}
            print("상태:", statuses)
            confirmed = statuses.get("H002") == "confirmed"
except Exception:
    pass
amb.close()
hosp.close()
print("이송 확정:", "OK" if confirmed else "확인 못 함(따라잡기로 재확인 필요)")
sys.exit(0 if confirmed else 1)
