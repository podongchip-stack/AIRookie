"""[배후역량] GET /hospital-backup(2026-10-08) 검증.

- 병상 줄: 보유(심평원)·E-Gen 정원·지금 가용(이송 확정 차감 반영)을 나란히, 값이 하나도 없는 줄은 뺀다
- 장비 줄: 심평원 보유 대수와 E-Gen 운영 Y/N — 혈관조영은 심평원 항목이 없다는 설명, 지금 남은 대수 칸은 없다
- 심평원 캐시가 없는 병원(backupCapacity 없음)·구 info 데이터도 그대로 통과(보유 칸만 빈다)
- 모르는 병원은 404, CORS 열림

    python hub/test_backup_view.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decision_log.jsonl")

import app  # noqa: E402
from hub_engine import HubEngine  # noqa: E402
from schema import ApprovalAction, BackupCapacity, GpsPoint, HospitalInfo, Specialty  # noqa: E402
from test_acceptance_messages import SCENE, _FakeMatcher, _voice  # noqa: E402


def _hospital(hpid: str, backup: bool) -> HospitalInfo:
    return HospitalInfo(
        hospitalId=hpid, name=f"[테스트] {hpid}", gps=GpsPoint(lat=37.5700, lng=126.9780),
        availableBedCount=5, nightDutyAvailable=True, updatedAt="2026-10-08T00:00:00Z",
        specialties=[Specialty(department="심장혈관흉부외과", doctorCount=4), Specialty(department="내과", doctorCount=0)],
        bedsByType={"ER_ADULT": 5, "OR": 3, "ICU": 2}, bedCapacityByType={"ER_ADULT": 20, "OR": 16, "ICU": 65},
        equipmentOperating={"ECMO": "Y", "ANGIO": "Y", "CT": "N1"},
        backupCapacity=BackupCapacity(
            equipment={"ECMO": 2, "CT": 5, "혈액투석을위한인공신장기": 49, "분만감시기": 18, "골밀도검사기": 2},
            operatingRooms=16, icuTotal=80, nicu=26,
            generalWard=646, nursingGrade="1", collectedAt="2026-10-07T16:02:34+00:00",
        ) if backup else None,
    )


def main() -> None:
    engine = HubEngine(specialty_matcher=_FakeMatcher())
    app.engine = engine
    engine.update_hospital_info(_hospital("K001", backup=True))
    engine.update_hospital_info(_hospital("K002", backup=False))
    client = app.app.test_client()

    print("=== 세 층 조립 ===")
    response = client.get("/hospital-backup?id=K001")
    assert response.status_code == 200 and response.headers.get("Access-Control-Allow-Origin") == "*"
    body = response.get_json()
    beds = {row["key"]: row for row in body["beds"]}
    assert (beds["OR"]["hiraCapacity"], beds["OR"]["egenCapacity"], beds["OR"]["available"]) == (16, 16, 3)
    assert (beds["ICU"]["hiraCapacity"], beds["ICU"]["egenCapacity"], beds["ICU"]["available"]) == (80, 65, 2)
    assert beds["ICU"]["note"], "중환자실은 심평원(총량)·E-Gen(일반)의 범위 차이를 밝힌다"
    assert beds["NICU"]["hiraCapacity"] == 26 and beds["NICU"]["available"] is None
    assert "ER_PEDIATRIC" not in beds, "값이 하나도 없는 줄은 빼야 한다"
    equipment = {row["key"]: row for row in body["equipment"]}
    assert (equipment["ECMO"]["hiraCount"], equipment["ECMO"]["egenOperating"]) == (2, "Y")
    assert equipment["ANGIO"]["hiraCount"] is None and equipment["ANGIO"]["note"], "혈관조영은 심평원 항목 없음을 밝힌다"
    assert equipment["HD"]["hiraCount"] == 49 and equipment["CT"]["egenOperating"] == "N1"
    assert equipment["FETAL_MONITOR"]["hiraCount"] == 18 and equipment["FETAL_MONITOR"]["egenOperating"] is None
    assert all(row["label"] != "골밀도검사기" for row in body["equipment"]), "배후진료와 무관한 심평원 장비는 싣지 않는다"
    assert all("available" not in row for row in body["equipment"]), "장비엔 지금 남은 대수 칸이 없다(공개 정보 없음)"
    assert [s["department"] for s in body["specialties"]] == ["심장혈관흉부외과"], "전문의 0명인 과는 뺀다"
    assert body["nursingGrade"] == "1" and body["hiraCollectedAt"] and body["source"] == "rule"
    print("  [확인] 병상 보유·정원·가용, 장비 보유·운영, 혈관조영 설명, 전문의·간호등급")

    print("=== 이송 확정 차감 반영 ===")
    engine.register_case("case-backup", "A0000099")
    engine.process_voice_summary(_voice("case-backup"), SCENE, max_zone=1)
    for action, actor in (("hospital_approve", "hospital"), ("final_approval", "paramedic")):
        engine.apply_approval_action(ApprovalAction(caseId="case-backup", action=action, hospital_id="K001",
                                                    actor=actor, timestamp="2026-10-08T00:00:00Z"))
    body = client.get("/hospital-backup?id=K001").get_json()
    er = next(row for row in body["beds"] if row["key"] == "ER_ADULT")
    assert er["available"] == 4 and body["inFlightCount"] == 1
    print("  [확인] 응급실 가용 5 → 4, 이송 중 1건")

    print("=== 심평원 캐시 없는 병원 · 모르는 병원 ===")
    body = client.get("/hospital-backup?id=K002").get_json()
    assert all(row["hiraCapacity"] is None for row in body["beds"]) and body["nursingGrade"] is None
    assert {row["key"] for row in body["equipment"]} == {"ECMO", "ANGIO", "CT"}, "E-Gen 운영 정보만 있는 줄은 남는다"
    assert client.get("/hospital-backup?id=NOPE").status_code == 404
    assert client.get("/hospital-backup").status_code == 404
    print("  [확인] 보유 칸만 비고 E-Gen 값은 그대로, 모르는 병원은 404")
    print("\ntest_backup_view 통과")


if __name__ == "__main__":
    main()
