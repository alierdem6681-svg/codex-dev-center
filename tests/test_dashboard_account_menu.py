import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web_panel"))

import auth as panel_auth  # noqa: E402


class DashboardAccountPayloadTest(unittest.TestCase):
    def test_public_account_payload_excludes_auth_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_file = Path(tmp) / "state" / "panel_auth.json"
            auth_file.parent.mkdir(parents=True)
            auth_file.write_text(
                json.dumps(
                    {
                        "auth_mode": "username_password",
                        "username": "denizkan",
                        "password": {
                            "algorithm": "pbkdf2_sha256",
                            "salt": "abc123",
                            "hash": "secret-hash",
                        },
                    }
                ),
                encoding="utf-8",
            )

            original_auth_file = panel_auth.AUTH_FILE
            panel_auth.AUTH_FILE = auth_file
            try:
                payload = panel_auth.public_account_state(
                    session={"sub": "denizkan", "iat": 1000, "exp": 1600},
                    current_time=1200,
                )
            finally:
                panel_auth.AUTH_FILE = original_auth_file

        serialized = json.dumps(payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["account"]["username"], "denizkan")
        self.assertEqual(payload["account"]["role"], "operator")
        self.assertEqual(payload["account"]["session"]["seconds_remaining"], 400)
        self.assertNotIn('"password":', serialized)
        self.assertNotIn("salt", serialized)
        self.assertNotIn("secret-hash", serialized)
        self.assertNotIn(panel_auth.COOKIE_NAME, serialized)


if __name__ == "__main__":
    unittest.main()
