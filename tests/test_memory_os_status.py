import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web_panel"))

import memory_os_status  # noqa: E402


class MemoryOsStatusTest(unittest.TestCase):
    def test_missing_runtime_markers_is_unknown_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            templates = root / "state_templates"
            templates.mkdir()
            (templates / "module_settings.json").write_text(
                json.dumps({"memory_os": {"enabled": True}}),
                encoding="utf-8",
            )

            payload = memory_os_status.build_memory_os_status(root)

        self.assertEqual(payload["status"], "UNKNOWN")
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["production_deploy_allowed"])
        self.assertFalse(payload["mutating_actions_allowed"])
        self.assertFalse(payload["raw_context_included"])
        self.assertFalse(payload["secret_values_included"])

    def test_status_exposes_only_safe_last_context_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            state.mkdir()
            templates = root / "state_templates"
            templates.mkdir()
            (templates / "module_settings.json").write_text(
                json.dumps({"memory_os": {"enabled": True}}),
                encoding="utf-8",
            )
            (state / "memory_os_status.json").write_text(
                json.dumps({"status": "PASS", "updated_at": "2026-06-05T00:00:00+00:00"}),
                encoding="utf-8",
            )
            (state / "memory_os_last_context.json").write_text(
                json.dumps(
                    {
                        "context_id": "CTX-1",
                        "title": "Memory OS runtime handoff",
                        "summary": "Safe summary",
                        "intent_domain": "memory_os",
                        "raw_payload": "token=secret-value",
                    }
                ),
                encoding="utf-8",
            )

            payload = memory_os_status.build_memory_os_status(root)

        self.assertEqual(payload["status"], "HEALTHY")
        self.assertEqual(payload["last_context"]["context_id"], "CTX-1")
        self.assertEqual(payload["last_context"]["summary"], "Safe summary")
        self.assertNotIn("raw_payload", payload["last_context"])
        self.assertIn("unsafe_fields_ignored", payload["last_context"]["reason_codes"])


if __name__ == "__main__":
    unittest.main()
