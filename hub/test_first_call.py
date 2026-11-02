import unittest
from first_call import rank
from test_ktas_dispatch import KtasDispatchTests, Socket, hospital

class FirstCallTests(KtasDispatchTests):
    def test_request_no_answer_and_ownership(self):
        self.engine.update_hospital_info(hospital("L"))
        self.engine.update_hospital_info(hospital("R", "권역응급의료센터", lat=37.57, em=10))
        self.app._case_scene.clear()
        ws = Socket()
        self.app._socket_identity[ws] = ("ambulance", "A")
        self.app._handle_first_call(ws, {"caseId":"case", "ktas":4})
        scene = self.app._case_scene["case"]
        first = next(h for h in scene["hospitals"] if h["firstCallRecommended"])
        self.app._handle_first_call(ws, {"caseId":"case", "ktas":4, "noAnswerHospitalId":first["hospitalId"]})
        scene = self.app._case_scene["case"]
        self.assertIn(first["hospitalId"], scene["callAttempts"])
        self.assertFalse(next(h for h in scene["hospitals"] if h["hospitalId"] == first["hospitalId"])["firstCallRecommended"])
        self.assertNotEqual(self.engine.get_case_status("case", first["hospitalId"]), "rejected")
        self.app._handle_first_call(ws, {"caseId":"case", "ktas":2})
        self.assertIn(first["hospitalId"], self.app._case_scene["case"]["callAttempts"])
        self.app._socket_identity[ws] = ("ambulance", "other")
        self.app._handle_first_call(ws, {"caseId":"case", "ktas":5})
        self.assertEqual(ws.sent[-1]["type"], "first_call_error")

    def test_clear_selection_syncs_both_devices_and_preserves_attempts(self):
        self.engine.update_hospital_info(hospital("L"))
        self.app._case_scene.clear()
        phone = self.connect("ambulance", "A")
        tablet = self.connect("ambulance", "A")
        self.app._handle_first_call(phone, {"caseId": "case", "ktas": 4})
        self.app._case_scene["case"]["callAttempts"] = ["L"]
        self.app._handle_first_call(phone, {"caseId": "case", "ktas": None})
        for device in (phone, tablet):
            scene = device.sent[-1]
            self.assertEqual(scene["type"], "scene_candidates")
            self.assertIsNone(scene["preKtas"])
            self.assertTrue(scene["preKtasCleared"])
            self.assertEqual(scene["callAttempts"], ["L"])
            self.assertFalse(any(h.get("firstCallRecommended") for h in scene["hospitals"]))
        self.assertNotIn("case", self.app._case_recommended)
        self.app._handle_first_call(tablet, {"caseId": "case", "ktas": 3})
        self.assertEqual(phone.sent[-1]["preKtas"], 3)
        self.assertFalse(phone.sent[-1]["preKtasCleared"])

    def test_missing_ktas_does_not_clear_selection(self):
        self.app._case_scene.clear()
        phone = self.connect("ambulance", "A")
        self.app._handle_first_call(phone, {"caseId": "case", "ktas": 4})
        self.app._handle_first_call(phone, {"caseId": "case"})
        self.assertEqual(self.app._case_scene["case"]["preKtas"], 4)

    def test_expands_for_ktas_and_exhausted_candidates(self):
        self.engine.update_hospital_info(hospital("near", em=5))
        self.engine.update_hospital_info(hospital("far", "권역응급의료센터", lat=37.66, em=10))
        self.app._case_scene["case"] = {"ambulanceGps": {"lat":37.5665,"lng":126.978}}
        ws = Socket()
        self.app._socket_identity[ws] = ("ambulance", "A")
        self.app._handle_first_call(ws, {"caseId":"case", "ktas":1})
        scene = self.app._case_scene["case"]
        self.assertGreater(max(scene["zoneActive"]), 1)
        self.assertEqual(next(h for h in scene["hospitals"] if h["firstCallRecommended"])["hospitalId"], "far")
        self.app._handle_first_call(ws, {"caseId":"case", "ktas":1, "noAnswerHospitalId":"far"})
        self.assertTrue(self.app._case_scene["case"]["firstCallExhausted"])

    def test_two_ambulances_share_hub_recommendations(self):
        self.app._case_scene.clear()
        self.app._case_call.clear()
        self.app._first_call_coordinator.leases.clear()
        self.engine.update_hospital_info(hospital("L", lat=37.567))
        self.engine.update_hospital_info(hospital("R", lat=37.568))
        self.engine.register_case("case2", "B")
        gps = {"lat":37.5665,"lng":126.978}
        picks=[]
        for cid, apid in [("case","A"),("case2","B")]:
            ws=Socket(); self.app._socket_identity[ws]=("ambulance",apid)
            self.app._case_scene[cid]={"ambulanceGps":gps}
            self.app._handle_first_call(ws,{"caseId":cid,"ktas":4})
            picks.append(next(h["hospitalId"] for h in self.app._case_scene[cid]["hospitals"] if h["firstCallRecommended"]))
        self.assertEqual(picks,["L","R"])

    def test_rank_capacity_distance_pressure_and_exhaustion(self):
        rows = [dict(hospitalId="center", emergencyLevel="권역응급의료센터", supportedKtas=[1,2,3,4,5], travelMin=4, distanceKm=1),
                dict(hospitalId="local", emergencyLevel="지역응급의료기관", supportedKtas=[3,4,5], travelMin=6, distanceKm=2)]
        self.assertEqual(rank(rows,4,[],{})[0][0]["hospitalId"], "local")
        self.assertEqual(rank(rows,1,[],{})[0][0]["hospitalId"], "center")
        self.assertEqual(rank(rows,4,[],{"local":3})[0][0]["hospitalId"], "center")
        self.assertEqual(rank(rows,4,["center","local"],{})[0], [])

if __name__ == "__main__": unittest.main()
