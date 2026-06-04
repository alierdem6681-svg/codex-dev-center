#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()
SUPERVISOR_DIR = ROOT / "supervisor"
if str(SUPERVISOR_DIR) not in sys.path:
    sys.path.insert(0, str(SUPERVISOR_DIR))

try:
    from task_status_constants import (  # type: ignore
        KNOWN_TASK_STATUSES,
        TASK_STATUS_APPROVAL_REQUIRED,
        TASK_STATUS_ARCHIVED,
        TASK_STATUS_ARCHIVED_STALE,
        TASK_STATUS_ASSIGNED,
        TASK_STATUS_BLOCKED,
        TASK_STATUS_CANCELLED,
        TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP,
        TASK_STATUS_DEPLOYED,
        TASK_STATUS_DONE,
        TASK_STATUS_ERROR,
        TASK_STATUS_FAILED,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_NO_CHANGE,
        TASK_STATUS_PENDING,
        TASK_STATUS_PIPELINE_FAILED,
        TASK_STATUS_PROPOSAL_DONE,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_QUEUED,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_RECEIVED,
        TASK_STATUS_REQUIRES_APPROVAL,
        TASK_STATUS_ROUTED,
        TASK_STATUS_RUNNING,
        TASK_STATUS_STALLED,
        TASK_STATUS_TIMEOUT,
        TASK_STATUS_VALIDATION_FAILED,
        normalize_status,
        read_json as read_state_json,
    )
except Exception:
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
    TASK_STATUS_REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    TASK_STATUS_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    TASK_STATUS_BLOCKED = "BLOCKED"
    TASK_STATUS_STALLED = "STALLED"
    TASK_STATUS_FAILED = "FAILED"
    TASK_STATUS_FAILED_NO_PROPOSAL = "FAILED_NO_PROPOSAL"
    TASK_STATUS_FAILED_TIMEOUT = "FAILED_TIMEOUT"
    TASK_STATUS_FAILED_RETRYABLE = "FAILED_RETRYABLE"
    TASK_STATUS_TIMEOUT = "TIMEOUT"
    TASK_STATUS_ERROR = "ERROR"
    TASK_STATUS_DONE = "DONE"
    TASK_STATUS_NO_CHANGE = "NO_CHANGE"
    TASK_STATUS_ARCHIVED_STALE = "ARCHIVED_STALE"
    TASK_STATUS_ARCHIVED = "ARCHIVED"
    TASK_STATUS_CANCELLED = "CANCELLED"
    TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP = "CANCELLED_BY_OWNER_CLEANUP"
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
        TASK_STATUS_REQUIRES_APPROVAL,
        TASK_STATUS_APPROVAL_REQUIRED,
        TASK_STATUS_BLOCKED,
        TASK_STATUS_STALLED,
        TASK_STATUS_FAILED,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_TIMEOUT,
        TASK_STATUS_ERROR,
        TASK_STATUS_DONE,
        TASK_STATUS_NO_CHANGE,
        TASK_STATUS_ARCHIVED_STALE,
        TASK_STATUS_ARCHIVED,
        TASK_STATUS_CANCELLED,
        TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP,
        TASK_STATUS_DEPLOYED,
    }

    def normalize_status(value: Any, default: str = TASK_STATUS_QUEUED) -> str:
        raw = str(value or "").strip().upper()
        return raw if raw in KNOWN_TASK_STATUSES else default

    def read_state_json(path: Path, default: Any) -> Any:
        try:
            if Path(path).exists():
                return json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except Exception:
            return default
        return default


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


STAGE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "intake",
        "label": "Intake",
        "statuses": (TASK_STATUS_RECEIVED, TASK_STATUS_ROUTED),
    },
    {
        "id": "queue",
        "label": "Queue",
        "statuses": (TASK_STATUS_PENDING, TASK_STATUS_QUEUED),
    },
    {
        "id": "worker",
        "label": "Worker",
        "statuses": (TASK_STATUS_ASSIGNED, TASK_STATUS_RUNNING),
    },
    {
        "id": "proposal",
        "label": "Proposal",
        "statuses": (TASK_STATUS_PROPOSAL_READY, TASK_STATUS_PROPOSAL_DONE),
    },
    {
        "id": "validation",
        "label": "Validation",
        "statuses": (
            TASK_STATUS_READY_FOR_VALIDATION,
            TASK_STATUS_VALIDATION_FAILED,
            TASK_STATUS_PIPELINE_FAILED,
        ),
    },
    {
        "id": "approval",
        "label": "Approval",
        "statuses": (
            TASK_STATUS_REQUIRES_APPROVAL,
            TASK_STATUS_APPROVAL_REQUIRED,
            TASK_STATUS_BLOCKED,
        ),
    },
    {
        "id": "failed",
        "label": "Failed",
        "statuses": (
            TASK_STATUS_STALLED,
            TASK_STATUS_FAILED,
            TASK_STATUS_FAILED_NO_PROPOSAL,
            TASK_STATUS_FAILED_TIMEOUT,
            TASK_STATUS_FAILED_RETRYABLE,
            TASK_STATUS_TIMEOUT,
            TASK_STATUS_ERROR,
        ),
    },
    {
        "id": "closed",
        "label": "Closed",
        "statuses": (
            TASK_STATUS_DONE,
            TASK_STATUS_NO_CHANGE,
            TASK_STATUS_ARCHIVED_STALE,
            TASK_STATUS_ARCHIVED,
            TASK_STATUS_CANCELLED,
            TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP,
        ),
    },
    {
        "id": "deployed",
        "label": "Deployed",
        "statuses": (TASK_STATUS_DEPLOYED,),
    },
)

STATUS_TO_STAGE = {
    status: stage["id"]
    for stage in STAGE_DEFINITIONS
    for status in stage["statuses"]
}
MAPPED_STATUSES = set(STATUS_TO_STAGE)
UNMAPPED_KNOWN_STATUSES = sorted(set(KNOWN_TASK_STATUSES) - MAPPED_STATUSES)
ACTIVE_STATUSES = {
    TASK_STATUS_RECEIVED,
    TASK_STATUS_ROUTED,
    TASK_STATUS_PENDING,
    TASK_STATUS_QUEUED,
    TASK_STATUS_ASSIGNED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_PROPOSAL_READY,
    TASK_STATUS_PROPOSAL_DONE,
    TASK_STATUS_READY_FOR_VALIDATION,
}
FAILED_STATUSES = {
    TASK_STATUS_VALIDATION_FAILED,
    TASK_STATUS_PIPELINE_FAILED,
    TASK_STATUS_STALLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_FAILED_NO_PROPOSAL,
    TASK_STATUS_FAILED_TIMEOUT,
    TASK_STATUS_FAILED_RETRYABLE,
    TASK_STATUS_TIMEOUT,
    TASK_STATUS_ERROR,
}
BLOCKED_STATUSES = {
    TASK_STATUS_REQUIRES_APPROVAL,
    TASK_STATUS_APPROVAL_REQUIRED,
    TASK_STATUS_BLOCKED,
}

SAFE_TASK_KEYS = (
    "id",
    "status",
    "source",
    "risk",
    "risk_level",
    "assigned_worker",
    "parent_task",
    "created_at",
    "updated_at",
    "finished_at",
)
SAFE_MARKER_KEYS = {
    "pipeline_status": {
        "status",
        "ok",
        "task_to_deploy_test",
        "checked_at",
        "updated_at",
        "last_task_id",
        "last_commit",
        "commit",
        "branch",
        "source",
        "workflow_run_id",
        "runner",
    },
    "github_actions": {
        "status",
        "ok",
        "runner_name",
        "vm_target",
        "workflow",
        "last_deploy_status",
        "last_deploy_run_id",
        "last_deploy_run_url",
        "last_deploy_commit",
        "last_deploy_ref",
        "last_deploy_at",
        "last_smoke_status",
        "last_smoke_run_id",
        "last_smoke_run_url",
        "last_smoke_commit",
        "last_smoke_at",
        "last_backup_path",
        "public_health_url",
        "checked_at",
        "updated_at",
    },
    "production_deploy": {
        "status",
        "ok",
        "scope",
        "dry_run",
        "started_at",
        "finished_at",
        "updated_at",
        "commit",
    },
    "staging_deploy": {
        "status",
        "ok",
        "scope",
        "dry_run",
        "started_at",
        "finished_at",
        "updated_at",
        "commit",
    },
    "last_smoke_test": {
        "status",
        "ok",
        "scope",
        "checked_at",
        "updated_at",
        "finished_at",
    },
}


def stage_for_status(value: Any) -> str:
    return STATUS_TO_STAGE.get(normalize_status(value), "queue")


def read_json(path: Path, default: Any) -> Any:
    return read_state_json(Path(path), default)


def safe_scalar(value: Any, max_len: int = 160) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    text = str(value)
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def compact_task(task: dict[str, Any]) -> dict[str, Any]:
    status = normalize_status(task.get("status"))
    compact = {
        key: safe_scalar(task.get(key))
        for key in SAFE_TASK_KEYS
        if task.get(key) is not None
    }
    compact["status"] = status
    compact["stage"] = stage_for_status(status)
    if "risk" not in compact and "risk_level" in compact:
        compact["risk"] = compact["risk_level"]
    return compact


def task_sort_value(task: dict[str, Any]) -> str:
    for key in ("updated_at", "finished_at", "created_at", "id"):
        value = task.get(key)
        if value is not None:
            return str(value)
    return ""


def stage_state(stage_id: str, statuses: set[str]) -> str:
    if not statuses:
        return "empty"
    if stage_id == "approval" or statuses & BLOCKED_STATUSES:
        return "blocked"
    if stage_id == "failed" or statuses & FAILED_STATUSES:
        return "failed"
    if statuses & ACTIVE_STATUSES:
        return "active"
    return "complete"


def safe_marker(payload: Any, allowed_keys: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in sorted(allowed_keys):
        if key in payload:
            value = payload.get(key)
            if isinstance(value, str | bool | int | float) or value is None:
                safe[key] = safe_scalar(value)
    return safe


def read_flow_markers(state_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        "pipeline_status": safe_marker(
            read_json(state_dir / "pipeline_status.json", {}),
            SAFE_MARKER_KEYS["pipeline_status"],
        ),
        "github_actions": safe_marker(
            read_json(state_dir / "github_actions_status.json", {}),
            SAFE_MARKER_KEYS["github_actions"],
        ),
        "production_deploy": safe_marker(
            read_json(state_dir / "production_deploy_status.json", {}),
            SAFE_MARKER_KEYS["production_deploy"],
        ),
        "staging_deploy": safe_marker(
            read_json(state_dir / "staging_deploy_status.json", {}),
            SAFE_MARKER_KEYS["staging_deploy"],
        ),
        "last_smoke_test": safe_marker(
            read_json(state_dir / "last_smoke_test_status.json", {}),
            SAFE_MARKER_KEYS["last_smoke_test"],
        ),
    }


def marker_data_status(markers: dict[str, dict[str, Any]]) -> str:
    has_pipeline = bool(markers.get("pipeline_status"))
    has_actions = bool(markers.get("github_actions"))
    if has_pipeline and has_actions:
        return "available"
    if has_pipeline or has_actions:
        return "partial"
    return "empty"


def latest_marker_timestamp(markers: dict[str, dict[str, Any]]) -> str | None:
    values: list[str] = []
    for marker in markers.values():
        for key in ("updated_at", "checked_at", "last_deploy_at", "last_smoke_at"):
            value = marker.get(key)
            if value:
                values.append(str(value))
    return max(values) if values else None


def dashboard_refresh_seconds(root: Path) -> int:
    settings = read_json(
        root / "state" / "module_settings.json",
        read_json(root / "state_templates" / "module_settings.json", {}),
    )
    if isinstance(settings, dict):
        try:
            return int(settings.get("dashboard", {}).get("poll_seconds", 5))
        except Exception:
            return 5
    return 5


def build_pipeline_tracking(root: Path | str = ROOT, generated_at: str | None = None) -> dict[str, Any]:
    runtime_root = Path(root)
    state_dir = runtime_root / "state"
    markers = {
        "pipeline_status": safe_marker(
            read_json(state_dir / "pipeline_status.json", {}),
            SAFE_MARKER_KEYS["pipeline_status"],
        ),
        "github_actions": safe_marker(
            read_json(state_dir / "github_actions_status.json", {}),
            SAFE_MARKER_KEYS["github_actions"],
        ),
    }
    return {
        "ok": True,
        "generated_at": generated_at or utc_now(),
        "read_only": True,
        "non_mutating": True,
        "production_deploy_allowed": False,
        "critical_operations_allowed": False,
        "refresh_seconds": dashboard_refresh_seconds(runtime_root),
        "data_status": marker_data_status(markers),
        "last_updated_at": latest_marker_timestamp(markers),
        "source_files": [
            "state/github_actions_status.json",
            "state/pipeline_status.json",
        ],
        "github_actions": markers["github_actions"],
        "pipeline_status": markers["pipeline_status"],
    }


def build_pipeline_flow(root: Path | str = ROOT, generated_at: str | None = None) -> dict[str, Any]:
    runtime_root = Path(root)
    state_dir = runtime_root / "state"
    queue = read_json(state_dir / "task_queue.json", {"tasks": []})
    tasks = queue.get("tasks", []) if isinstance(queue, dict) else []
    if not isinstance(tasks, list):
        tasks = []

    normalized_tasks = [task for task in tasks if isinstance(task, dict)]
    normalized_statuses = [normalize_status(task.get("status")) for task in normalized_tasks]
    status_counts: dict[str, int] = {}
    for status in normalized_statuses:
        status_counts[status] = status_counts.get(status, 0) + 1

    stages = []
    for order, definition in enumerate(STAGE_DEFINITIONS, start=1):
        stage_statuses = set(definition["statuses"])
        stage_tasks = [
            task
            for task in normalized_tasks
            if normalize_status(task.get("status")) in stage_statuses
        ]
        stage_tasks.sort(key=task_sort_value, reverse=True)
        stage_status_counts = {
            status: status_counts.get(status, 0)
            for status in definition["statuses"]
            if status_counts.get(status, 0)
        }
        stages.append(
            {
                "id": definition["id"],
                "label": definition["label"],
                "order": order,
                "statuses": list(definition["statuses"]),
                "state": stage_state(definition["id"], set(stage_status_counts)),
                "task_count": len(stage_tasks),
                "status_counts": stage_status_counts,
                "tasks": [compact_task(task) for task in stage_tasks[:8]],
            }
        )

    non_empty_stages = [stage for stage in stages if stage["task_count"] > 0]
    current_stage = non_empty_stages[-1]["id"] if non_empty_stages else None
    return {
        "ok": True,
        "generated_at": generated_at or utc_now(),
        "non_mutating": True,
        "source_files": [
            "state/task_queue.json",
            "state/pipeline_status.json",
            "state/github_actions_status.json",
            "state/production_deploy_status.json",
            "state/staging_deploy_status.json",
            "state/last_smoke_test_status.json",
        ],
        "summary": {
            "task_count": len(normalized_tasks),
            "stage_count": len(stages),
            "current_stage": current_stage,
            "status_counts": status_counts,
            "failed_count": sum(status_counts.get(status, 0) for status in FAILED_STATUSES),
            "blocked_count": sum(status_counts.get(status, 0) for status in BLOCKED_STATUSES),
            "unmapped_known_statuses": UNMAPPED_KNOWN_STATUSES,
        },
        "stages": stages,
        "markers": read_flow_markers(state_dir),
    }
