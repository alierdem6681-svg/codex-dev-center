import json
import os
import stat
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StagingReadinessWrapperTest(unittest.TestCase):
    def test_policy_defaults_use_staging_wrapper_commands(self):
        expected = {
            "CODEX_STAGING_HEALTH_CHECK_COMMAND": "scripts/staging_health_check.sh",
            "CODEX_STAGING_SMOKE_TEST_COMMAND": "scripts/staging_smoke_test.sh",
        }
        deploy_policy = json.loads((ROOT / "state_templates/deploy_policy.json").read_text(encoding="utf-8"))
        module_settings = json.loads((ROOT / "state_templates/module_settings.json").read_text(encoding="utf-8"))
        action_catalog = json.loads((ROOT / "state_templates/action_catalog.json").read_text(encoding="utf-8"))
        readiness_policy = json.loads((ROOT / "state_templates/production_readiness_policy.json").read_text(encoding="utf-8"))

        self.assertEqual({key: deploy_policy["commands"][key] for key in expected}, expected)
        production_environment = module_settings["production_environment_manager"]
        self.assertEqual(production_environment["staging_health_check_command"], expected["CODEX_STAGING_HEALTH_CHECK_COMMAND"])
        self.assertEqual(production_environment["staging_smoke_test_command"], expected["CODEX_STAGING_SMOKE_TEST_COMMAND"])
        staging_wrappers = readiness_policy["staging_readiness_wrappers"]
        self.assertEqual(staging_wrappers["health_default_command"], expected["CODEX_STAGING_HEALTH_CHECK_COMMAND"])
        self.assertEqual(staging_wrappers["smoke_default_command"], expected["CODEX_STAGING_SMOKE_TEST_COMMAND"])

        actions = {item["id"]: item for item in action_catalog["actions"]}
        self.assertEqual(actions["staging_health_check"]["command"], expected["CODEX_STAGING_HEALTH_CHECK_COMMAND"])
        self.assertEqual(actions["staging_smoke_test"]["command"], expected["CODEX_STAGING_SMOKE_TEST_COMMAND"])

        from supervisor import production_deploy_controller, production_environment_manager

        self.assertEqual(
            {key: production_environment_manager.DEFAULT_COMMANDS[key] for key in expected},
            expected,
        )
        self.assertEqual(
            {key: production_deploy_controller.DEFAULT_COMMANDS[key] for key in expected},
            expected,
        )

    def assert_wrapper_contract(self, script_name: str, manager_action: str) -> None:
        path = ROOT / "scripts" / script_name
        text = path.read_text(encoding="utf-8")

        self.assertTrue(path.exists(), script_name)
        self.assertTrue(text.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("set -euo pipefail", text)
        self.assertIn('ROOT="${CODEX_DEV_CENTER_HOME:-$(cd "$SCRIPT_DIR/.." && pwd)}"', text)
        self.assertIn('PY="${CODEX_PYTHON:-python}"', text)
        self.assertIn(
            f'exec "$PY" supervisor/production_environment_manager.py {manager_action} --scope staging "$@"',
            text,
        )
        self.assertNotIn("--scope production", text)
        self.assertNotIn("CODEX_HEALTH_SCOPE", text)
        self.assertNotIn("CODEX_SMOKE_SCOPE", text)
        mode = path.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR, f"{script_name} must be executable by owner")
        self.assertTrue(os.access(path, os.X_OK), f"{script_name} must be executable")

    def test_staging_health_wrapper_uses_staging_scope(self):
        self.assert_wrapper_contract("staging_health_check.sh", "health-check")

    def test_staging_smoke_wrapper_uses_staging_scope(self):
        self.assert_wrapper_contract("staging_smoke_test.sh", "smoke-test")


if __name__ == "__main__":
    unittest.main()
