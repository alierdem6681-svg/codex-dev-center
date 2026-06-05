from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


SENSITIVE_CONFIG_KEYS = {"token", "secret", "password", "private_key", "api_key"}
TEST_MANIFEST_NAMES = ("package.json", "pyproject.toml", "go.mod", "Cargo.toml", "pom.xml", "Makefile")
TEST_FILE_PATTERNS = (
    "test_*.py",
    "*_test.py",
    "*_test.go",
    "*.test.js",
    "*.spec.js",
    "*.test.ts",
    "*.spec.ts",
)


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".bootstrap-write-test-{os.getpid()}"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _config_status(config_path: Path, require_codex_config: bool) -> tuple[str, list[str]]:
    issues: list[str] = []
    if not config_path.exists():
        if require_codex_config:
            issues.append("codex_config_missing")
            return "blocked_bootstrap_missing", issues
        return "ready", issues
    if not config_path.is_file():
        issues.append("codex_config_not_file")
        return "blocked_bootstrap_invalid", issues
    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        issues.append("codex_config_unreadable")
        return "blocked_bootstrap_invalid", issues
    if not text.strip():
        issues.append("codex_config_empty")
        return "blocked_bootstrap_invalid", issues
    lowered = text.lower()
    if any(key in lowered for key in SENSITIVE_CONFIG_KEYS):
        issues.append("codex_config_contains_sensitive_key_name")
        return "degraded_diagnostic", issues
    return "ready", issues


def _git_repo_status(workspace_path: Path, *, require_local_git_metadata: bool) -> tuple[str, dict[str, Any], list[str]]:
    issues: list[str] = []
    git_meta = workspace_path / ".git"
    checks: dict[str, Any] = {
        "required_local_metadata": require_local_git_metadata,
        "metadata_type": "directory" if git_meta.is_dir() else ("file" if git_meta.is_file() else "missing"),
        "tool_available": shutil.which("git") is not None,
        "is_inside_work_tree": False,
        "top_level_matches_workspace": False,
        "local_metadata": git_meta.is_dir(),
    }

    if not checks["tool_available"]:
        issues.append("git_tool_missing")
        return "invalid", checks, issues

    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(workspace_path),
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        top_level = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(workspace_path),
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        issues.append("repo_checkout_invalid")
        return "invalid", checks, issues

    checks["rev_parse_returncode"] = inside.returncode
    checks["is_inside_work_tree"] = inside.returncode == 0 and inside.stdout.strip().lower() == "true"
    if top_level.returncode == 0:
        top_path = Path(top_level.stdout.strip()).resolve()
        checks["top_level"] = str(top_path)
        checks["top_level_matches_workspace"] = top_path == workspace_path.resolve()

    if not checks["is_inside_work_tree"]:
        issues.append("repo_checkout_missing" if checks["metadata_type"] == "missing" else "repo_checkout_invalid")
        status = "missing" if checks["metadata_type"] == "missing" else "invalid"
        return status, checks, issues
    if not checks["top_level_matches_workspace"]:
        issues.append("repo_checkout_not_workspace_root")
        return "invalid", checks, issues
    if require_local_git_metadata and not checks["local_metadata"]:
        issues.append("repo_git_metadata_not_local")
        return "invalid", checks, issues
    return "ready", checks, issues


def _test_surface_status(workspace_path: Path) -> tuple[str, dict[str, Any], list[str]]:
    markers: list[str] = []
    for name in TEST_MANIFEST_NAMES:
        if (workspace_path / name).is_file():
            markers.append(name)

    tests_dir = workspace_path / "tests"
    if tests_dir.is_dir():
        for pattern in TEST_FILE_PATTERNS:
            for path in sorted(tests_dir.rglob(pattern)):
                if path.is_file():
                    markers.append(path.relative_to(workspace_path).as_posix())
                    if len(markers) >= 20:
                        break
            if len(markers) >= 20:
                break

    script = workspace_path / "scripts" / "codex_test_suite.sh"
    if script.is_file():
        markers.append("scripts/codex_test_suite.sh")

    checks = {
        "found": bool(markers),
        "markers": markers,
        "manifest_names": list(TEST_MANIFEST_NAMES),
        "test_file_patterns": list(TEST_FILE_PATTERNS),
    }
    if not markers:
        return "missing", checks, ["no_test_surface"]
    return "ready", checks, []


def _tool_status() -> dict[str, Any]:
    ripgrep_available = shutil.which("rg") is not None
    return {
        "ripgrep_available": ripgrep_available,
        "file_search_fallback": "rg" if ripgrep_available else "find",
    }


def bootstrap_preflight(
    workspace: str | Path,
    *,
    require_codex_config: bool = False,
    require_git_repo: bool = False,
    require_local_git_metadata: bool = False,
    require_test_surface: bool = False,
) -> dict[str, Any]:
    workspace_path = Path(workspace)
    checks: dict[str, Any] = {
        "workspace_exists": workspace_path.exists(),
        "workspace_is_dir": workspace_path.is_dir(),
        "workspace_writable": False,
        "codex_config_required": require_codex_config,
        "codex_config_path": str(workspace_path / ".codex" / "config"),
        "git_repo_required": require_git_repo,
        "local_git_metadata_required": require_local_git_metadata,
        "test_surface_required": require_test_surface,
        "tools": _tool_status(),
    }
    issues: list[str] = []

    if not checks["workspace_exists"]:
        issues.append("workspace_missing")
        status = "blocked_bootstrap_missing"
    elif not checks["workspace_is_dir"]:
        issues.append("workspace_not_directory")
        status = "blocked_bootstrap_invalid"
    else:
        checks["workspace_writable"] = _is_writable_dir(workspace_path)
        if not checks["workspace_writable"]:
            issues.append("workspace_not_writable")
            status = "blocked_bootstrap_invalid"
        else:
            status, config_issues = _config_status(workspace_path / ".codex" / "config", require_codex_config)
            issues.extend(config_issues)
            git_status, git_checks, git_issues = _git_repo_status(
                workspace_path,
                require_local_git_metadata=require_local_git_metadata,
            )
            checks["git_repo"] = git_checks
            checks["git_repo"]["status"] = git_status
            if require_git_repo and git_status != "ready":
                issues.extend(git_issues)
                if status in {"ready", "degraded_diagnostic"}:
                    status = "blocked_bootstrap_missing" if git_status == "missing" else "blocked_bootstrap_invalid"

            test_status, test_checks, test_issues = _test_surface_status(workspace_path)
            checks["test_surface"] = test_checks
            checks["test_surface"]["status"] = test_status
            if require_test_surface and test_status != "ready":
                issues.extend(test_issues)
                if status in {"ready", "degraded_diagnostic"}:
                    status = "blocked_no_test_surface"

    ready = status == "ready"
    return {
        "ok": ready,
        "status": status,
        "issues": issues,
        "checks": checks,
        "diagnostic_only": status == "degraded_diagnostic",
        "secret_values_logged": False,
    }


def write_bootstrap_diagnostics(workspace: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(workspace) / "bootstrap_diagnostics.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
