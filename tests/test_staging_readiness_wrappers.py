import os
import stat
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StagingReadinessWrapperTest(unittest.TestCase):
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
