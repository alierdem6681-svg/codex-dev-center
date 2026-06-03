#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TASK_STATUS_RECEIVED = "RECEIVED"
TASK_STATUS_ROUTED = "ROUTED"
TASK_STATUS_PENDING = "PENDING"
TASK_STATUS_QUEUED = "QUEUED"
TASK_STATUS_ASSIGNED = "ASSIGNED"
TASK_STATUS_RUNNING = "RUNNING"
TASK_STATUS_PROPOSAL_READY = "PROPOSAL_READY"
TASK_STATUS_PROPOSAL_DONE = "PROPOSAL_DONE"
TASK_STATUS_READY_FOR_VALIDATION = "READY_FOR_VALIDATION"
TASK_STATUS_VALIDATION_FAILED = "VALIDATION_FAILED"
TASK_STATUS_PIPELINE_FAILED = "PIPELINE_FAILED"
TASK_STATUS_DONE = "DONE"
TASK_STATUS_STALLED = "STALLED"
TASK_STATUS_FAILED = "FAILED"
TASK_STATUS_FAILED_NO_PROPOSAL = "FAILED_NO_PROPOSAL"
TASK_STATUS_FAILED_TIMEOUT = "FAILED_TIMEOUT"
TASK_STATUS_FAILED_RETRYABLE = "FAILED_RETRYABLE"
TASK_STATUS_TIMEOUT = "TIMEOUT"
TASK_STATUS_ERROR = "ERROR"
TASK_STATUS_ARCHIVED_STALE = "ARCHIVED_STALE"
TASK_STATUS_REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
TASK_STATUS_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
TASK_STATUS_BLOCKED = "BLOCKED"
TASK_STATUS_DEPLOYED = "DEPLOYED"

KNOWN_TASK_STATUSES = {
    TASK_STATUS_RECEIVED,
    TASK_STATUS_ROUTED,
    TASK_STATUS_PENDING,
    TASK_STATUS_QUEUED,
    TASK_STATUS_ASSIGNED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_PROPOSAL_READY,
    TASK_STATUS_PROPOSAL_DONE,
    TASK_STATUS_READY_FOR_VALIDATION,
    TASK_STATUS_VALIDATION_FAILED,
    TASK_STATUS_PIPELINE_FAILED,
    TASK_STATUS_DONE,
    TASK_STATUS_STALLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_FAILED_NO_PROPOSAL,
    TASK_STATUS_FAILED_TIMEOUT,
    TASK_STATUS_FAILED_RETRYABLE,
    TASK_STATUS_TIMEOUT,
    TASK_STATUS_ERROR,
    TASK_STATUS_ARCHIVED_STALE,
    TASK_STATUS_REQUIRES_APPROVAL,
    TASK_STATUS_APPROVAL_REQUIRED,
    TASK_STATUS_BLOCKED,
    TASK_STATUS_DEPLOYED,
}

ACTIVE_TASK_STATUSES = {
    TASK_STATUS_PENDING,
    TASK_STATUS_QUEUED,
    TASK_STATUS_ASSIGNED,
    TASK_STATUS_RUNNING,
}

TERMINAL_TASK_STATUSES = {
    TASK_STATUS_PROPOSAL_READY,
    TASK_STATUS_PROPOSAL_DONE,
    TASK_STATUS_READY_FOR_VALIDATION,
    TASK_STATUS_VALIDATION_FAILED,
    TASK_STATUS_PIPELINE_FAILED,
    TASK_STATUS_DONE,
    TASK_STATUS_STALLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_FAILED_NO_PROPOSAL,
    TASK_STATUS_FAILED_TIMEOUT,
    TASK_STATUS_FAILED_RETRYABLE,
    TASK_STATUS_TIMEOUT,
    TASK_STATUS_ERROR,
    TASK_STATUS_ARCHIVED_STALE,
    TASK_STATUS_REQUIRES_APPROVAL,
    TASK_STATUS_APPROVAL_REQUIRED,
    TASK_STATUS_BLOCKED,
    TASK_STATUS_DEPLOYED,
}

APPROVAL_RISKS = {"HIGH", "CRITICAL"}
WORKER_BLOCKED_SOURCES = {"telegram"}

SENSITIVE_PATTERNS = [
    re.compile(r"(?i)\b(token|api[_-]?key|password|passwd|secret|private[_-]?key)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]

STATUS_ALIASES = {
    "": TASK_STATUS_QUEUED,
    "queued": TASK_STATUS_QUEUED,
    "queue": TASK_STATUS_QUEUED,
    "pending": TASK_STATUS_PENDING,
    "assigned": TASK_STATUS_ASSIGNED,
    "running": TASK_STATUS_RUNNING,
    "proposal_ready": TASK_STATUS_PROPOSAL_READY,
    "done": TASK_STATUS_DONE,
    "failed": TASK_STATUS_FAILED,
    "failed_no_proposal": TASK_STATUS_FAILED_NO_PROPOSAL,
    "failed_timeout": TASK_STATUS_FAILED_TIMEOUT,
    "failed_retryable": TASK_STATUS_FAILED_RETRYABLE,
    "proposal_done": TASK_STATUS_PROPOSAL_DONE,
    "ready_for_validation": TASK_STATUS_READY_FOR_VALIDATION,
    "validation_failed": TASK_STATUS_VALIDATION_FAILED,
    "pipeline_failed": TASK_STATUS_PIPELINE_FAILED,
    "archived_stale": TASK_STATUS_ARCHIVED_STALE,
    "stalled": TASK_STATUS_STALLED,
    "timeout": TASK_STATUS_TIMEOUT,
    "error": TASK_STATUS_ERROR,
    "received": TASK_STATUS_RECEIVED,
    "routed": TASK_STATUS_ROUTED,
    "requires_approval": TASK_STATUS_REQUIRES_APPROVAL,
    "approval_required": TASK_STATUS_APPROVAL_REQUIRED,
    "blocked": TASK_STATUS_BLOCKED,
    "deployed": TASK_STATUS_DEPLOYED,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_status(value: Any, default: str = TASK_STATUS_QUEUED) -> str:
    raw = str(value or "").strip()
    if raw in KNOWN_TASK_STATUSES:
        return raw
    upper = raw.upper()
    if upper in KNOWN_TASK_STATUSES:
        return upper
    return STATUS_ALIASES.get(raw.lower(), default)


def redact_sensitive_text(value: Any) -> str:
    text = str(value or "")
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub("[REDACTED_SECRET]", text)
    return text


def normalize_risk(value: Any) -> str:
    risk = str(value or "low").strip().lower()
    if risk not in {"low", "medium", "high", "critical"}:
        return "medium"
    return risk


def task_risk_upper(task: dict[str, Any]) -> str:
    return normalize_risk(task.get("risk") or task.get("risk_level")).upper()


def normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    task["status"] = normalize_status(task.get("status"))
    risk = normalize_risk(task.get("risk") or task.get("risk_level"))
    task["risk"] = risk
    task["risk_level"] = risk
    if "source" not in task or not str(task.get("source", "")).strip():
        task["source"] = "local"
    task["source"] = str(task["source"]).strip().lower()
    return task


def is_active_task(task: dict[str, Any]) -> bool:
    return normalize_status(task.get("status")) in ACTIVE_TASK_STATUSES


def worker_block_reason(task: dict[str, Any]) -> str:
    source = str(task.get("source", "")).lower()
    if task.get("worker_eligible") is False:
        return "worker_eligible_false"
    if source in WORKER_BLOCKED_SOURCES:
        return "telegram_reserved_for_cto"
    if task_risk_upper(task) in APPROVAL_RISKS:
        return "approval_required"
    return ""


def is_worker_eligible_task(task: dict[str, Any]) -> bool:
    return is_active_task(task) and not worker_block_reason(task)


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    return default


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, dict):
        data["updated_at"] = utc_now()
    tmp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_audit(root: Path, event: str, payload: dict[str, Any]) -> None:
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    record = {"created_at": utc_now(), "event": event, **payload}
    with (log_dir / "cto_audit.ndjson").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def normalize_queue_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    changes: list[dict[str, Any]] = []
    tasks = payload.setdefault("tasks", [])
    for task in tasks:
        if not isinstance(task, dict):
            continue
        before_status = task.get("status")
        before_risk = task.get("risk") or task.get("risk_level")
        normalize_task(task)
        if task.get("status") != before_status or task.get("risk") != before_risk:
            changes.append(
                {
                    "id": task.get("id"),
                    "from_status": before_status,
                    "to_status": task.get("status"),
                    "from_risk": before_risk,
                    "to_risk": task.get("risk"),
                }
            )
    payload["updated_at"] = utc_now()
    return payload, changes
