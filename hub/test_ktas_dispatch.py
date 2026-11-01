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
from schema import ApprovalAction, DashboardIdentify, GpsPoint, HospitalInfo, PatientOverride, Specialty, VoiceCallSummaryMessage
from test_spider_rule import _voice

SCENE = GpsPoint(lat=37.5665, lng=126.9780)


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

    def test_k2_filters_local_keeps_internal_audit(self):
        self.engine.update_hospital_info(hospital("L"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터"))
        result = self.result()
        wire = dashboard_payload(result.model_dump())
        self.assertEqual({h.hospitalId for h in result.hospitals}, {"L", "R"})
        self.assertEqual([h["hospitalId"] for h in wire["hospitals"]], ["R"])
        self.assertEqual(wire["dispatchPolicy"]["targetCount"], 1)
        self.assertEqual(wire["dispatchPolicy"]["omitted"][0]["hospitalId"], "L")
        self.assertEqual(wire, dashboard_payload(wire))
        self.assertEqual(wire["hospitals"][0]["ktasSuitability"]["patientKtas"], 2)

    def test_condition_wall_blocks_equipment_missing(self):
        self.engine.update_hospital_info(hospital("NO", "권역응급의료센터", angio="N"))
        self.engine.update_hospital_info(hospital("YES", "권역응급의료센터"))
        wire = dashboard_payload(self.result(text="심근경색").model_dump())
        self.assertEqual([h["hospitalId"] for h in wire["hospitals"]], ["YES"])

    def test_no_target_expands_to_compatible_zone(self):
        self.engine.update_hospital_info(hospital("L"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터", lat=37.63))
        result = self.result()
        self.assertEqual(max(result.zoneActive), 2)
        self.assertEqual([h["hospitalId"] for h in dashboard_payload(result.model_dump())["hospitals"]], ["R"])

    def test_no_compatible_target_has_no_fallback(self):
        self.engine.update_hospital_info(hospital("L"))
        result = self.result()
        self.assertEqual(max(result.zoneActive), 10)
        self.assertEqual(dashboard_payload(result.model_dump())["hospitals"], [])

    def test_timer_skips_incompatible_outer_zone(self):
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터"))
        self.engine.update_hospital_info(hospital("L2", lat=37.63))
        self.engine.update_hospital_info(hospital("R3", "권역응급의료센터", lat=37.68))
        self.result()
        self.assertEqual(self.engine.next_zone_with_new(SCENE, 1, case_id="case"), 3)

    def test_broadcast_phone_pad_hospital_and_monitor_agree(self):
        self.engine.update_hospital_info(hospital("L"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터"))
        phone, pad = self.connect("ambulance", "A"), self.connect("ambulance", "A")
        local, regional = self.connect("hospital", "L"), self.connect("hospital", "R")
        monitor = self.connect("monitor", "map")
        self.app._send_to_dashboard(self.result().model_dump())
        for sock in (phone, pad, regional):
            self.assertEqual([h["hospitalId"] for h in sock.sent[-1]["hospitals"]], ["R"])
        self.assertEqual(local.sent, [])
        self.assertEqual([h["hospitalId"] for h in monitor.sent[-1]["hospitals"]], ["R"])
        self.assertEqual(self.app._case_reach["case"], {"R"})

    def test_late_hospital_and_ambulance_catchup_are_filtered(self):
        self.engine.update_hospital_info(hospital("L"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터"))
        self.result()
        local, phone, regional = Socket(), Socket(), Socket()
        self.assertEqual(self.app._send_catchup(local, DashboardIdentify(role="hospital", id="L")), [])
        self.assertEqual(local.sent, [])
        self.app._send_catchup(phone, DashboardIdentify(role="ambulance", id="A"))
        self.app._send_catchup(regional, DashboardIdentify(role="hospital", id="R"))
        for sock in (phone, regional):
            self.assertEqual([h["hospitalId"] for h in sock.sent[-1]["hospitals"]], ["R"])

    def test_ktas_change_withdraws_request_without_new_profile(self):
        self.engine.update_hospital_info(hospital("L"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터"))
        local = self.connect("hospital", "L")
        self.app._send_to_dashboard(self.result(3).model_dump())
        self.assertEqual(local.sent[-1]["type"], "match_result")
        self.app._send_to_dashboard(self.result(2).model_dump())
        self.assertEqual(local.sent[-1], {"type": "case_closed", "caseId": "case", "reason": "ktas_dispatch_changed"})
        self.assertNotIn("patientInfo", local.sent[-1])
        count = len(local.sent)
        self.app._send_to_dashboard(self.result(2).model_dump())
        self.assertEqual(len(local.sent), count)

    def test_omitted_hospital_cannot_submit_stale_approval(self):
        self.engine.update_hospital_info(hospital("L"))
        self.result()
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
        self.engine.update_hospital_info(hospital("L"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터"))
        archive = RecordArchive(Path(_TMP.name) / "record-filter-test.sqlite3")
        with patch.object(self.app, "record_archive", archive):
            self.app._send_to_dashboard(self.result().model_dump())
            token = archive.grant("A")
            response = archive.handle(("ambulance", "A"), {"type": "record_sync", "token": token, "requestId": "r", "cursor": 0})
            self.assertEqual([h["hospitalId"] for h in response["records"][0]["hospitals"]], ["R"])

    def test_raw_voice_v2_ktas_is_the_dispatch_input(self):
        self.engine.update_hospital_info(hospital("L"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터"))
        voice = VoiceCallSummaryMessage.model_validate({"caseId": "case", "source": "ai",
            "transcript": {"raw_text": "통화", "filtered_text": "통화"},
            "summary": {"ktas_level": 2, "chief_complaint": {"major": "복통", "minor": "복통"}}})
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
        self.assertEqual([h["hospitalId"] for h in dashboard_payload(night.model_dump())["hospitals"]], ["R"])

    def test_reject_ratio_counts_only_dispatchable_hospitals(self):
        for i in range(4):
            self.engine.update_hospital_info(hospital(f"L{i}"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터"))
        self.result(2)
        self.assertTrue(self.engine.apply_approval_action(ApprovalAction(caseId="case", hospital_id="R",
            action="hospital_reject", actor="hospital", timestamp="2026-11-01T05:00:00Z")))
        self.assertEqual(self.engine.reject_ratio("case", SCENE, 1), 1)

    def test_state_reload_does_not_restore_omitted_hospital_access(self):
        self.engine.update_hospital_info(hospital("L"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터"))
        self.result(2)
        restored = HubEngine(specialty_matcher=Matcher())
        restored.import_state(self.engine.export_state())
        self.assertEqual(restored.get_cases_for_hospital("L"), [])
        self.assertEqual(len(restored.get_cases_for_hospital("R")), 1)


if __name__ == "__main__":
    unittest.main()
