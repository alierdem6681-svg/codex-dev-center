from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTRACT_VERSION = 1
SUMMARY_MAX_CHARS = 280
TITLE_MAX_CHARS = 120
ID_MAX_CHARS = 96

STATUS_FILES = (
    "memory_os_status.json",
    "memory_os_health.json",
)
CONTEXT_FILES = (
    "memory_os_last_context.json",
    "memory_os_context.json",
)

HEALTHY_VALUES = {"ACTIVE", "CURRENT", "DONE", "HEALTHY", "OK", "PASS", "READY"}
DEGRADED_VALUES = {"DEGRADED", "STALE", "WARN", "WARNING"}
UNHEALTHY_VALUES = {"BLOCKED", "ERROR", "FAIL", "FAILED", "UNHEALTHY"}

SENSITIVE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\b(?:token|secret|password|private[_-]?key)\s*[:=]\s*\S+", re.I),
)

FORBIDDEN_KEY_PARTS = (
    "authorization",
    "credential",
    "diff",
    "env",
    "file_id",
    "full_context",
    "header",
    "log",
    "message",
    "path",
    "payload",
    "private_key",
    "prompt",
    "raw",
    "secret",
    "stderr",
    "stdout",
    "token",
    "transcript",
)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"_read_error": str(exc), "_source_name": path.name}
    return default


def first_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def safe_text(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if len(text) > max_chars:
        return text[: max(0, max_chars - 3)].rstrip() + "..."
    return text


def forbidden_key_count(payload: Any) -> int:
    if isinstance(payload, dict):
        count = 0
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                count += 1
            count += forbidden_key_count(value)
        return count
    if isinstance(payload, list):
        return sum(forbidden_key_count(item) for item in payload)
    return 0


def read_first_state_file(state_dir: Path, names: tuple[str, ...]) -> tuple[dict[str, Any], str | None, bool]:
    for name in names:
        path = state_dir / name
        if path.exists():
            payload = read_json(path, {})
            if isinstance(payload, dict):
                return payload, name, "_read_error" not in payload
            return {"_read_error": "json_payload_not_object", "_source_name": name}, name, False
    return {}, None, False


def normalize_health(payload: dict[str, Any], source_name: str | None) -> dict[str, Any]:
    read_error = payload.get("_read_error")
    reason_codes: list[str] = []
    if not source_name:
        reason_codes.append("no_runtime_marker")
        return {
            "status": "UNKNOWN",
            "updated_at": None,
            "source": "missing",
            "reason_codes": reason_codes,
        }
    if read_error:
        return {
            "status": "UNKNOWN",
            "updated_at": None,
            "source": source_name,
            "reason_codes": ["runtime_marker_unreadable"],
        }

    explicit_status = first_value(payload, "status", "health", "state", "result")
    status_text = str(explicit_status or "").strip().upper()
    if status_text in HEALTHY_VALUES or (not status_text and payload.get("ok") is True):
        status = "HEALTHY"
    elif status_text in DEGRADED_VALUES:
        status = "DEGRADED"
    elif status_text in UNHEALTHY_VALUES or payload.get("ok") is False:
        status = "UNHEALTHY"
    else:
        status = "UNKNOWN"
        reason_codes.append("status_unmapped")

    if forbidden_key_count(payload):
        reason_codes.append("unsafe_fields_ignored")

    return {
        "status": status,
        "updated_at": first_value(payload, "updated_at", "checked_at", "generated_at"),
        "source": source_name,
        "reason_codes": reason_codes,
    }


def normalize_last_context(payload: dict[str, Any], source_name: str | None) -> dict[str, Any]:
    if not source_name:
        return {
            "available": False,
            "source": "missing",
            "reason_codes": ["no_last_context_marker"],
        }
    if payload.get("_read_error"):
        return {
            "available": False,
            "source": source_name,
            "reason_codes": ["last_context_unreadable"],
        }

    reason_codes: list[str] = []
    if forbidden_key_count(payload):
        reason_codes.append("unsafe_fields_ignored")

    summary = first_value(payload, "summary", "safe_summary", "last_context_summary", "context_summary")
    title = first_value(payload, "title", "name", "topic")
    item = {
        "available": bool(summary or title or first_value(payload, "context_id", "id", "task_id")),
        "source": source_name,
        "reason_codes": reason_codes,
        "context_id": safe_text(first_value(payload, "context_id", "id", "memory_id"), ID_MAX_CHARS),
        "task_id": safe_text(first_value(payload, "task_id", "root_task_id", "dispatch_id"), ID_MAX_CHARS),
        "title": safe_text(title, TITLE_MAX_CHARS),
        "summary": safe_text(summary, SUMMARY_MAX_CHARS),
        "intent_domain": safe_text(first_value(payload, "intent_domain", "domain"), ID_MAX_CHARS),
        "updated_at": first_value(payload, "updated_at", "last_used_at", "created_at"),
    }
    return {key: value for key, value in item.items() if value not in ("", None)}


def build_memory_os_status(root: Path) -> dict[str, Any]:
    root = Path(root)
    state_dir = root / "state"
    settings = read_json(root / "state_templates" / "module_settings.json", {})
    memory_settings = settings.get("memory_os", {}) if isinstance(settings, dict) else {}

    health_payload, health_source, _ = read_first_state_file(state_dir, STATUS_FILES)
    context_payload, context_source, _ = read_first_state_file(state_dir, CONTEXT_FILES)
    health = normalize_health(health_payload, health_source)
    last_context = normalize_last_context(context_payload, context_source)

    reason_codes = list(dict.fromkeys(health.get("reason_codes", []) + last_context.get("reason_codes", [])))
    status = health["status"]
    if status == "UNKNOWN" and last_context.get("available"):
        reason_codes.append("health_unknown_context_available")

    updated_at = health.get("updated_at") or last_context.get("updated_at")
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": now(),
        "enabled": bool(memory_settings.get("enabled", True)),
        "read_only": True,
        "status": status,
        "updated_at": updated_at,
        "reason_codes": reason_codes,
        "health": health,
        "last_context": last_context,
        "runtime_sources": {
            "health_marker": health_source or "missing",
            "last_context_marker": context_source or "missing",
        },
        "raw_context_included": False,
        "secret_values_included": False,
        "production_deploy_allowed": False,
        "mutating_actions_allowed": False,
    }
