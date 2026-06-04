import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.safe_test_scratch import (
    REPO_ROOT,
    assert_repo_unchanged,
    guard_repo_clean,
    make_test_scratch_dir,
    repo_snapshot,
    resolve_test_scratch_root,
    test_scratch,
)


class SafeTestScratchStandardTest(unittest.TestCase):
    def test_test_scratch_root_redirects_runtime_environment_and_cleans_up(self):
        previous_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"TEST_SCRATCH_ROOT": tmp, "TEST_WORKER_ID": "gw0"}, clear=False):
                with test_scratch("unit suite", "creates runtime files") as scratch:
                    self.assertTrue(scratch.is_dir())
                    self.assertTrue(scratch.as_posix().startswith(Path(tmp).resolve().as_posix()))
                    self.assertIn("/unit-suite/gw0/", scratch.as_posix())
                    self.assertTrue(os.environ["TMPDIR"].startswith(scratch.as_posix()))
                    self.assertTrue(os.environ["HOME"].startswith(scratch.as_posix()))
                    self.assertTrue(os.environ["XDG_CACHE_HOME"].startswith(scratch.as_posix()))
                    self.assertEqual(tempfile.gettempdir(), os.environ["TMPDIR"])
                    Path(os.environ["CODEX_TEST_OUTPUT_DIR"]).joinpath("result.txt").write_text("ok", encoding="utf-8")
                    scratch_path = scratch

                self.assertFalse(scratch_path.exists())

        self.assertEqual(os.environ.get("HOME"), previous_home)

    def test_scratch_root_fallbacks_use_runner_temp_before_tmpdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"RUNNER_TEMP": tmp}, clear=True):
                self.assertEqual(resolve_test_scratch_root(), Path(tmp).resolve() / "test-scratch")

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"TMPDIR": tmp}, clear=True):
                self.assertEqual(resolve_test_scratch_root(), Path(tmp).resolve() / "test-scratch")

    def test_scratch_root_inside_repo_is_rejected(self):
        with mock.patch.dict(os.environ, {"TEST_SCRATCH_ROOT": str(REPO_ROOT / "tmp" / "test-scratch")}, clear=False):
            with self.assertRaisesRegex(ValueError, "outside repo"):
                resolve_test_scratch_root()
        with self.assertRaisesRegex(ValueError, "outside repo"):
            make_test_scratch_dir("suite", "test", root=REPO_ROOT / "tmp" / "test-scratch")

    def test_unique_scratch_directory_names_do_not_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = make_test_scratch_dir("suite", "same test", root=Path(tmp), worker_id="worker-1")
            second = make_test_scratch_dir("suite", "same test", root=Path(tmp), worker_id="worker-1")
            try:
                self.assertNotEqual(first, second)
                self.assertTrue(first.exists())
                self.assertTrue(second.exists())
                self.assertEqual(first.parent, second.parent)
            finally:
                shutil.rmtree(first, ignore_errors=True)
                shutil.rmtree(second, ignore_errors=True)

    def test_repo_guard_detects_unallowlisted_repo_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "README.md").write_text("before\n", encoding="utf-8")
            before = repo_snapshot(root)

            (root / "state").mkdir()
            (root / "state" / "runtime.json").write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(AssertionError, "created=state/runtime.json"):
                assert_repo_unchanged(before, root=root)

            assert_repo_unchanged(before, root=root, allowlist=("state/",))

    def test_repo_guard_context_allows_clean_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "README.md").write_text("stable\n", encoding="utf-8")

            with guard_repo_clean(root=root):
                self.assertEqual((root / "docs" / "README.md").read_text(encoding="utf-8"), "stable\n")


if __name__ == "__main__":
    unittest.main()
