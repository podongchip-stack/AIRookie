"""충돌 장면 시드: 병원 3곳(권역 H001 병상 1) · 구급차 3대 · 사건 3건 → H001이 셋 다 수용 → 1순위 겹침 + 여력 1 → 관제 판단 대기.
H002(지역센터)는 B·C만 수용. 이송 확정은 하지 않는다(관제 화면에서 확인)."""
import json
import time
from datetime import datetime, timezone

import requests
from simple_websocket import Client

HUB, WS = "http://127.0.0.1:5001", "ws://127.0.0.1:5001/ws/dashboard"
now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")

hospitals = [
    ("H001", "권역센터병원(데모)", 37.5700, 126.9850, 1, "권역응급의료센터", 15),
    ("H002", "지역센터병원(데모)", 37.5560, 126.9720, 3, "지역응급의료센터", 6),
    ("H003", "지역기관병원(데모)", 37.5510, 126.9880, 2, "지역응급의료기관", 3),
]
for hid, name, lat, lng, beds, level, em in hospitals:
    requests.post(f"{HUB}/info/hospitals", json={
        "hospitalId": hid, "name": name, "gps": {"lat": lat, "lng": lng}, "availableBedCount": beds,
        "bedsByType": {"ER_ADULT": beds}, "nightDutyAvailable": True, "emergencyLevel": level,
        "specialties": [{"department": "응급의학과", "doctorCount": em}, {"department": "순환기내과", "doctorCount": 4}],
        "equipmentOperating": {"CT": "Y", "ANGIO": "Y" if level != "지역응급의료기관" else "N"}, "updatedAt": now(),
    }, timeout=10).raise_for_status()

# 돌릴 때마다 새 사건 ID — 같은 ID를 다시 쓰면 지난번 확정이 남아 충돌이 다시 생기지 않는다
RUN = datetime.now().strftime("%H%M%S")
cases = [  # (caseId, apid, 구급대 이름, 위치, KTAS, 주 호소)
    (f"case-A-{RUN}", "A0000001", "구급 1호차", (37.5665, 126.9780), 1, "심정지 의심"),
    (f"case-B-{RUN}", "A0000002", "구급 2호차", (37.5640, 126.9800), 2, "뇌졸중 의심"),
    (f"case-C-{RUN}", "A0000003", "구급 3호차", (37.5620, 126.9760), 3, "복통"),
]
for _, apid, name, (lat, lng), _, _ in cases:
    requests.post(f"{HUB}/info/ambulances", json={"apid": apid, "name": name, "gps": {"lat": lat, "lng": lng},
                                                  "voicePort": 6001, "updatedAt": now()}, timeout=10).raise_for_status()
print("레지스트리 주입 완료")

socks = {}
for case_id, apid, *_ in cases:
    s = Client.connect(WS)
    s.send(json.dumps({"type": "identify", "role": "ambulance", "id": apid}))
    s.send(json.dumps({"type": "call_signal", "signal": "call_started", "timestamp": now(), "apid": apid,
                       "caseId": case_id, "device": "tablet"}))
    socks[case_id] = s
time.sleep(1)
for case_id, apid, *_ in cases:
    socks[case_id].send(json.dumps({"type": "call_signal", "signal": "call_ended", "timestamp": now(), "apid": apid,
                                    "caseId": case_id, "device": "tablet"}))

for case_id, _, _, _, ktas, cc in cases:
    requests.post(f"{HUB}/voice/summary", json={
        "caseId": case_id, "source": "ai", "transcript": {"raw_text": cc, "filtered_text": cc},
        "summary": {"ktas_level": ktas, "chief_complaint": {"major": cc, "minor": cc}},
    }, timeout=10).raise_for_status()
print("요약 3건 전송 — 매칭 대기")
time.sleep(8)

hosp = {}
for hid in ("H001", "H002"):
    h = Client.connect(WS)
    h.send(json.dumps({"type": "identify", "role": "hospital", "id": hid}))
    hosp[hid] = h
time.sleep(1)
a, b, c = (cid for cid, *_ in cases)
for case_id, hid in ((a, "H001"), (b, "H001"), (c, "H001"), (b, "H002"), (c, "H002")):
    hosp[hid].send(json.dumps({"action": "hospital_approve", "hospital_id": hid, "actor": "hospital",
                               "timestamp": now(), "caseId": case_id}))
    time.sleep(0.5)
time.sleep(2)

for case_id, s in socks.items():
    pending = None
    while True:
        msg = s.receive(timeout=1)
        if msg is None:
            break
        d = json.loads(msg)
        if d.get("type") == "dispatcher_pending":
            pending = d
    print(case_id, "관제 판단 대기:", pending and (pending["pending"], pending["hospitalName"]))
for s in [*socks.values(), *hosp.values()]:
    s.close()
