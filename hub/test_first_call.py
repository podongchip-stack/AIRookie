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
        self.app._handle_first_call(ws, {"caseId":"case"})
        scene = self.app._case_scene["case"]
        first = next(h for h in scene["hospitals"] if h["firstCallRecommended"])
        self.app._handle_first_call(ws, {"caseId":"case", "noAnswerHospitalId":first["hospitalId"]})
        scene = self.app._case_scene["case"]
        self.assertIn(first["hospitalId"], scene["callAttempts"])
        self.assertFalse(next(h for h in scene["hospitals"] if h["hospitalId"] == first["hospitalId"])["firstCallRecommended"])
        self.assertNotEqual(self.engine.get_case_status("case", first["hospitalId"]), "rejected")
        self.app._handle_first_call(ws, {"caseId":"case"})
        self.assertIn(first["hospitalId"], self.app._case_scene["case"]["callAttempts"])
        self.app._socket_identity[ws] = ("ambulance", "other")
        self.app._handle_first_call(ws, {"caseId":"case"})
        self.assertEqual(ws.sent[-1]["type"], "first_call_error")

    def test_expands_when_everything_nearby_has_no_answer_then_exhausted(self):
        self.engine.update_hospital_info(hospital("near", em=5))
        self.engine.update_hospital_info(hospital("far", "권역응급의료센터", lat=37.66, em=10))
        self.app._case_scene["case"] = {"ambulanceGps": {"lat":37.5665,"lng":126.978}}
        ws = Socket()
        self.app._socket_identity[ws] = ("ambulance", "A")
        self.app._handle_first_call(ws, {"caseId":"case"})
        first = next(h for h in self.app._case_scene["case"]["hospitals"] if h["firstCallRecommended"])["hospitalId"]
        self.assertEqual(first, "near")
        self.app._handle_first_call(ws, {"caseId":"case", "noAnswerHospitalId":"near"})
        scene = self.app._case_scene["case"]
        self.assertGreater(max(scene["zoneActive"]), 1)
        self.assertEqual(next(h for h in scene["hospitals"] if h["firstCallRecommended"])["hospitalId"], "far")
        self.app._handle_first_call(ws, {"caseId":"case", "noAnswerHospitalId":"far"})
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
            self.app._handle_first_call(ws,{"caseId":cid})
            picks.append(next(h["hospitalId"] for h in self.app._case_scene[cid]["hospitals"] if h["firstCallRecommended"]))
        self.assertEqual(picks,["L","R"])

    def test_recommendation_change_refreshes_the_other_ambulance_at_once(self):
        self.app._case_scene.clear(); self.app._case_call.clear(); self.app._case_recommended.clear()
        self.app._first_call_coordinator.leases.clear()
        self.engine.update_hospital_info(hospital("L", lat=37.567))
        self.engine.update_hospital_info(hospital("R", lat=37.568))
        self.engine.register_case("case2", "B")
        gps = {"lat":37.5665,"lng":126.978}
        sockets = {}
        for cid, apid in [("case","A"),("case2","B")]:
            ws=Socket(); sockets[cid]=ws; self.app._socket_identity[ws]=("ambulance",apid)
            self.app._case_scene[cid]={"ambulanceGps":gps}
            self.app._handle_first_call(ws,{"caseId":cid})
        pick = lambda cid: next(h["hospitalId"] for h in self.app._case_scene[cid]["hospitals"] if h["firstCallRecommended"])
        self.assertEqual((pick("case"), pick("case2")), ("L", "R"))
        sent_before = len(sockets["case2"].sent)
        # A가 L에 전화했는데 받지 않으면 A의 추천은 R로 옮겨 가고, B는 요청하지 않아도 L(이제 비어 있다)을 추천받는다
        self.app._handle_first_call(sockets["case"], {"caseId":"case", "noAnswerHospitalId":"L"})
        self.assertEqual(pick("case"), "R")
        self.assertEqual(pick("case2"), "L")
        self.assertGreater(len(sockets["case2"].sent), sent_before)
        self.assertEqual(sockets["case2"].sent[-1]["type"], "scene_candidates")

    def test_rank_distance_pressure_and_exhaustion(self):
        rows = [dict(hospitalId="center", emergencyLevel="권역응급의료센터", travelMin=4, distanceKm=1),
                dict(hospitalId="local", emergencyLevel="지역응급의료기관", travelMin=6, distanceKm=2)]
        self.assertEqual(rank(rows,[],{})[0][0]["hospitalId"], "center")          # 중증도를 모르니 이동시간 그대로
        self.assertEqual(rank(rows,[],{"center":3})[0][0]["hospitalId"], "local")  # 다른 구급차 점유(상한 5분)가 가까운 병원을 뒤로
        self.assertEqual(rank(rows,["center","local"],{})[0], [])

if __name__ == "__main__": unittest.main()
