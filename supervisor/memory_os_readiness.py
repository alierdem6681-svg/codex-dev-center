#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()

CONTRACT_VERSION = 1
MODULE_ID = "memory_os"
ACTION_ID = "check_memory_os_readiness"

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bAuthorization\s*:\s*\S+", re.I),
    re.compile(r"\b(token|secret|password|private_key)\b\s*[:=]\s*\S+", re.I),
]

REQUIRED_CAPABILITIES = [
    {
        "id": "record_schema",
        "label": "Memory record schema",
        "setting": "record_schema_defined",
    },
    {
        "id": "index_cache",
        "label": "Index/cache layer",
        "setting": "index_cache_enabled",
    },
    {
        "id": "health_state",
        "label": "Memory health state",
        "setting": "health_state_enabled",
    },
    {
        "id": "telegram_memory_commands",
        "label": "Telegram memory commands",
        "setting": "telegram_memory_commands_enabled",
    },
    {
        "id": "dashboard_memory_center",
        "label": "Dashboard Memory Center",
        "setting": "dashboard_memory_center_enabled",
    },
    {
        "id": "secret_redaction_tests",
        "label": "Secret redaction tests",
        "setting": "secret_redaction_tests_enabled",
    },
]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    return default


def read_repo_json(root: Path, rel: str, default: Any) -> Any:
    runtime_path = root / "state" / rel
    if runtime_path.exists():
        return read_json(runtime_path, default)
    return read_json(root / "state_templates" / rel, default)


def redact_text(value: Any) -> str:
    text = str(value or "")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED_SECRET]", text)
    return text


def module_entry(registry: dict[str, Any]) -> dict[str, Any]:
    modules = registry.get("modules", []) if isinstance(registry, dict) else []
    for item in modules:
        if isinstance(item, dict) and item.get("id") == MODULE_ID:
            return item
    return {}


def action_entry(catalog: dict[str, Any]) -> dict[str, Any]:
    actions = catalog.get("actions", []) if isinstance(catalog, dict) else []
    for item in actions:
        if isinstance(item, dict) and item.get("id") == ACTION_ID:
            return item
    return {}


def settings_for(root: Path) -> dict[str, Any]:
    settings = read_repo_json(root, "module_settings.json", {})
    memory_settings = settings.get(MODULE_ID, {}) if isinstance(settings, dict) else {}
    return memory_settings if isinstance(memory_settings, dict) else {}


def capability_enabled(root: Path, settings: dict[str, Any], capability: dict[str, str]) -> bool:
    capabilities = settings.get("capabilities", {})
    nested = capabilities.get(capability["id"], {}) if isinstance(capabilities, dict) else {}
    if not isinstance(nested, dict):
        nested = {}

    configured = bool(nested.get("implemented")) or bool(settings.get(capability["setting"]))
    evidence_files = nested.get("evidence_files", [])
    if isinstance(evidence_files, str):
        evidence_files = [evidence_files]
    if evidence_files:
        return configured and all((root / str(rel)).exists() for rel in evidence_files)
    return configured


def implemented_baseline_capabilities(root: Path, settings: dict[str, Any]) -> list[str]:
    implemented: list[str] = []
    capabilities = settings.get("capabilities", {})
    project_memory = capabilities.get("project_memory_file", {}) if isinstance(capabilities, dict) else {}
    configured = bool(project_memory.get("implemented")) if isinstance(project_memory, dict) else False
    if configured and (root / "memory" / "project_memory.md").exists():
        implemented.append("project_memory_file")
    return implemented


def build_memory_os_readiness(root: Path | None = None, checked_at: str | None = None) -> dict[str, Any]:
    root = (root or ROOT).resolve()
    registry = read_repo_json(root, "module_registry.json", {"modules": []})
    catalog = read_repo_json(root, "action_catalog.json", {"actions": []})
    settings = settings_for(root)

    module = module_entry(registry)
    action = action_entry(catalog)
    missing = [
        {
            "id": capability["id"],
            "label": capability["label"],
        }
        for capability in REQUIRED_CAPABILITIES
        if not capability_enabled(root, settings, capability)
    ]
    implemented = implemented_baseline_capabilities(root, settings)
    implemented.extend(
        capability["id"]
        for capability in REQUIRED_CAPABILITIES
        if capability_enabled(root, settings, capability)
    )

    module_status = redact_text(module.get("status") or "missing")
    ready = bool(module) and module_status == "active" and not missing
    status = "ready" if ready else "not_ready"
    blocking_reason = "" if ready else "blocked_not_implemented"

    return {
        "ok": True,
        "contract_version": CONTRACT_VERSION,
        "checked_at": checked_at or now(),
        "module_id": MODULE_ID,
        "status": status,
        "ready": ready,
        "blocking_reason": blocking_reason,
        "module_status": module_status,
        "module_registered": bool(module),
        "settings_registered": bool(settings),
        "action_registered": bool(action),
        "action_id": ACTION_ID if action else "",
        "required_capabilities": [item["id"] for item in REQUIRED_CAPABILITIES],
        "implemented_capabilities": implemented,
        "missing_capabilities": missing,
        "missing_count": len(missing),
        "summary": (
            "Memory OS is ready."
            if ready
            else "Memory OS is not implemented yet; existing project memory file is not a full Memory OS."
        ),
        "dashboard_safe": True,
        "raw_logs_included": False,
        "terminal_output_included": False,
        "secret_values_included": False,
        "production_deploy_allowed": False,
        "production_deploy_performed": False,
        "mutating_operations_performed": False,
    }


def build_dashboard_memory_os_readiness(root: Path | None = None) -> dict[str, Any]:
    payload = build_memory_os_readiness(root)
    missing_ids = [item["id"] for item in payload["missing_capabilities"]]
    return {
        "contract_version": payload["contract_version"],
        "status": payload["status"],
        "ready": payload["ready"],
        "blocking_reason": payload["blocking_reason"],
        "module_status": payload["module_status"],
        "missing_count": payload["missing_count"],
        "missing_capabilities": missing_ids[:8],
        "implemented_capabilities": payload["implemented_capabilities"][:8],
        "summary": payload["summary"],
        "dashboard_safe": True,
        "raw_logs_included": False,
        "terminal_output_included": False,
        "secret_values_included": False,
        "production_deploy_allowed": False,
        "production_deploy_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_memory_os_readiness(ROOT)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{payload['status']}: {payload['summary']}")


if __name__ == "__main__":
    main()
