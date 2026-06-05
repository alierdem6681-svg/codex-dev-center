import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web_panel"))

from supervisor import memory_os_readiness  # noqa: E402


def load_panel_module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


panel_server = load_panel_module("memory_os_panel_server_test_module", "web_panel/panel_server.py")
legacy_panel_server = load_panel_module("memory_os_legacy_panel_server_test_module", "web_panel/server.py")


class MemoryOsReadinessTest(unittest.TestCase):
    def write_contract_root(self, root: Path, memory_settings: dict | None = None, module_status: str = "planned") -> None:
        (root / "memory").mkdir(parents=True)
        (root / "memory" / "project_memory.md").write_text("# memory\n", encoding="utf-8")
        templates = root / "state_templates"
        templates.mkdir(parents=True)
        (templates / "module_registry.json").write_text(
            json.dumps(
                {
                    "modules": [
                        {
                            "id": "memory_os",
                            "status": module_status,
                            "settings_enabled": True,
                            "actions_enabled": True,
                            "dashboard_visible": True,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (templates / "action_catalog.json").write_text(
            json.dumps({"actions": [{"id": "check_memory_os_readiness", "module": "memory_os", "enabled": True}]}),
            encoding="utf-8",
        )
        default_settings = {
            "memory_os": {
                "enabled": False,
                "readiness_guard_enabled": True,
                "record_schema_defined": False,
                "index_cache_enabled": False,
                "health_state_enabled": False,
                "telegram_memory_commands_enabled": False,
                "dashboard_memory_center_enabled": False,
                "secret_redaction_tests_enabled": False,
                "capabilities": {
                    "project_memory_file": {
                        "implemented": True,
                        "evidence_files": ["memory/project_memory.md"],
                    }
                },
            }
        }
        if memory_settings:
            default_settings["memory_os"].update(memory_settings)
        (templates / "module_settings.json").write_text(json.dumps(default_settings), encoding="utf-8")

    def test_project_memory_file_alone_does_not_make_memory_os_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_contract_root(root)

            payload = memory_os_readiness.build_memory_os_readiness(root, checked_at="2026-06-05T00:00:00+00:00")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "not_ready")
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["blocking_reason"], "blocked_not_implemented")
        self.assertEqual(payload["module_status"], "planned")
        self.assertEqual(payload["missing_count"], 6)
        self.assertIn("project_memory_file", payload["implemented_capabilities"])
        self.assertEqual(
            {item["id"] for item in payload["missing_capabilities"]},
            {
                "record_schema",
                "index_cache",
                "health_state",
                "telegram_memory_commands",
                "dashboard_memory_center",
                "secret_redaction_tests",
            },
        )
        self.assertFalse(payload["production_deploy_allowed"])
        self.assertFalse(payload["production_deploy_performed"])

    def test_dashboard_summary_is_short_and_excludes_secret_like_source_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_contract_root(
                root,
                memory_settings={
                    "operator_note": "Authorization: Bearer fakebearervalue1234567890",
                    "debug_stdout": "stdout should not be returned",
                },
            )

            summary = memory_os_readiness.build_dashboard_memory_os_readiness(root)

        encoded = json.dumps(summary, sort_keys=True)
        self.assertEqual(summary["status"], "not_ready")
        self.assertTrue(summary["dashboard_safe"])
        self.assertFalse(summary["raw_logs_included"])
        self.assertFalse(summary["terminal_output_included"])
        self.assertFalse(summary["secret_values_included"])
        self.assertLessEqual(len(summary["missing_capabilities"]), 8)
        self.assertNotIn("fakebearervalue1234567890", encoded)
        self.assertNotIn("Authorization:", encoded)
        self.assertNotIn("stdout should not be returned", encoded)

    def test_status_payload_exposes_memory_os_readiness_for_all_panel_servers(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir(parents=True)
            originals = {
                panel_server: (panel_server.STATE, getattr(panel_server, "services", None)),
                legacy_panel_server: (legacy_panel_server.STATE, None),
            }
            try:
                panel_server.STATE = state
                panel_server.services = lambda: []
                legacy_panel_server.STATE = state
                for module in (panel_server, legacy_panel_server):
                    payload = module.status_payload()
                    view = payload["memory_os_readiness"]
                    self.assertEqual(view["contract_version"], 1)
                    self.assertEqual(view["status"], "not_ready")
                    self.assertFalse(view["ready"])
                    self.assertEqual(view["blocking_reason"], "blocked_not_implemented")
                    self.assertIn("record_schema", view["missing_capabilities"])
                    self.assertFalse(view["production_deploy_allowed"])
                    self.assertFalse(view["production_deploy_performed"])
            finally:
                panel_server.STATE, original_services = originals[panel_server]
                if original_services is not None:
                    panel_server.services = original_services
                legacy_panel_server.STATE = originals[legacy_panel_server][0]

    def test_repo_templates_register_memory_os_without_marking_it_active(self):
        registry = memory_os_readiness.read_repo_json(ROOT, "module_registry.json", {"modules": []})
        settings = memory_os_readiness.read_repo_json(ROOT, "module_settings.json", {})
        catalog = memory_os_readiness.read_repo_json(ROOT, "action_catalog.json", {"actions": []})

        module = memory_os_readiness.module_entry(registry)
        action = memory_os_readiness.action_entry(catalog)

        self.assertEqual(module["id"], "memory_os")
        self.assertNotEqual(module["status"], "active")
        self.assertIn(module["status"], {"planned", "contract_ready"})
        self.assertIn("memory_os", settings)
        self.assertFalse(settings["memory_os"]["enabled"])
        self.assertEqual(action["module"], "memory_os")
        self.assertTrue(action["non_mutating"])


if __name__ == "__main__":
    unittest.main()
