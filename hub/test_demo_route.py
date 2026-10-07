"""관제 지도 자동 시연 경로(/route/demo) 검사(2026-10-07) — 좌표를 받지 않고 ID·현장 번호로만 답하며, 현장은 구급차마다
고정이고, 길찾기는 캐시·하루 한도를 지킨다. 카카오는 부르지 않는다(가짜 router).

    python test_demo_route.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decision_log.jsonl")
os.environ["HOSPITAL_REJECTION_LOG_DIR"] = str(Path(_TMP.name) / "rejections")

import app  # noqa: E402
from schema import AmbulanceInfo, GpsPoint  # noqa: E402
from test_app_background import _hospital  # noqa: E402


class _FakeRouter:
    calls = 0

    def route(self, origin: GpsPoint, dest: GpsPoint) -> dict:
        _FakeRouter.calls += 1
        mid = [(origin.lat + dest.lat) / 2 + 0.001, (origin.lng + dest.lng) / 2]
        return {"path": [[origin.lat, origin.lng], mid, [dest.lat, dest.lng]], "durationSec": 300, "distanceM": 2000}


def main() -> None:
    app.router = _FakeRouter()
    client = app.app.test_client()
    client.post("/info/ambulances", json=AmbulanceInfo(apid="A1", name="[테스트] A1", gps=GpsPoint(lat=37.5665, lng=126.978),
                                                      voicePort=6000, updatedAt="2026-10-07T00:00:00Z").model_dump())
    hospital = _hospital(beds=5)
    app.engine.update_hospital_info(hospital)

    d1 = client.get("/route/demo?apid=A1&scene=2").get_json()
    d2 = client.get("/route/demo?apid=A1&scene=2").get_json()
    assert d1["point"] == d2["point"] and d1["point"] is not None, "같은 구급차·현장 번호면 같은 현장"
    assert d1["path"] and len(d1["path"]) == 3, d1
    assert _FakeRouter.calls == 1, "두 번째는 캐시"
    t = client.get(f"/route/demo?apid=A1&scene=2&leg=transport&hospitalId={hospital.hospitalId}").get_json()
    assert t["toHospital"] and t["back"], t
    assert client.get("/route/demo?apid=없음").get_json()["point"] is None, "모르는 구급차는 좌표 없음"

    app.DEMO_ROUTE_PER_DAY = _FakeRouter.calls  # 한도 소진 → 새 경로는 null(대시보드가 직선으로)
    assert client.get("/route/demo?apid=A1&scene=4").get_json()["path"] is None
    print("모든 검사 통과")


if __name__ == "__main__":
    main()
