from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


SENSITIVE_CONFIG_KEYS = {"token", "secret", "password", "private_key", "api_key"}


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


def bootstrap_preflight(workspace: str | Path, *, require_codex_config: bool = False) -> dict[str, Any]:
    workspace_path = Path(workspace)
    checks: dict[str, Any] = {
        "workspace_exists": workspace_path.exists(),
        "workspace_is_dir": workspace_path.is_dir(),
        "workspace_writable": False,
        "codex_config_required": require_codex_config,
        "codex_config_path": str(workspace_path / ".codex" / "config"),
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
