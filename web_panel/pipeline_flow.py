#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
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
STAGE_ORDER_BY_ID = {
    stage["id"]: order
    for order, stage in enumerate(STAGE_DEFINITIONS, start=1)
}
STAGE_LABEL_BY_ID = {stage["id"]: stage["label"] for stage in STAGE_DEFINITIONS}
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
COMPLETE_STATUSES = {
    TASK_STATUS_DONE,
    TASK_STATUS_NO_CHANGE,
    TASK_STATUS_ARCHIVED_STALE,
    TASK_STATUS_ARCHIVED,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP,
    TASK_STATUS_DEPLOYED,
}
OVERALL_STATUS_PRIORITY = (
    tuple(FAILED_STATUSES),
    tuple(BLOCKED_STATUSES),
    (TASK_STATUS_RUNNING, TASK_STATUS_ASSIGNED, TASK_STATUS_READY_FOR_VALIDATION),
    (TASK_STATUS_PROPOSAL_DONE, TASK_STATUS_PROPOSAL_READY),
    (TASK_STATUS_QUEUED, TASK_STATUS_PENDING, TASK_STATUS_ROUTED, TASK_STATUS_RECEIVED),
    (TASK_STATUS_DEPLOYED,),
    tuple(COMPLETE_STATUSES),
)
LEGACY_MAIN_TASK_ID = "__legacy_ungrouped_tasks__"
LEGACY_MAIN_TASK_CODE = "LEGACY"
LEGACY_MAIN_TASK_TITLE = "Gruplanmamış Eski Görevler"
MAIN_TASK_CHILD_LIMIT = 12

SAFE_TASK_KEYS = (
    "id",
    "status",
    "source",
    "risk",
    "risk_level",
    "assigned_worker",
    "root_task_id",
    "parent_task_id",
    "parent_task",
    "dispatch_id",
    "repo_apply_child",
    "delivery_level",
    "pipeline_status",
    "pull_request_url",
    "merge_blocked_reason",
    "blocked_reason",
    "deploy_run_id",
    "deploy_run_url",
    "deploy_workflow_status",
    "deploy_workflow_conclusion",
    "smoke_run_id",
    "smoke_run_url",
    "smoke_workflow_status",
    "smoke_workflow_conclusion",
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
    },
    "github_actions": {
        "status",
        "ok",
        "runner_name",
        "workflow",
        "last_deploy_status",
        "last_deploy_run_id",
        "last_smoke_status",
        "last_smoke_run_id",
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


def task_id(task: dict[str, Any]) -> str:
    return str(task.get("id") or "").strip()


def relation_id(task: dict[str, Any]) -> str:
    for key in ("root_task_id", "parent_task_id", "parent_task"):
        value = str(task.get(key) or "").strip()
        if value and value != task_id(task):
            return value
    return ""


def referenced_relation_ids(tasks: list[dict[str, Any]]) -> set[str]:
    referenced: set[str] = set()
    for task in tasks:
        relation = relation_id(task)
        if relation:
            referenced.add(relation)
    return referenced


def ultimate_root_id(task: dict[str, Any], tasks_by_id: dict[str, dict[str, Any]]) -> str:
    current = task
    seen: set[str] = set()
    while True:
        current_id = task_id(current)
        if not current_id or current_id in seen:
            return current_id or LEGACY_MAIN_TASK_ID
        seen.add(current_id)
        parent_id = relation_id(current)
        if not parent_id:
            return current_id
        parent = tasks_by_id.get(parent_id)
        if parent is None:
            return parent_id
        current = parent


def is_self_root(task: dict[str, Any]) -> bool:
    own_id = task_id(task)
    return bool(own_id and str(task.get("root_task_id") or "").strip() == own_id)


def main_group_id(
    task: dict[str, Any],
    tasks_by_id: dict[str, dict[str, Any]],
    referenced_ids: set[str],
) -> str:
    relation = relation_id(task)
    if relation:
        root_id = ultimate_root_id(task, tasks_by_id)
        return root_id or relation

    own_id = task_id(task)
    if own_id and (own_id in referenced_ids or is_self_root(task)):
        return own_id

    return LEGACY_MAIN_TASK_ID


def safe_title_from_code(code: str) -> str:
    parts = [part for part in re.split(r"[-_\s]+", code) if part]
    skipped = {"CTO", "TASK", "JOB", "APPLY", "BACKLOG", "DISPATCH", "WORKER", "SUB"}
    words = []
    for part in parts:
        upper = part.upper()
        if upper in skipped or upper.startswith("SUB") or upper.isdigit():
            continue
        words.append(part.capitalize())
    if words:
        return safe_scalar(" ".join(words[-6:]), 80)
    return safe_scalar(f"Ana görev {code}", 80)


def group_current_stage(tasks: list[dict[str, Any]]) -> str | None:
    stage_ids = {stage_for_status(task.get("status")) for task in tasks}
    ordered = sorted(stage_ids, key=lambda stage_id: STAGE_ORDER_BY_ID.get(stage_id, 0))
    return ordered[-1] if ordered else None


def group_overall_status(tasks: list[dict[str, Any]]) -> str:
    statuses = {normalize_status(task.get("status")) for task in tasks}
    for group in OVERALL_STATUS_PRIORITY:
        for status in group:
            if status in statuses:
                return status
    return normalize_status(tasks[0].get("status")) if tasks else TASK_STATUS_QUEUED


def first_present(task: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = task.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def latest_pr(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for task in sorted(tasks, key=task_sort_value, reverse=True):
        url = first_present(task, ("pull_request_url", "pr_url", "github_pr_url"))
        if url:
            return {
                "task_id": safe_scalar(task_id(task)),
                "url": safe_scalar(url),
                "status": safe_scalar(first_present(task, ("merge_status", "pipeline_status", "status"))),
                "updated_at": safe_scalar(first_present(task, ("updated_at", "finished_at", "created_at"))),
            }
    return None


def latest_workflow_run(tasks: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    prefix = "deploy" if kind == "deploy" else "smoke"
    for task in sorted(tasks, key=task_sort_value, reverse=True):
        run_id = first_present(task, (f"{prefix}_run_id", f"{prefix}_workflow_run_id"))
        run_url = first_present(task, (f"{prefix}_run_url", f"{prefix}_workflow_run_url"))
        status = first_present(task, (f"{prefix}_workflow_status", f"{prefix}_status"))
        conclusion = first_present(task, (f"{prefix}_workflow_conclusion", f"{prefix}_conclusion"))
        commit = first_present(task, (f"{prefix}_commit", "deploy_commit"))
        if run_id or run_url or status or conclusion or commit:
            return {
                "task_id": safe_scalar(task_id(task)),
                "run_id": safe_scalar(run_id),
                "url": safe_scalar(run_url),
                "status": safe_scalar(status),
                "conclusion": safe_scalar(conclusion),
                "commit": safe_scalar(commit),
                "updated_at": safe_scalar(first_present(task, ("updated_at", "finished_at", "created_at"))),
            }
    return None


def blocked_reason(tasks: list[dict[str, Any]]) -> str:
    for task in sorted(tasks, key=task_sort_value, reverse=True):
        reason = first_present(task, ("merge_blocked_reason", "blocked_reason", "reason", "last_error_code"))
        if reason:
            return str(safe_scalar(reason))
    return ""


def build_main_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks_by_id = {task_id(task): task for task in tasks if task_id(task)}
    referenced_ids = referenced_relation_ids(tasks)
    groups: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        group_id = main_group_id(task, tasks_by_id, referenced_ids)
        groups.setdefault(group_id, []).append(task)

    main_tasks = []
    for group_id, group_tasks in groups.items():
        group_tasks.sort(key=task_sort_value, reverse=True)
        statuses = [normalize_status(task.get("status")) for task in group_tasks]
        status_counts: dict[str, int] = {}
        stage_counts: dict[str, int] = {}
        for status in statuses:
            status_counts[status] = status_counts.get(status, 0) + 1
            stage_id = stage_for_status(status)
            stage_counts[stage_id] = stage_counts.get(stage_id, 0) + 1

        current_stage = group_current_stage(group_tasks)
        current_order = STAGE_ORDER_BY_ID.get(current_stage or "", 0)
        total_stages = len(STAGE_DEFINITIONS)
        progress_percent = round((current_order / total_stages) * 100) if current_order else 0
        overall_status = group_overall_status(group_tasks)
        is_legacy = group_id == LEGACY_MAIN_TASK_ID
        child_candidates = [
            task
            for task in group_tasks
            if is_legacy or task_id(task) != group_id
        ]
        updated_at = task_sort_value(group_tasks[0]) if group_tasks else ""
        main_code = LEGACY_MAIN_TASK_CODE if is_legacy else safe_scalar(group_id, 120)
        main_title = LEGACY_MAIN_TASK_TITLE if is_legacy else safe_title_from_code(group_id)
        root_task_id = LEGACY_MAIN_TASK_CODE if is_legacy else safe_scalar(group_id, 160)
        main_tasks.append(
            {
                "id": safe_scalar(group_id),
                "code": main_code,
                "title": main_title,
                "main_task_code": main_code,
                "main_task_title": main_title,
                "root_task_id": root_task_id,
                "overall_status": overall_status,
                "status": overall_status,
                "stage": current_stage,
                "state": stage_state(current_stage or "", set(status_counts)) if current_stage else "empty",
                "progress_percent": progress_percent,
                "progress": {
                    "current_stage": current_stage,
                    "current_stage_label": STAGE_LABEL_BY_ID.get(current_stage or ""),
                    "completed_stage_count": current_order,
                    "total_stage_count": total_stages,
                    "percent": progress_percent,
                },
                "counts": {
                    "tasks": len(group_tasks),
                    "children": len(child_candidates),
                    "active": sum(status_counts.get(status, 0) for status in ACTIVE_STATUSES),
                    "failed": sum(status_counts.get(status, 0) for status in FAILED_STATUSES),
                    "blocked": sum(status_counts.get(status, 0) for status in BLOCKED_STATUSES),
                    "closed": sum(status_counts.get(status, 0) for status in COMPLETE_STATUSES),
                },
                "counts_by_status": status_counts,
                "status_counts": status_counts,
                "stage_counts": stage_counts,
                "children": [compact_task(task) for task in child_candidates[:MAIN_TASK_CHILD_LIMIT]],
                "latest_pr": latest_pr(group_tasks),
                "latest_deploy_run": latest_workflow_run(group_tasks, "deploy"),
                "latest_smoke_run": latest_workflow_run(group_tasks, "smoke"),
                "blocked_reason": blocked_reason(group_tasks),
                "updated_at": safe_scalar(updated_at),
            }
        )

    main_tasks.sort(
        key=lambda item: (
            item["code"] != LEGACY_MAIN_TASK_CODE,
            str(item.get("updated_at") or ""),
        ),
        reverse=True,
    )
    return main_tasks


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
    main_tasks = build_main_tasks(normalized_tasks)
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
            "main_task_count": len(main_tasks),
            "stage_count": len(stages),
            "current_stage": current_stage,
            "status_counts": status_counts,
            "failed_count": sum(status_counts.get(status, 0) for status in FAILED_STATUSES),
            "blocked_count": sum(status_counts.get(status, 0) for status in BLOCKED_STATUSES),
            "unmapped_known_statuses": UNMAPPED_KNOWN_STATUSES,
        },
        "stages": stages,
        "main_tasks": main_tasks,
        "markers": read_flow_markers(state_dir),
    }
