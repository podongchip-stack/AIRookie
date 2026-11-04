import base64
import hashlib
import hmac
from pathlib import Path
import sys
import tempfile
import unittest

from configure import configuration

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hub"))
from call_sessions import ice_servers_for


class TurnConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.env = {"TURN_HOST": "turn.goldenlink.test", "TURN_EXTERNAL_IP": "8.8.8.8/192.168.1.5",
                    "HUB_TURN_SECRET": "a" * 64}

    def test_coturn_and_hub_share_authentication(self):
        config, urls = configuration(self.env)
        self.assertIn("use-auth-secret\n", config)
        self.assertIn("static-auth-secret=" + self.env["HUB_TURN_SECRET"], config)
        servers = ice_servers_for("call-123", now=100, env={**self.env, "HUB_TURN_URLS": urls})
        turn = servers[-1]
        self.assertEqual(turn["urls"], ["turn:turn.goldenlink.test:3478?transport=udp",
                                        "turn:turn.goldenlink.test:3478?transport=tcp"])
        self.assertEqual(turn["username"], "3700:call-123")
        expected = base64.b64encode(hmac.new(self.env["HUB_TURN_SECRET"].encode(),
                                            turn["username"].encode(), hashlib.sha1).digest()).decode()
        self.assertEqual(turn["credential"], expected)
        self.assertNotIn(self.env["HUB_TURN_SECRET"], str(servers))
        self.assertIn("no-tls\n", config)

    def test_rejects_incomplete_and_injected_settings(self):
        for changes in ({"HUB_TURN_SECRET": ""}, {"TURN_HOST": "turn.example.com"},
                        {"TURN_EXTERNAL_IP": "not-an-ip"}, {"TURN_PORT": "80"},
                        {"TURN_MIN_PORT": "50000", "TURN_MAX_PORT": "49000"},
                        {"TURN_HOST": "real.test\nno-auth"}, {"TURN_CERT": "/missing"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                configuration({**self.env, **changes})

    def test_tls_urls_require_both_files(self):
        with tempfile.TemporaryDirectory() as folder:
            cert = Path(folder) / "cert.pem"
            key = Path(folder) / "key.pem"
            cert.touch()
            key.touch()
            config, urls = configuration({**self.env, "TURN_CERT": str(cert), "TURN_PKEY": str(key)})
            self.assertIn("turns:turn.goldenlink.test:5349?transport=tcp", urls)
            self.assertIn("tls-listening-port=5349", config)
            self.assertNotIn("no-tls\n", config)


if __name__ == "__main__":
    unittest.main()
