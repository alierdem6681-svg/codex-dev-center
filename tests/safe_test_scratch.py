from __future__ import annotations

import contextlib
import hashlib
import itertools
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
_COUNTER = itertools.count()
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")
_SKIP_SNAPSHOT_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _clean_component(value: str, fallback: str) -> str:
    cleaned = _SAFE_COMPONENT.sub("-", str(value or "").strip()).strip(".-")
    return (cleaned or fallback)[:80]


def resolve_test_scratch_root(repo_root: Path = REPO_ROOT) -> Path:
    """Resolve the shared scratch root without allowing repo-local output."""
    if os.environ.get("TEST_SCRATCH_ROOT"):
        root = Path(os.environ["TEST_SCRATCH_ROOT"]).expanduser()
    elif os.environ.get("RUNNER_TEMP"):
        root = Path(os.environ["RUNNER_TEMP"]).expanduser() / "test-scratch"
    else:
        root = Path(os.environ.get("TMPDIR") or tempfile.gettempdir()).expanduser() / "test-scratch"

    resolved = root.resolve()
    resolved_repo = repo_root.resolve()
    if _is_relative_to(resolved, resolved_repo):
        raise ValueError(f"test scratch root must be outside repo: {resolved}")
    return resolved


def make_test_scratch_dir(
    suite: str,
    test_name: str,
    *,
    root: Path | None = None,
    worker_id: str | None = None,
) -> Path:
    """Create one atomically unique scratch directory for a test."""
    scratch_root = Path(root).resolve() if root is not None else resolve_test_scratch_root()
    if _is_relative_to(scratch_root, REPO_ROOT.resolve()):
        raise ValueError(f"test scratch root must be outside repo: {scratch_root}")
    worker = _clean_component(
        worker_id or os.environ.get("TEST_WORKER_ID") or os.environ.get("PYTEST_XDIST_WORKER") or "main",
        "main",
    )
    suite_dir = scratch_root / _clean_component(suite, "suite") / worker
    suite_dir.mkdir(parents=True, exist_ok=True)

    test_hash = hashlib.sha256(str(test_name or "test").encode("utf-8")).hexdigest()[:12]
    for _ in range(1000):
        candidate = suite_dir / f"{test_hash}-{os.getpid()}-{next(_COUNTER)}"
        try:
            candidate.mkdir(mode=0o700)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"could not create unique scratch directory under {suite_dir}")


@contextlib.contextmanager
def test_scratch(
    suite: str,
    test_name: str,
    *,
    root: Path | None = None,
    worker_id: str | None = None,
) -> Iterator[Path]:
    """Yield an isolated scratch directory and redirect runtime env there."""
    scratch = make_test_scratch_dir(suite, test_name, root=root, worker_id=worker_id)
    env_paths = {
        "TMPDIR": scratch / "tmp",
        "TEMP": scratch / "tmp",
        "TMP": scratch / "tmp",
        "HOME": scratch / "home",
        "XDG_CACHE_HOME": scratch / "cache",
        "XDG_CONFIG_HOME": scratch / "config",
        "CODEX_TEST_OUTPUT_DIR": scratch / "output",
        "TEST_SCRATCH_ACTIVE_DIR": scratch,
    }
    for path in env_paths.values():
        Path(path).mkdir(parents=True, exist_ok=True)

    old_env = {key: os.environ.get(key) for key in env_paths}
    old_tempdir = tempfile.tempdir
    try:
        for key, path in env_paths.items():
            os.environ[key] = str(path)
        tempfile.tempdir = str(env_paths["TMPDIR"])
        yield scratch
    finally:
        tempfile.tempdir = old_tempdir
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        keep = os.environ.get("TEST_SCRATCH_KEEP") == "1" or os.environ.get("KEEP_TEST_SCRATCH") == "1"
        if not keep:
            shutil.rmtree(scratch, ignore_errors=True)


def repo_snapshot(root: Path = REPO_ROOT) -> dict[str, tuple[int, int]]:
    """Capture repo file metadata without reading file contents."""
    snapshot: dict[str, tuple[int, int]] = {}
    root = Path(root).resolve()
    for path in root.rglob("*"):
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(part in _SKIP_SNAPSHOT_PARTS for part in rel.parts):
            continue
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError:
            continue
        snapshot[rel.as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def _matches_allowlist(rel: str, allowlist: tuple[str, ...]) -> bool:
    for item in allowlist:
        normalized = str(item).replace("\\", "/").lstrip("/")
        if normalized.endswith("/") and rel.startswith(normalized):
            return True
        if rel == normalized:
            return True
    return False


def assert_repo_unchanged(
    before: dict[str, tuple[int, int]],
    *,
    root: Path = REPO_ROOT,
    allowlist: tuple[str, ...] = (),
) -> None:
    after = repo_snapshot(root)
    before_keys = set(before)
    after_keys = set(after)
    created = sorted(rel for rel in after_keys - before_keys if not _matches_allowlist(rel, allowlist))
    deleted = sorted(rel for rel in before_keys - after_keys if not _matches_allowlist(rel, allowlist))
    modified = sorted(
        rel
        for rel in before_keys & after_keys
        if before[rel] != after[rel] and not _matches_allowlist(rel, allowlist)
    )
    if created or deleted or modified:
        details = []
        if created:
            details.append("created=" + ",".join(created[:20]))
        if deleted:
            details.append("deleted=" + ",".join(deleted[:20]))
        if modified:
            details.append("modified=" + ",".join(modified[:20]))
        raise AssertionError("repo changed outside allowlist: " + "; ".join(details))


@contextlib.contextmanager
def guard_repo_clean(
    *,
    root: Path = REPO_ROOT,
    allowlist: tuple[str, ...] = (),
) -> Iterator[None]:
    before = repo_snapshot(root)
    try:
        yield
    finally:
        assert_repo_unchanged(before, root=root, allowlist=allowlist)
