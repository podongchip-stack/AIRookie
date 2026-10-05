"""구급차 묶음 수신·목록 동기화 검사(2026-10-04) — 실제 서버 없이 Flask test client로 부른다.

Supabase ambulances 테이블을 시연용 3대에서 서울 119 구급차로 통째로 바꿨을 때, 옛 구급차가 hub에 남지 않고
(진행 중 사건·출동 중이면 남기고) 관제 지도 전송은 주기마다 한 번만 나가는지 본다.

    python test_ambulance_roster.py
"""
from __future__ import annotations

import os
import random
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decision_log.jsonl")
os.environ["HOSPITAL_REJECTION_LOG_DIR"] = str(Path(_TMP.name) / "rejections")

import app  # noqa: E402
from ambulance_sim import DispatchSim  # noqa: E402
from schema import AmbulanceInfo, GpsPoint  # noqa: E402
from test_app_background import _FakeSocket  # noqa: E402


def _amb(apid: str, lat: float = 37.5665) -> dict:
    return AmbulanceInfo(apid=apid, name=f"[테스트] {apid}", gps=GpsPoint(lat=lat, lng=126.9780),
                         voicePort=6000, updatedAt="2026-10-04T00:00:00Z").model_dump()


def _overviews(sock: _FakeSocket) -> int:
    return sum(1 for m in sock.sent if m.get("type") == "map_overview")


def main() -> None:
    app.sim = DispatchSim(None, random.Random(1), lambda: 1_000_000.0, Path(_TMP.name) / "sim")
    client = app.app.test_client()
    monitor = _FakeSocket()
    app._dashboard_sockets.add(monitor)
    app._socket_identity[monitor] = ("monitor", "map")

    print("=== 옛 구급차 3대 등록(한 대씩) ===")
    for apid in ("A0000001", "A0000002", "A0000003"):
        assert client.post("/info/ambulances", json=_amb(apid)).status_code == 200
    app._voice_addresses["A0000003"] = "http://10.0.0.3:6003"

    print("=== 묶음 수신: 새 구급차 5대 + 형식 틀린 1대 → 관제 지도는 한 번만 ===")
    before = _overviews(monitor)
    new_ids = [f"SEL{i:04d}" for i in range(1, 6)]
    body = {"ambulances": [_amb(a) for a in new_ids] + [{"apid": "BAD", "name": "형식 틀림"}]}
    res = client.post("/info/ambulances/batch", json=body).get_json()
    assert res["accepted"] == 5 and len(res["rejected"]) == 1 and res["rejected"][0]["apid"] == "BAD", res
    assert _overviews(monitor) - before == 1, "묶음 하나에 관제 지도 전송 한 번"
    assert all(app.engine.get_ambulance_base(a) for a in new_ids) and app.sim.phase_of("SEL0001") == "idle"
    print("  [확인] 5대 반영·1대 거부, 관제 지도 1회")

    print("=== 목록 동기화: 진행 중 사건(A0000001)·출동 중(A0000002)은 남기고 A0000003만 뺀다 ===")
    app.engine.register_case("case-live", "A0000001")
    app.sim._units["A0000002"].phase = "dispatching"
    res = client.post("/info/ambulances/roster", json={"apids": new_ids}).get_json()
    assert res["removed"] == ["A0000003"] and sorted(res["kept"]) == ["A0000001", "A0000002"], res
    assert app.engine.get_ambulance_base("A0000003") is None and app.sim.phase_of("A0000003") is None
    assert "A0000003" not in app._voice_addresses, "빠진 구급차의 voice 주소도 지운다"
    assert app.engine.get_ambulance_base("A0000001") and app.engine.get_ambulance_base("A0000002")
    print("  [확인] 제거 1대, 보류 2대")

    print("=== 목록 급감·빈 목록·형식 오류는 아무것도 안 뺀다 ===")
    res = client.post("/info/ambulances/roster", json={"apids": new_ids[:1]}).get_json()
    assert res["removed"] == [], "절반 미만으로 급감하면 부분 조회 실패로 보고 안 뺀다"
    res = client.post("/info/ambulances/roster", json={"apids": []}).get_json()
    assert res["removed"] == []
    assert client.post("/info/ambulances/roster", json={"apids": "SEL0001"}).status_code == 400
    assert client.post("/info/ambulances/batch", json={"ambulances": "x"}).status_code == 400
    print("  [확인] 급감·빈 목록 무시, 형식 오류 400")

    print("=== 사건이 끝나고 출동이 끝나면 다음 주기에 빠진다 ===")
    app.engine._case_arrival["case-live"] = "accepted"  # 수용 완료된 사건은 진행 중이 아니다
    app.sim._units["A0000002"].phase = "idle"
    res = client.post("/info/ambulances/roster", json={"apids": new_ids}).get_json()
    assert sorted(res["removed"]) == ["A0000001", "A0000002"] and res["kept"] == [], res
    assert sorted(a.apid for a in app.engine.list_ambulances()) == new_ids
    print("  [확인] 남은 구급차 = 새 목록 5대")
    print("\n모든 검사 통과")


if __name__ == "__main__":
    main()
