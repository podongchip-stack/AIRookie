"""실통화→첫 요약 판단 게이트/추가 통화/중앙 voice 단일 소유권 회귀 검사."""
import unittest
from unittest.mock import patch, Mock

# 기존 검사와 같은 임시 상태·로그 격리(실제 서버에 접속하지 않는다).
from test_call_sessions import _Clock
from call_sessions import CallSessionManager
import app


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.manager = CallSessionManager(clock=self.clock)
        self.engine = Mock()
        self.engine.get_case_result.return_value = None
        self.patches = [patch.object(app, "engine", self.engine),
            patch.object(app, "_central_voice_url", return_value="http://central.test"),
            patch.object(app, "_relay_to_central_voice"), patch.object(app, "_start_call_hold"),
            patch.object(app, "_release_call_hold"), patch.object(app.decision_log, "log_decision"),
            patch.object(app.case_tracker, "event"), patch.dict(app._first_call_wait, clear=True),
            patch.object(app, "_call_manager", self.manager)]
        self.started = [p.start() for p in self.patches]
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        self.relay = self.started[2]

    def active(self, mode="on_device"):
        m = self.manager
        m.invite(call_id="call1", case_id="case1", apid="A1", hospital_id="H1", caller_ws="caller",
                 hospital_online=True, pipeline=mode)
        m.accept("call1", "hospital", "H1", "callee")
        m.offer("call1", "ambulance", "A1", "caller", "offer", 1)
        m.answer("call1", "hospital", "H1", "callee", "answer", 1)
        m.media_ready("call1", "ambulance", "A1", "caller")
        m.media_ready("call1", "hospital", "H1", "callee")
        return m.get("call1")

    def test_on_device_registers_once_and_holds_first_summary_before_end_delivery(self):
        session = self.active()
        app._advance_call_pipeline(session)
        app._advance_call_pipeline(session)
        self.engine.register_case.assert_called_once_with("case1", "A1")
        outcome = self.manager.hangup("call1", "hospital", "H1", "callee")
        def delivered(*args):
            self.assertIn("case1", app._first_call_wait)
        with patch.object(app, "_call_targets", return_value=["caller"]), \
             patch.object(app, "_send_to_socket", side_effect=delivered), patch.object(app, "_after_call_change"):
            app._deliver_call(outcome)
        wait = app._first_call_wait["case1"]
        summary = Mock(caseId="case1")
        self.assertTrue(app._first_call_gate(summary))
        self.assertIs(wait["summary"], summary)
        app._advance_call_pipeline(session)
        self.assertIs(app._first_call_wait["case1"], wait)
        self.relay.assert_not_called()

    def test_followup_uses_existing_hold_without_first_call_gate(self):
        self.engine.get_case_result.return_value = object()
        session = self.active()
        app._advance_call_pipeline(session)
        self.started[3].assert_called_once_with("case1", "A1")
        self.manager.hangup("call1", "ambulance", "A1", "caller")
        app._advance_call_pipeline(session)
        self.assertNotIn("case1", app._first_call_wait)

    def test_central_waits_for_caller_last_pcm_and_finishes_once(self):
        session = self.active("central")
        app._advance_call_pipeline(session)
        self.assertEqual(self.relay.call_count, 1)
        self.manager.hangup("call1", "hospital", "H1", "callee")
        app._advance_call_pipeline(session)
        self.assertEqual(self.relay.call_count, 1)  # 마지막 PCM을 받을 때까지 중앙 인식기 종료를 미룸
        with patch.dict(app._socket_identity, {"caller": ("ambulance", "A1"), "other": ("ambulance", "A2")}):
            message = {"type": "call_pipeline_finish", "callId": "call1"}
            app._handle_call_session_message("other", message)
            self.assertFalse(session.pipeline_audio_closed)
            app._handle_call_session_message("caller", message)
            app._handle_call_session_message("caller", message)
        self.assertEqual(self.relay.call_count, 2)
        self.assertEqual(self.relay.call_args.args[0].signal, "call_ended")

    def test_case_closed_cancels_central_without_decision(self):
        session = self.active("central")
        app._advance_call_pipeline(session)
        self.manager.end_for_case("case1", "case_closed")
        app._advance_call_pipeline(session)
        self.assertTrue(self.relay.call_args.args[0].cancelled)
        self.assertNotIn("case1", app._first_call_wait)

    def test_fast_end_still_prepares_gate(self):
        session = self.active()
        self.manager.hangup("call1", "hospital", "H1", "callee")
        app._advance_call_pipeline(session)
        self.assertIn("case1", app._first_call_wait)
        self.assertTrue(session.pipeline_started and session.pipeline_finished)

    def test_legacy_calls_remain_call_only(self):
        session = self.active(None)
        app._advance_call_pipeline(session)
        self.manager.hangup("call1", "hospital", "H1", "callee")
        app._advance_call_pipeline(session)
        self.engine.register_case.assert_not_called()
        self.assertNotIn("case1", app._first_call_wait)

    def test_central_missing_final_ack_is_bounded(self):
        session = self.active("central")
        app._advance_call_pipeline(session)
        self.manager.hangup("call1", "hospital", "H1", "callee")
        app._advance_call_pipeline(session)
        self.assertEqual(self.manager.audio_finishes_due(), [])
        self.clock.t += 11
        self.assertEqual(self.manager.audio_finishes_due(), [session])
        app._finish_call_audio(session)
        self.assertEqual(self.manager.audio_finishes_due(), [])


if __name__ == "__main__":
    unittest.main()
