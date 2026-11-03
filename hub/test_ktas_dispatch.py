"""KTAS 전달 필터·존 확장·재접속·철회 검사. 모델/네트워크/운영 기록을 사용하지 않는다."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "state.json")
os.environ["HUB_RECORD_DB_PATH"] = str(Path(_TMP.name) / "records.sqlite3")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decisions.jsonl")
os.environ["HUB_PERSIST_STATE"] = "0"
os.environ["HUB_SPIDER_HOUR"] = "14"

import spider_rule
from hospital_dispatch import can_receive, dashboard_payload
from hub_engine import HubEngine
from schema import AcceptanceMessage, ApprovalAction, DashboardIdentify, GpsPoint, HospitalInfo, PatientOverride, Specialty, VoiceCallSummaryMessage
from test_spider_rule import _voice

SCENE = GpsPoint(lat=37.5665, lng=126.9780)
STEMI = "심근경색"


class Matcher:
    def match_many(self, text, lists):
        return [(depts[0], 0.5) if depts else (None, 0.0) for depts in lists]


class Socket:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(json.loads(message))


def hospital(hid, level="지역응급의료기관", lat=37.5675, em=5, angio="Y", ct="Y"):
    return HospitalInfo(hospitalId=hid, name=hid, gps=GpsPoint(lat=lat, lng=126.9780),
                        availableBedCount=10, bedsByType={"ER_ADULT": 10}, nightDutyAvailable=True,
                        specialties=[Specialty(department="응급의학과", doctorCount=em)],
                        emergencyLevel=level, equipmentOperating={"ANGIO": angio, "CT": ct}, updatedAt="2026-11-01T05:00:00Z")


class KtasDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("hub_engine.SpecialtyMatcher", return_value=Matcher()):
            import app
        cls.app = app

    def setUp(self):
        self.engine = HubEngine(specialty_matcher=Matcher())
        self.app.engine = self.engine
        self.app.sim = None
        self.app._dashboard_sockets.clear()
        self.app._socket_identity.clear()
        self.app._case_audience.clear()
        self.app._case_reach.clear()
        self.app._zone_timer.clear()
        self.engine.register_case("case", "A")

    def connect(self, role, hid):
        sock = Socket()
        self.app._dashboard_sockets.add(sock)
        self.app._socket_identity[sock] = (role, hid)
        return sock

    def result(self, k=2, text="복통"):
        return self.engine.process_voice_summary(_voice("case", k, text), SCENE)

    def test_monitor_overview_exposes_rule_ktas(self):
        h = hospital("MAP", "지역응급의료센터")
        self.engine.update_hospital_info(h)
        payload = self.app._build_map_overview()
        row = next(r for r in payload["hospitals"] if r["hospitalId"] == "MAP")
        suitability = spider_rule.ktas_suitability(3, "general", h, 14)
        self.assertEqual(row["supportedKtas"], suitability["supportedKtas"])
        self.assertEqual(row["ktasSource"], "rule")
        self.assertFalse(row["ktasClinicallyValidated"])
        self.assertFalse(row["bedCountUnknown"])
        self.assertEqual(row["mapCapacity"], spider_rule.hospital_z(h, 14)[1])
        self.assertEqual(row["mapKtasLevel"], suitability["hospitalKtas"])

    def test_higher_capacity_hospital_still_receives(self):
        # 보고서 기준: 필요 역량 이상이면 받는다 — 대표 KTAS(hospitalKtas)가 달라도 거르지 않는다(2026-11-04)
        self.engine.update_hospital_info(hospital("K1", "권역응급의료센터"))
        self.engine.update_hospital_info(hospital("K2", "지역응급의료센터"))
        rows = dashboard_payload(self.result(2).model_dump())["hospitals"]
        self.assertEqual({h["hospitalId"] for h in rows}, {"K1", "K2"})
        self.assertEqual(next(h for h in rows if h["hospitalId"] == "K1")["ktasSuitability"]["hospitalKtas"], 1)

    def test_all_ktas_reuse_spider_rule(self):
        for level in spider_rule.LEVEL_G:
            for em in (0, 2, 5, 8):
                for hour in (2, 14, 23):
                    for cond in ("general", "stemi", "stroke", "trauma"):
                        h = hospital("H", level, em=em)
                        for k in range(1, 6):
                            suitability = spider_rule.ktas_suitability(k, cond, h, hour)
                            expected = spider_rule.line(k, cond, h, 10, 0, 0, hour)["blocked"] is None
                            self.assertEqual(suitability["eligible"], expected)
                            self.assertEqual(k in suitability["supportedKtas"], expected)
                            self.assertFalse(suitability["clinicallyValidated"])

    # 보고서 기준(2026-11-04): 확인된 사실로 처치할 수 없는 병원(confirmedBlock — 여기선 심근경색 환자 + 혈관조영 미운영 신고)만
    # 전달하지 않는다. 줄이 없어도 정보가 없거나 역량이 추정상 모자란 병원은 전달하고 맨 뒤에 둔다.
    def blocked_pair(self, r_level="권역응급의료센터", **r):
        self.engine.update_hospital_info(hospital("L", "지역응급의료센터", angio="N"))
        self.engine.update_hospital_info(hospital("R", r_level, **r))

    def test_confirmed_block_is_omitted_keeps_internal_audit(self):
        self.blocked_pair()
        result = self.result(text=STEMI)
        wire = dashboard_payload(result.model_dump())
        self.assertEqual({h.hospitalId for h in result.hospitals}, {"L", "R"})
        self.assertEqual([h["hospitalId"] for h in wire["hospitals"]], ["R"])
        self.assertEqual(wire["dispatchPolicy"]["targetCount"], 1)
        self.assertEqual(wire["dispatchPolicy"]["omitted"], [{"hospitalId": "L", "reason": "혈관조영 미운영"}])
        self.assertEqual(wire, dashboard_payload(wire))
        self.assertEqual(wire["hospitals"][0]["ktasSuitability"]["patientKtas"], 2)

    def test_estimated_shortfall_is_sent_last(self):
        # 지역기관(전문의 5명)은 KTAS 2 환자에게 줄이 없지만(추정 역량 모자람) 확인된 사실은 아니다 — 보내고 맨 뒤
        self.engine.update_hospital_info(hospital("L"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터"))
        result = self.result()
        local = next(h for h in result.hospitals if h.hospitalId == "L")
        self.assertIsNotNone(local.spiderBlocked)
        self.assertIsNone(local.ktasSuitability["confirmedBlock"])
        self.assertEqual([h["hospitalId"] for h in dashboard_payload(result.model_dump())["hospitals"]], ["R", "L"])

    def test_unknown_equipment_is_sent_last_not_omitted(self):
        # 혈관조영 운영 정보가 아예 없으면 미상 — 빼지 않는다
        self.engine.update_hospital_info(hospital("U", "권역응급의료센터").model_copy(update={"equipmentOperating": {}}))
        self.engine.update_hospital_info(hospital("YES", "권역응급의료센터", lat=37.5690))
        wire = dashboard_payload(self.result(text=STEMI).model_dump())
        self.assertEqual([h["hospitalId"] for h in wire["hospitals"]], ["YES", "U"])

    def test_condition_wall_blocks_equipment_missing(self):
        self.engine.update_hospital_info(hospital("NO", "권역응급의료센터", angio="N"))
        self.engine.update_hospital_info(hospital("YES", "권역응급의료센터"))
        wire = dashboard_payload(self.result(text="심근경색").model_dump())
        self.assertEqual([h["hospitalId"] for h in wire["hospitals"]], ["YES"])

    def test_no_target_expands_to_compatible_zone(self):
        # 존 확장은 줄이 걸리는 병원을 찾아 넓힌다 — 가까운 병원이 추정상 모자라도 그 병원만으로 존 1에 머물지 않는다
        self.engine.update_hospital_info(hospital("L"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터", lat=37.63))
        result = self.result()
        self.assertEqual(max(result.zoneActive), 2)
        self.assertEqual([h["hospitalId"] for h in dashboard_payload(result.model_dump())["hospitals"]], ["R", "L"])

    def test_no_fit_target_still_sends_estimated_short_hospital(self):
        # 50km까지 맞는 병원이 없어도 추정상 모자란 병원은 마지막 수단으로 받는다(제외하지 않음)
        self.engine.update_hospital_info(hospital("L"))
        result = self.result()
        self.assertEqual(max(result.zoneActive), 10)
        self.assertEqual([h["hospitalId"] for h in dashboard_payload(result.model_dump())["hospitals"]], ["L"])

    def test_timer_skips_incompatible_outer_zone(self):
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터"))
        self.engine.update_hospital_info(hospital("L2", lat=37.63))
        self.engine.update_hospital_info(hospital("R3", "권역응급의료센터", lat=37.68))
        self.result()
        self.assertEqual(self.engine.next_zone_with_new(SCENE, 1, case_id="case"), 3)

    def test_broadcast_phone_pad_hospital_and_monitor_agree(self):
        self.blocked_pair()
        phone, pad = self.connect("ambulance", "A"), self.connect("ambulance", "A")
        local, regional = self.connect("hospital", "L"), self.connect("hospital", "R")
        monitor = self.connect("monitor", "map")
        self.app._send_to_dashboard(self.result(text=STEMI).model_dump())
        for sock in (phone, pad, regional):
            self.assertEqual([h["hospitalId"] for h in sock.sent[-1]["hospitals"]], ["R"])
        self.assertEqual(local.sent, [])
        overview = next(m for m in reversed(monitor.sent) if m.get("type") == "case_overview")
        self.assertEqual([h["hospitalId"] for h in overview["hospitals"]], ["R"])
        self.assertEqual(self.app._case_reach["case"], {"R"})

    def test_late_hospital_and_ambulance_catchup_are_filtered(self):
        self.blocked_pair()
        self.result(text=STEMI)
        local, phone, regional = Socket(), Socket(), Socket()
        self.assertEqual(self.app._send_catchup(local, DashboardIdentify(role="hospital", id="L")), [])
        self.assertEqual(local.sent, [])
        self.app._send_catchup(phone, DashboardIdentify(role="ambulance", id="A"))
        self.app._send_catchup(regional, DashboardIdentify(role="hospital", id="R"))
        for sock in (phone, regional):
            self.assertEqual([h["hospitalId"] for h in sock.sent[-1]["hospitals"]], ["R"])

    def test_condition_change_withdraws_request_without_new_profile(self):
        self.blocked_pair()
        local = self.connect("hospital", "L")
        self.app._send_to_dashboard(self.result(2).model_dump())  # 복통 — 혈관조영과 무관해 L도 받는다
        self.assertEqual(local.sent[-1]["type"], "match_result")
        self.app._send_to_dashboard(self.result(2, STEMI).model_dump())
        self.assertEqual(local.sent[-1], {"type": "case_closed", "caseId": "case", "reason": "ktas_dispatch_changed"})
        self.assertNotIn("patientInfo", local.sent[-1])
        count = len(local.sent)
        self.app._send_to_dashboard(self.result(2, STEMI).model_dump())
        self.assertEqual(len(local.sent), count)

    def test_omitted_hospital_cannot_submit_stale_approval(self):
        self.engine.update_hospital_info(hospital("L", "지역응급의료센터", angio="N"))
        self.result(text=STEMI)
        action = ApprovalAction(caseId="case", hospital_id="L", action="hospital_approve", actor="hospital", timestamp="2026-11-01T05:00:00Z")
        self.assertFalse(self.engine.apply_approval_action(action))

    def test_explicit_approval_survives_ktas_override(self):
        self.engine.update_hospital_info(hospital("L"))
        self.result(3)
        action = ApprovalAction(caseId="case", hospital_id="L", action="hospital_approve", actor="hospital", timestamp="2026-11-01T05:00:00Z")
        self.assertTrue(self.engine.apply_approval_action(action))
        updated = self.engine.apply_patient_override(PatientOverride(caseId="case", ktasLevel=2), SCENE)
        result = self.engine.get_case_result("case")
        self.assertTrue(can_receive(result.hospitals[0]))
        self.assertEqual(dashboard_payload(result.model_dump())["hospitals"][0]["status"], "approved")

    def test_record_sync_uses_filtered_candidates(self):
        from record_archive import RecordArchive
        self.blocked_pair()
        archive = RecordArchive(Path(_TMP.name) / "record-filter-test.sqlite3")
        with patch.object(self.app, "record_archive", archive):
            self.app._send_to_dashboard(self.result(text=STEMI).model_dump())
            token = archive.grant("A")
            response = archive.handle(("ambulance", "A"), {"type": "record_sync", "token": token, "requestId": "r", "cursor": 0})
            self.assertEqual([h["hospitalId"] for h in response["records"][0]["hospitals"]], ["R"])

    def test_raw_voice_v2_ktas_is_the_dispatch_input(self):
        self.blocked_pair()
        voice = VoiceCallSummaryMessage.model_validate({"caseId": "case", "source": "ai",
            "transcript": {"raw_text": "통화", "filtered_text": "통화"},
            "summary": {"ktas_level": 2, "chief_complaint": {"major": "I 심혈관계", "minor": "흉통(심장성)"}}})
        wire = dashboard_payload(self.engine.process_voice_summary(voice, SCENE).model_dump())
        self.assertEqual(wire["dispatchPolicy"]["ktasLevel"], 2)
        self.assertEqual([h["hospitalId"] for h in wire["hospitals"]], ["R"])

    def test_night_refresh_expands_when_local_capacity_changes(self):
        self.engine.update_hospital_info(hospital("L", em=2))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터", lat=37.63))
        day = self.result(3)
        self.assertEqual([h["hospitalId"] for h in dashboard_payload(day.model_dump())["hospitals"]], ["L"])
        with patch.dict(os.environ, {"HUB_SPIDER_HOUR": "2"}):
            night = self.engine.refresh_case("case", SCENE)
        self.assertIsNotNone(night)
        self.assertEqual(max(night.zoneActive), 2)
        # 밤엔 L이 추정상 모자라 줄이 없다 — 존을 넓혀 R을 찾고, L은 빼지 않고 맨 뒤로
        self.assertEqual([h["hospitalId"] for h in dashboard_payload(night.model_dump())["hospitals"]], ["R", "L"])

    def test_recent_block_held_from_first_dispatch_until_zone_expands(self):
        # 사건 질환군(대동맥응급) 차단 공지를 1시간 전에 건 병원 — 첫 동시 전송에선 보류, 존을 넓히면 포함(2026-11-04)
        from datetime import datetime, timedelta, timezone
        start = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        block = AcceptanceMessage(kind="severe", message="의료진 부족", department="흉부외과", diseaseGroup="대동맥응급", startAt=start)
        self.engine.update_hospital_info(hospital("B", "권역응급의료센터").model_copy(update={"acceptanceMessages": [block]}))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터", lat=37.5690))
        first = self.result(text="대동맥 박리 의심")
        held = next(h for h in first.hospitals if h.hospitalId == "B")
        self.assertEqual(held.dispatchHold, "recent_severe_block")
        self.assertEqual([h["hospitalId"] for h in dashboard_payload(first.model_dump())["hospitals"]], ["R"])
        wider = self.engine.force_expand_zone("case", SCENE, cause="test")
        self.assertIsNotNone(wider)
        self.assertIn("B", [h["hospitalId"] for h in dashboard_payload(wider.model_dump())["hospitals"]])

    def test_old_block_is_not_held(self):
        from datetime import datetime, timedelta, timezone
        start = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
        block = AcceptanceMessage(kind="severe", message="의료진 부족", department="흉부외과", diseaseGroup="대동맥응급", startAt=start)
        self.engine.update_hospital_info(hospital("B", "권역응급의료센터").model_copy(update={"acceptanceMessages": [block]}))
        first = self.result(text="대동맥 박리 의심")
        self.assertIsNone(first.hospitals[0].dispatchHold, "6시간 넘은 공지는 보류하지 않는다(순서만 내림 — 기존 규칙)")

    def test_reject_ratio_counts_only_dispatchable_hospitals(self):
        for i in range(4):
            self.engine.update_hospital_info(hospital(f"L{i}"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터"))
        self.result(2)
        self.assertTrue(self.engine.apply_approval_action(ApprovalAction(caseId="case", hospital_id="R",
            action="hospital_reject", actor="hospital", timestamp="2026-11-01T05:00:00Z")))
        self.assertEqual(self.engine.reject_ratio("case", SCENE, 1), 1)

    def test_state_reload_does_not_restore_omitted_hospital_access(self):
        self.blocked_pair()
        self.result(2, STEMI)
        restored = HubEngine(specialty_matcher=Matcher())
        restored.import_state(self.engine.export_state())
        self.assertEqual(restored.get_cases_for_hospital("L"), [])
        self.assertEqual(len(restored.get_cases_for_hospital("R")), 1)

if __name__ == "__main__":
    unittest.main()
