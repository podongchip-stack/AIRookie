import unittest
from unittest.mock import patch
from test_ktas_dispatch import KtasDispatchTests, Socket, hospital

class CallConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        KtasDispatchTests.setUpClass()
        cls.app = KtasDispatchTests.app
    def setUp(self):
        KtasDispatchTests.setUp(self)
        self.engine.update_hospital_info(hospital("H"))
        self.app._case_call.clear()
        self.app._case_scene.clear()
        self.phone = Socket(); self.monitor = Socket()
        self.app._socket_identity[self.phone] = ("ambulance", "A")
        self.app._socket_identity[self.monitor] = ("monitor", "control")
        self.msg = dict(caseId="case",hospitalId="H",requestId="r1",timestamp="2026-11-01T00:00:00Z")

    def op(self, op, ws=None, **changes):
        self.app._handle_call_connection(ws or self.phone, dict(self.msg, operation=op, **changes))

    def test_ringing_no_answer_and_late_answer(self):
        with patch.object(self.app, "_relay_call_signal") as relay:
            self.op("request")
            self.assertEqual(self.app._case_call["case"]["state"], "ringing")
            relay.assert_not_called()
            self.op("no_answer", self.monitor)
            self.assertEqual(self.app._case_call["case"]["state"], "no_answer")
            self.assertEqual(self.app._case_scene["case"]["callAttempts"], ["H"])
            self.assertNotEqual(self.engine.get_case_status("case","H"), "rejected")
            self.op("answer", self.monitor)
            relay.assert_not_called()

    def test_answer_uses_phone_audio_socket_once(self):
        def connected(signal, ws):
            self.assertIs(ws, self.phone)
            self.app._send_call_status({**self.app._case_call["case"],"state":"calling"})
        with patch.object(self.app, "_relay_call_signal", side_effect=connected) as relay:
            self.op("request")
            self.op("answer") # ambulance cannot simulate hospital response
            relay.assert_not_called()
            self.op("answer", self.monitor)
            self.op("answer", self.monitor)
            self.assertEqual(relay.call_count,1)

    def test_cancel_then_new_attempt_rejects_old_response(self):
        self.op("request"); self.op("cancel")
        self.op("request", requestId="r2")
        with patch.object(self.app,"_relay_call_signal") as relay:
            self.op("answer",self.monitor)
            relay.assert_not_called()
        self.assertEqual(self.app._case_call["case"]["requestId"],"r2")

if __name__ == "__main__": unittest.main()
