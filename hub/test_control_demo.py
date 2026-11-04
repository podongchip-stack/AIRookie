"""관제 시연 상황 부여 · 다수 사상자 신고(2026-11-04) 앱 레이어 검사 — 실제 상태·로그는 건드리지 않는다(임시 경로).

① [충돌 상황] → 권역센터 여력 1 · 사건 2건 → 관제 배정 요청(assignment_conflicts)
② [수용 곤란 상황] → 다음 사건에서 그 병원에 학습 반영(+분)
③ [수용 회신 없음] · [최근 차단 공지] 사건이 만들어진다
④ [다수 사상자 신고] → 반경 병원 집계·예상 분배·구급대 추천(mci_assessment), 관제 소켓만

실행: python test_control_demo.py
"""
from __future__ import annotations

import os
import random
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decision_log.jsonl")
os.environ["HUB_RECORD_DB_PATH"] = str(Path(_TMP.name) / "records.sqlite3")
os.environ["HOSPITAL_REJECTION_LOG_DIR"] = str(Path(_TMP.name) / "rejections")
os.environ["HUB_REJECTION_URL"] = "http://127.0.0.1:9/hub/rejection"
os.environ["HUB_SPIDER_HOUR"] = "14"

import app  # noqa: E402
from ambulance_sim import DispatchSim  # noqa: E402
from schema import AmbulanceInfo, DashboardIdentify, GpsPoint, HospitalInfo  # noqa: E402
from test_app_background import _FakeSocket  # noqa: E402
from test_real_hospitals import real_capability  # noqa: E402


def _flush() -> None:
    app._match_executor.submit(lambda: None).result(timeout=120)


def _of(sock, type_):
    return [m for m in sock.sent if m.get("type") == type_]


def _setup():
    app.sim = DispatchSim(None, random.Random(1), pool_dir=Path(_TMP.name) / "sim")
    for hid, lat, level, name in (("C1", 37.5700, "권역응급의료센터", "서울대학교병원"),
                                  ("C2", 37.5600, "지역응급의료센터", "강북삼성병원"),
                                  ("C3", 37.5750, "지역응급의료센터", "강북삼성병원")):
        app.engine.update_hospital_info(HospitalInfo(
            hospitalId=hid, name=f"[테스트] {hid}", gps=GpsPoint(lat=lat, lng=126.9800), availableBedCount=4,
            bedsByType={"ER_ADULT": 4}, nightDutyAvailable=True, updatedAt="2026-11-04T00:00:00Z",
            **{**real_capability(name), "emergencyLevel": level}))
    client = app.app.test_client()
    for i in range(10):
        client.post("/info/ambulances", json=AmbulanceInfo(
            apid=f"A{i}", name=f"[테스트] 구급 {i}호차", gps=GpsPoint(lat=37.566 + i * 0.001, lng=126.978),
            voicePort=6000, updatedAt="2026-11-04T00:00:00Z").model_dump())
    monitor = _FakeSocket()
    app._dashboard_sockets.add(monitor)
    app._handle_identify(monitor, DashboardIdentify(role="monitor", id="map"))
    return monitor


def main() -> None:
    monitor = _setup()

    print("=== ① 충돌 상황 ===")
    app._run_demo_scenario("conflict", monitor)
    _flush()
    assert _of(monitor, "action_result")[-1]["ok"], _of(monitor, "action_result")[-1]
    groups = app._assignment_snapshot()["groups"]
    assert groups and groups[0]["hospitalId"] == "C1" and len(groups[0]["caseIds"]) == 2, groups
    assert all(c.startswith("demo-") for c in groups[0]["caseIds"])
    print(f"  [확인] {groups[0]['hospitalName']} 여력 {groups[0]['capacity']} · 사건 2건 → 관제 배정 요청")
    case_a = groups[0]["caseIds"][0]
    apid_a = app.engine.get_case_apid(case_a)
    assert app.sim.phase_of(apid_a) == "on_scene", "시연 사건 구급차는 현장 도착 상태 — 확정되면 출발한다"
    app._handle_dashboard_action({"caseId": case_a, "action": "final_approval", "hospital_id": "C1", "actor": "dispatcher",
                                  "timestamp": "2026-11-04T00:00:00Z"}, ws=monitor)
    assert app.sim.phase_of(apid_a) == "transporting", "관제 지정 → 병원으로 이송 시작(사건이 끝까지 진행)"
    print("  [확인] 시연 사건 구급차 현장 도착 → 관제 지정 시 이송 출발")
    for _ in range(3):  # 이송을 끝까지 — 시연 시뮬레이션 시계를 몇 번 크게 넘긴다
        app.sim._clock = (lambda base=app.sim._clock(): (lambda: base + 3600))()
        app._sim_tick()
    assert app.sim.phase_of(apid_a) == "at_hospital", app.sim.phase_of(apid_a)
    app._demo_arrived_at.clear()  # _sim_tick이 실제 시각으로 이미 적어 둔 도착 시각을 지우고 시험 시각으로
    app._demo_auto_accept(now=0.0)
    app._demo_auto_accept(now=10.0)
    assert app.engine.get_case_result(case_a).arrival.result == "accepted", "병원 도착 5초 뒤 시연 사건은 자동 수용 완료"
    print("  [확인] 시연 사건: 병원 도착 → 5초 뒤 자동 수용 완료(사건 종료)")

    print("=== ② 수용 곤란 상황(학습 반영) ===")
    app._run_demo_scenario("refusal", monitor)
    _flush()
    result = _of(monitor, "action_result")[-1]
    assert result["ok"], result
    reasons = [h.refusalReasons for cid in app.engine.list_open_case_ids() if (r := app.engine.get_case_result(cid))
               for h in r.hospitals if h.refusalReasons]
    assert reasons and "수술실 사용 중" in reasons[0][0], reasons
    print(f"  [확인] {result['reason']} — 다음 사건에 '{reasons[0][0]}'")

    print("=== ③ 수용 회신 없음 · 최근 차단 공지 ===")
    for kind in ("no_accept", "recent_block"):
        app._run_demo_scenario(kind, monitor)
        _flush()
        res = _of(monitor, "action_result")[-1]
        print(f"  {kind}: ok={res['ok']} {res['reason']}")
    held = [h for cid in app.engine.list_open_case_ids() if (r := app.engine.get_case_result(cid))
            for h in r.hospitals if h.dispatchHold]
    assert held, "최근 차단 공지 병원은 첫 동시 전송에서 보류"
    print("  [확인] 최근 차단 공지 병원 → dispatchHold")

    print("=== ④ 다수 사상자 신고 ===")
    stranger = _FakeSocket()
    app._dashboard_sockets.add(stranger)
    app._handle_identify(stranger, DashboardIdentify(role="hospital", id="C1"))
    app._handle_mci_register(stranger, {"lat": 37.566, "lng": 126.978, "counts": {"중증": 1}})
    assert _of(stranger, "action_refused")[-1]["reason"] == "not_dispatcher"
    app._handle_mci_register(monitor, {"lat": 37.566, "lng": 126.978, "counts": {"중증": 2, "중등증": 1, "경증": 2}, "label": "테스트 화재"})
    a = _of(monitor, "mci_assessment")[-1]
    assert a["total"] == 5 and a["hospitalsInRadius"] == 3 and sum(p["count"] for p in a["plan"]) + a["unplaced"] == 5, a
    assert [s["stage"] for s in a["steps"]] == ["인식", "판단", "행동"] and a["source"] == "rule"
    assert a["neededAmbulances"] == 4, "중증 2 + 중등증 1 + 경증 2명(1대) = 4대"
    app._handle_mci_register(monitor, {"lat": 37.566, "lng": 126.978, "counts": {"중증": 20}})
    big = _of(monitor, "mci_assessment")[-1]
    assert big["neededAmbulances"] == 20 and big["shortage"] == 20 - len(big["ambulances"]) > 0, "모자라면 부족 대수를 알린다"
    print(f"  [확인] 병원 {a['hospitalsInRadius']}곳 집계 · 분배 {[(p['name'], p['count']) for p in a['plan']]} · 구급대 {len(a['ambulances'])}대 추천")
    print("\n모든 검사 통과")


if __name__ == "__main__":
    main()
