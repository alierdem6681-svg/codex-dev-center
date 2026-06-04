#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .state_file_lock import state_file_lock
except ImportError:
    from state_file_lock import state_file_lock

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
TASK_STATUS_ARCHIVED = "ARCHIVED"
TASK_STATUS_CANCELLED = "CANCELLED"
TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP = "CANCELLED_BY_OWNER_CLEANUP"
TASK_STATUS_NO_CHANGE = "NO_CHANGE"
TASK_STATUS_REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
TASK_STATUS_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
TASK_STATUS_BLOCKED = "BLOCKED"
TASK_STATUS_DEPLOYED = "DEPLOYED"
TASK_DEFAULT_MAX_ATTEMPTS = 1

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
    TASK_STATUS_ARCHIVED,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP,
    TASK_STATUS_NO_CHANGE,
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
    TASK_STATUS_ARCHIVED,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP,
    TASK_STATUS_NO_CHANGE,
    TASK_STATUS_REQUIRES_APPROVAL,
    TASK_STATUS_APPROVAL_REQUIRED,
    TASK_STATUS_BLOCKED,
    TASK_STATUS_DEPLOYED,
}

APPROVAL_RISKS = {"HIGH", "CRITICAL"}
WORKER_BLOCKED_SOURCES = {"telegram"}

SENSITIVE_PATTERNS = [
    re.compile(r"(?i)\b[A-Za-z0-9_-]*(?:token|api[_-]?key|password|passwd|secret|private[_-]?key)[A-Za-z0-9_-]*\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"(?i)\b(token|api[_-]?key|password|passwd|secret|private[_-]?key)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}\b"),
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
    "in_progress": TASK_STATUS_RUNNING,
    "proposal_ready": TASK_STATUS_PROPOSAL_READY,
    "done": TASK_STATUS_DONE,
    "complete": TASK_STATUS_DONE,
    "completed": TASK_STATUS_DONE,
    "failed": TASK_STATUS_FAILED,
    "failed_no_proposal": TASK_STATUS_FAILED_NO_PROPOSAL,
    "failed_timeout": TASK_STATUS_FAILED_TIMEOUT,
    "failed_retryable": TASK_STATUS_FAILED_RETRYABLE,
    "proposal_done": TASK_STATUS_PROPOSAL_DONE,
    "ready_for_validation": TASK_STATUS_READY_FOR_VALIDATION,
    "validation_failed": TASK_STATUS_VALIDATION_FAILED,
    "pipeline_failed": TASK_STATUS_PIPELINE_FAILED,
    "archived_stale": TASK_STATUS_ARCHIVED_STALE,
    "archived": TASK_STATUS_ARCHIVED,
    "cancelled": TASK_STATUS_CANCELLED,
    "canceled": TASK_STATUS_CANCELLED,
    "cancelled_by_owner_cleanup": TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP,
    "canceled_by_owner_cleanup": TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP,
    "no_change": TASK_STATUS_NO_CHANGE,
    "noop": TASK_STATUS_NO_CHANGE,
    "no_op": TASK_STATUS_NO_CHANGE,
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
    alias_key = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    return STATUS_ALIASES.get(alias_key, default)


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


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def ensure_dispatch_contract(task: dict[str, Any]) -> dict[str, Any]:
    task_id = str(task.get("id") or "").strip()
    parent_task_id = str(task.get("parent_task_id") or "").strip()
    root_task_id = str(task.get("root_task_id") or parent_task_id or task_id).strip()
    dispatch_id = str(task.get("dispatch_id") or task_id or root_task_id).strip()

    if root_task_id:
        task["root_task_id"] = root_task_id
    if dispatch_id:
        task["dispatch_id"] = dispatch_id

    attempt = _positive_int(task.get("attempt"), 1)
    max_attempts = _positive_int(task.get("max_attempts"), TASK_DEFAULT_MAX_ATTEMPTS)
    if max_attempts < attempt:
        max_attempts = attempt
    task["attempt"] = attempt
    task["max_attempts"] = max_attempts

    assigned_worker = str(task.get("assigned_worker") or "").strip()
    worker_id = str(task.get("worker_id") or assigned_worker).strip()
    if worker_id:
        task["worker_id"] = worker_id

    task.setdefault("last_error_code", "")
    task.setdefault("claimed_at", None)
    task.setdefault("finished_at", None)
    return task


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
    ensure_dispatch_contract(task)
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


def _json_corrupt_backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return path.with_name(f"{path.name}.corrupt.{stamp}.bak")


def _fsync_parent(path: Path) -> None:
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _load_json_text(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return _load_json_text(path)
    except Exception:
        try:
            backup = _json_corrupt_backup_path(path)
            shutil.copy2(path, backup)
        except Exception:
            pass
        for candidate in sorted(path.parent.glob(path.name + ".*.tmp"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                return _load_json_text(candidate)
            except Exception:
                continue
        return default
    return default


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with state_file_lock(path):
        if isinstance(data, dict):
            data["updated_at"] = utc_now()
        tmp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
        encoded = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        _load_json_text(tmp)
        os.replace(tmp, path)
        _fsync_parent(path)


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
