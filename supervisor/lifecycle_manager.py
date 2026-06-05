#!/usr/bin/env python3
import argparse
import json
import os
import time
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from . import cto_autonomous_delivery
    from .critical_operation_policy import approval_required_payload
    from .state_file_lock import state_file_lock
    from .task_status_constants import (
        ACTIVE_TASK_STATUSES,
        TASK_STATUS_APPROVAL_REQUIRED,
        TASK_STATUS_ASSIGNED,
        TASK_STATUS_DONE,
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
        TASK_STATUS_RUNNING,
        TASK_STATUS_STALLED,
        TASK_STATUS_VALIDATION_FAILED,
        atomic_write_json,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_risk,
        normalize_status,
        read_json as read_state_json,
        worker_block_reason,
    )
except ImportError:
    import cto_autonomous_delivery
    from critical_operation_policy import approval_required_payload
    from state_file_lock import state_file_lock
    from task_status_constants import (
        ACTIVE_TASK_STATUSES,
        TASK_STATUS_APPROVAL_REQUIRED,
        TASK_STATUS_ASSIGNED,
        TASK_STATUS_DONE,
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
        TASK_STATUS_RUNNING,
        TASK_STATUS_STALLED,
        TASK_STATUS_VALIDATION_FAILED,
        atomic_write_json,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_risk,
        normalize_status,
        read_json as read_state_json,
        worker_block_reason,
    )

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
WORKERS_PATH = STATE / "workers.json"
QUEUE_PATH = STATE / "task_queue.json"
SYSTEM_STATE_PATH = STATE / "system_state.json"

WORKERS = ["worker-1", "worker-2", "worker-3", "worker-4"]
PENDING_WORKER_STATUSES = {TASK_STATUS_PENDING, TASK_STATUS_QUEUED}
CLAIMED_WORKER_STATUSES = {TASK_STATUS_ASSIGNED, TASK_STATUS_RUNNING}
WAKE_SELECTION_STATUSES = [
    TASK_STATUS_RUNNING,
    TASK_STATUS_ASSIGNED,
    TASK_STATUS_PENDING,
    TASK_STATUS_QUEUED,
]
POLL_SECONDS = 5
SLEEP_AFTER_IDLE_CYCLES = 4
BACKLOG_DISPATCHER_SOURCE = "cto_backlog_dispatcher"
BACKLOG_RECOVERABLE_STATUSES = {
    TASK_STATUS_FAILED,
    TASK_STATUS_FAILED_NO_PROPOSAL,
    TASK_STATUS_FAILED_RETRYABLE,
    TASK_STATUS_FAILED_TIMEOUT,
    TASK_STATUS_PIPELINE_FAILED,
    TASK_STATUS_PROPOSAL_DONE,
    TASK_STATUS_PROPOSAL_READY,
    TASK_STATUS_STALLED,
    TASK_STATUS_VALIDATION_FAILED,
}
PROGRESS_PROPAGATION_BLOCKED_STATUSES = {
    "ARCHIVED",
    "ARCHIVED_STALE",
    "CANCELLED",
    "CANCELLED_BY_OWNER_CLEANUP",
    "APPROVAL_REQUIRED",
    "REQUIRES_APPROVAL",
    "BLOCKED",
    "DEPLOYED",
}
CHILD_FAILURE_STATUSES = {
    TASK_STATUS_FAILED,
    TASK_STATUS_FAILED_NO_PROPOSAL,
    TASK_STATUS_FAILED_RETRYABLE,
    TASK_STATUS_FAILED_TIMEOUT,
    TASK_STATUS_PIPELINE_FAILED,
    TASK_STATUS_STALLED,
    TASK_STATUS_VALIDATION_FAILED,
}
VALIDATION_BATCH_SIZE = int(os.environ.get("CODEX_TASK_VALIDATION_BATCH_SIZE", "25"))
VALIDATION_INTERVAL_SECONDS = int(os.environ.get("CODEX_TASK_VALIDATION_INTERVAL_SECONDS", "60"))
VALIDATION_PIPELINE_MAX_AGE_SECONDS = int(os.environ.get("CODEX_TASK_VALIDATION_PIPELINE_MAX_AGE_SECONDS", "86400"))
DELIVERY_INTERVAL_SECONDS = int(os.environ.get("CODEX_AUTONOMOUS_DELIVERY_INTERVAL_SECONDS", "120"))

def now():
    return datetime.now(timezone.utc).isoformat()

def log(msg):
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with (LOGS / "lifecycle.log").open("a", encoding="utf-8") as f:
            f.write(f"{now()} {msg}\n")
    except OSError:
        return

def read_json(path, default):
    return read_state_json(Path(path), default)

def write_json(path, data):
    atomic_write_json(Path(path), data)

def safe_id(value):
    out = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(value or "TASK"))
    return out[:90] or "TASK"

def service_name(worker):
    return f"codex-{worker}"

def systemctl(action, worker):
    svc = service_name(worker)
    active = systemctl_is_active(worker)
    if action == "start" and active:
        log(f"SYSTEMCTL_NOOP action=start svc={svc} reason=already_active")
        return True
    if action == "stop" and not active:
        log(f"SYSTEMCTL_NOOP action=stop svc={svc} reason=already_inactive")
        return True
    cmd = ["sudo", "/bin/systemctl", action, svc]
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        log(f"SYSTEMCTL action={action} svc={svc} rc={p.returncode} stderr={p.stderr[-300:]}")
        return p.returncode == 0
    except Exception as exc:
        log(f"SYSTEMCTL_ERROR action={action} worker={worker} err={exc}")
        return False

def systemctl_is_active(worker):
    svc = service_name(worker)
    try:
        p = subprocess.run(["/bin/systemctl", "is-active", "--quiet", svc], text=True, capture_output=True, timeout=10)
        return p.returncode == 0
    except Exception as exc:
        log(f"SYSTEMCTL_IS_ACTIVE_ERROR worker={worker} err={exc}")
        return False

def active_worker_services() -> set[str]:
    return {worker for worker in WORKERS if systemctl_is_active(worker)}

def update_worker_state(worker_id, status, note=""):
    with state_file_lock(WORKERS_PATH):
        data = read_json(WORKERS_PATH, {"workers": []})
        found = False
        for w in data.get("workers", []):
            if w.get("id") == worker_id:
                if status == "IDLE" and str(w.get("status", "")).upper() == "RUNNING" and w.get("current_task"):
                    w["last_seen"] = now()
                    w["note"] = note
                    found = True
                    break
                w["status"] = status
                if status in {"IDLE", "SLEEPING", "STOPPED"}:
                    w["current_task"] = None
                else:
                    w["current_task"] = w.get("current_task")
                w["last_seen"] = now()
                w["note"] = note
                found = True
                break
        if not found:
            data.setdefault("workers", []).append({
                "id": worker_id,
                "role": "Auto worker",
                "status": status,
                "current_task": None,
                "last_seen": now(),
                "note": note
            })
        write_json(WORKERS_PATH, data)

def worker_lifecycle_snapshot() -> dict[str, list[dict[str, Any]]]:
    q = read_json(QUEUE_PATH, {"tasks": []})
    q, _changes = normalize_queue_payload(q)
    tasks = q.get("tasks", [])
    worker_tasks = [t for t in tasks if is_worker_eligible_task(t)]
    pending = [t for t in worker_tasks if normalize_status(t.get("status")) in PENDING_WORKER_STATUSES]
    claimed = [t for t in worker_tasks if normalize_status(t.get("status")) in CLAIMED_WORKER_STATUSES]
    return {
        "pending_tasks": pending,
        "active_tasks": claimed,
        "wake_tasks": claimed + pending,
    }

def choose_worker(title):
    text = str(title or "").lower()
    if any(x in text for x in ["dashboard", "panel", "ui", "frontend"]):
        return "worker-2"
    if any(x in text for x in ["service", "watcher", "deploy", "rollback", "lifecycle"]):
        return "worker-3"
    if any(x in text for x in ["quality", "test", "gate", "validation", "pipeline"]):
        return "worker-4"
    return "worker-1"

def max_parallel_workers() -> int:
    try:
        configured = int(cto_autonomous_delivery.policy().get("max_parallel_tasks") or 1)
    except Exception:
        configured = 1
    return max(1, min(len(WORKERS), configured))

def _select_workers_for_tasks(
    tasks: list[dict[str, Any]],
    max_workers: int,
    fallback_to_default: bool,
) -> list[str]:
    selected: list[str] = []

    def append_worker(worker_id: str) -> bool:
        chosen = worker_id if worker_id in WORKERS else ""
        if not chosen or chosen in selected:
            for fallback in WORKERS:
                if fallback not in selected:
                    chosen = fallback
                    break
        if not chosen or chosen in selected:
            return False
        selected.append(chosen)
        return len(selected) >= max_workers

    for status in WAKE_SELECTION_STATUSES:
        for task in tasks:
            if normalize_status(task.get("status")) != status:
                continue
            worker_id = task.get("assigned_worker")
            if worker_id in WORKERS:
                preferred = worker_id
            else:
                preferred = choose_worker(task.get("title") or task.get("id"))
            if append_worker(preferred):
                return selected
    if selected or not fallback_to_default:
        return selected
    return ["worker-1"]

def selected_workers_for_active_mode(fallback_to_default: bool = True) -> list[str]:
    snapshot = worker_lifecycle_snapshot()
    return _select_workers_for_tasks(snapshot["wake_tasks"], max_parallel_workers(), fallback_to_default)

def worker_wake_plan(active_services: set[str] | None = None) -> dict[str, Any]:
    snapshot = worker_lifecycle_snapshot()
    max_workers = max_parallel_workers()
    pending_count = len(snapshot["pending_tasks"])
    active_count = len(snapshot["active_tasks"])
    desired_worker_count = min(pending_count + active_count, max_workers)
    selected = _select_workers_for_tasks(
        snapshot["wake_tasks"],
        desired_worker_count,
        fallback_to_default=False,
    )
    awake = set(active_services) if active_services is not None else active_worker_services()
    selected_set = set(selected)
    workers_to_start = [worker for worker in selected if worker not in awake]
    workers_to_stop = [worker for worker in WORKERS if worker in awake and worker not in selected_set]
    return {
        "pending_worker_eligible_count": pending_count,
        "active_worker_eligible_count": active_count,
        "desired_worker_count": desired_worker_count,
        "awake_worker_count": len(awake),
        "selected_workers": selected,
        "workers_to_start": workers_to_start,
        "workers_to_stop": workers_to_stop,
        "parallel_limit": max_workers,
    }

def queue_counts():
    snapshot = worker_lifecycle_snapshot()
    pending = snapshot["pending_tasks"]
    active = snapshot["active_tasks"]
    running = [t for t in active if normalize_status(t.get("status")) == TASK_STATUS_RUNNING]
    return len(pending), len(running), len(pending) + len(active)

def should_sleep_workers(pending_count: int, active_count: int) -> bool:
    return pending_count == 0 and active_count == 0

def active_child_exists(tasks: list[dict[str, Any]], child_id: str | None) -> bool:
    if not child_id:
        return False
    for task in tasks:
        if task.get("id") != child_id:
            continue
        return normalize_status(task.get("status")) in ACTIVE_TASK_STATUSES
    return False

def child_allows_retry(tasks: list[dict[str, Any]], child_id: str | None) -> bool:
    if not child_id:
        return True
    retryable = {
        TASK_STATUS_FAILED,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_VALIDATION_FAILED,
        TASK_STATUS_PIPELINE_FAILED,
    }
    for task in tasks:
        if task.get("id") != child_id:
            continue
        if (
            normalize_status(task.get("status")) == TASK_STATUS_FAILED_RETRYABLE
            and (
                str(task.get("delivery_level") or "").upper() == "PR_CONFLICT"
                or str(task.get("deployment_status") or "").upper() == "MERGE_CONFLICT"
            )
        ):
            return True
        if (
            task.get("pull_request_url")
            or task.get("merge_blocked")
            or str(task.get("result") or "") == "repo_apply_pr_ready_pipeline_passed"
        ):
            return False
        return normalize_status(task.get("status")) in retryable
    return True

def backlog_dispatch_mode(status: str) -> str:
    if status == TASK_STATUS_PROPOSAL_DONE:
        return "apply"
    if status == TASK_STATUS_PROPOSAL_READY:
        return "validation"
    if status in {TASK_STATUS_VALIDATION_FAILED, TASK_STATUS_PIPELINE_FAILED}:
        return "repair"
    return "retry"

def backlog_description(parent: dict[str, Any], mode: str) -> str:
    parent_id = parent.get("id", "")
    status = normalize_status(parent.get("status"))
    title = parent.get("title") or parent_id
    report = parent.get("report_path") or parent.get("workspace") or "-"
    if mode == "validation":
        action = "Validate the proposal/workspace output and prepare concrete implementation or validation findings."
    elif mode == "repair":
        action = "Analyze the failed validation or pipeline evidence and prepare the smallest safe repair plan."
    else:
        action = "Retry the work in smaller scope and produce a proposal that can be validated."
    return (
        f"Backlog dispatcher child for parent {parent_id}. "
        f"Parent status: {status}. Parent title: {title}. Evidence: {report}. "
        f"{action} Work only in the isolated worker workspace. "
        "Do not mutate production, secrets, IAM, billing, DNS, firewall, token/private key/env values, database, or Google Ads."
    )

def task_text(task: dict[str, Any]) -> str:
    return "\n".join(str(task.get(key, "")) for key in ["title", "description", "raw_message"])


def children_by_parent(tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_parent: dict[str, list[dict[str, Any]]] = {}
    ids = {str(task.get("id") or "") for task in tasks if isinstance(task, dict)}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        child_id = str(task.get("id") or "")
        parent_ids = {
            str(task.get("parent_task_id") or ""),
            str(task.get("parent_task") or ""),
        }
        root_id = str(task.get("root_task_id") or "")
        if root_id and root_id in ids and root_id != child_id:
            parent_ids.add(root_id)
        for parent_id in parent_ids:
            if parent_id and parent_id != child_id:
                by_parent.setdefault(parent_id, []).append(task)
    return by_parent


def parent_progress_from_children(children: list[dict[str, Any]]) -> dict[str, Any] | None:
    statuses = [normalize_status(child.get("status")) for child in children]
    if any(status in ACTIVE_TASK_STATUSES for status in statuses):
        active_child = next(child for child in children if normalize_status(child.get("status")) in ACTIVE_TASK_STATUSES)
        mode = str(active_child.get("dispatcher_mode") or active_child.get("execution_mode") or "child").upper()
        return {
            "status": TASK_STATUS_RUNNING,
            "delivery_level": "REPO_APPLY_RUNNING" if "APPLY" in mode else "CHILD_RUNNING",
            "result": "child_task_in_progress",
            "active_child_task_id": active_child.get("id"),
        }
    if any(str(child.get("delivery_level") or "").upper() == "PR_READY" for child in children):
        child = next(child for child in children if str(child.get("delivery_level") or "").upper() == "PR_READY")
        return {
            "status": TASK_STATUS_READY_FOR_VALIDATION,
            "delivery_level": "PR_READY",
            "result": "child_pr_ready_for_finalizer",
            "active_child_task_id": child.get("id"),
        }
    if any(status == TASK_STATUS_READY_FOR_VALIDATION for status in statuses):
        child = next(child for child in children if normalize_status(child.get("status")) == TASK_STATUS_READY_FOR_VALIDATION)
        return {
            "status": TASK_STATUS_READY_FOR_VALIDATION,
            "delivery_level": TASK_STATUS_READY_FOR_VALIDATION,
            "result": "child_ready_for_validation",
            "active_child_task_id": child.get("id"),
        }
    if any(status == TASK_STATUS_PROPOSAL_DONE for status in statuses):
        child = next(child for child in children if normalize_status(child.get("status")) == TASK_STATUS_PROPOSAL_DONE)
        return {
            "status": TASK_STATUS_PROPOSAL_DONE,
            "delivery_level": TASK_STATUS_PROPOSAL_DONE,
            "result": "child_proposal_done",
            "active_child_task_id": child.get("id"),
        }
    if children and all(status in CHILD_FAILURE_STATUSES for status in statuses):
        child = children[-1]
        return {
            "status": TASK_STATUS_FAILED_RETRYABLE,
            "delivery_level": "CHILD_FAILED_RETRYABLE",
            "result": "child_task_failed_root_cause_required",
            "active_child_task_id": child.get("id"),
        }
    return None


def propagate_parent_progress(queue: dict[str, Any]) -> int:
    tasks = [task for task in queue.get("tasks", []) if isinstance(task, dict)]
    changed = 0
    for _pass in range(4):
        pass_changed = 0
        grouped = children_by_parent(tasks)
        by_id = {str(task.get("id") or ""): task for task in tasks}
        for parent_id, children in grouped.items():
            parent = by_id.get(parent_id)
            if not parent:
                continue
            if normalize_status(parent.get("status")) in PROGRESS_PROPAGATION_BLOCKED_STATUSES:
                continue
            progress = parent_progress_from_children(children)
            if not progress:
                continue
            if normalize_status(parent.get("status")) == progress["status"] and parent.get("delivery_level") == progress["delivery_level"]:
                continue
            parent["status"] = progress["status"]
            parent["delivery_level"] = progress["delivery_level"]
            parent["result"] = progress["result"]
            parent["active_child_task_id"] = progress.get("active_child_task_id")
            parent["parent_progress_propagated"] = True
            parent["worker_eligible"] = False
            parent["updated_at"] = now()
            pass_changed += 1
        changed += pass_changed
        if not pass_changed:
            break
    return changed

def is_repo_apply_candidate(task: dict[str, Any], tasks: list[dict[str, Any]]) -> bool:
    status = normalize_status(task.get("status"))
    retrying_apply_failure = (
        status == TASK_STATUS_FAILED_RETRYABLE
        and str(task.get("result") or "") == "child_task_failed_root_cause_required"
        and bool(task.get("workspace") or task.get("report_path"))
    )
    if status not in {TASK_STATUS_PROPOSAL_DONE, TASK_STATUS_DONE} and not retrying_apply_failure:
        return False
    if (
        str(task.get("delivery_level") or "").upper() == "PR_READY"
        or task.get("pull_request_url")
        or task.get("pull_request_number")
        or str(task.get("result") or "") == "repo_apply_pr_ready_pipeline_passed"
    ):
        return False
    if status == TASK_STATUS_DONE and (
        str(task.get("validation_status") or "").upper() != "PASS"
        or str(task.get("pipeline_status") or "").upper() != "PASS"
    ):
        return False
    if task.get("source") == BACKLOG_DISPATCHER_SOURCE:
        return False
    if task.get("production_deployed") or task.get("repo_applied") or task.get("branch_merged"):
        return False
    if task.get("approval_required") or status == TASK_STATUS_APPROVAL_REQUIRED:
        return False
    if worker_block_reason(task) and not retrying_apply_failure:
        return False
    child_id = task.get("repo_apply_child")
    if active_child_exists(tasks, child_id):
        return False
    if not child_allows_retry(tasks, child_id):
        return False
    attempts = int(task.get("repo_apply_attempts", 0) or 0)
    max_attempts = 3 if retrying_apply_failure else 2
    return attempts < max_attempts

def repo_apply_candidate(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for task in tasks:
        if is_repo_apply_candidate(task, tasks):
            return task
    return None

def mark_approval_required(task: dict[str, Any], findings: list[str]) -> None:
    task["status"] = TASK_STATUS_APPROVAL_REQUIRED
    task["worker_eligible"] = False
    task["approval_required"] = True
    task["approval_reason"] = "critical_infrastructure_operation"
    task["critical_operation_findings"] = findings
    task["updated_at"] = now()

def create_repo_apply_task(queue: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    parent_id = str(parent.get("id") or "TASK")
    title = parent.get("title") or parent_id
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    child_id = f"CTO-APPLY-{stamp}-{safe_id(parent_id)}"
    risk = normalize_risk(parent.get("risk") or parent.get("risk_level") or "medium")
    evidence = parent.get("workspace") or parent.get("report_path") or "-"
    child = {
        "id": child_id,
        "title": f"Apply: {str(title)[:90]}",
        "description": (
            f"Repo apply child for validated proposal {parent_id}. "
            f"Parent status: {normalize_status(parent.get('status'))}. Evidence: {evidence}. "
            "Worker must implement the smallest safe repo/app change in an isolated repo clone and branch, "
            "then create a PR after local gates pass. Do not deploy production. Do not touch secret/env/token/private key, "
            "IAM, billing, DNS, firewall, destructive database, or advertising platform live-write operations."
        ),
        "status": TASK_STATUS_PENDING,
        "source": BACKLOG_DISPATCHER_SOURCE,
        "parent_task": parent_id,
        "parent_task_id": parent_id,
        "proposal_workspace": parent.get("workspace", ""),
        "proposal_report_path": parent.get("report_path", ""),
        "risk": risk,
        "risk_level": risk,
        "assigned_worker": choose_worker(title),
        "worker_eligible": True,
        "dispatcher_mode": "apply",
        "execution_mode": "repo_apply",
        "repo_apply_allowed": True,
        "requires_pipeline_before_deploy": True,
        "created_at": now(),
        "updated_at": now(),
        "repo_applied": False,
        "branch_merged": False,
        "production_deployed": False,
        "validation_status": "PENDING",
        "pipeline_status": "NOT_RUN",
        "delivery_level": "REPO_APPLY_QUEUED",
    }
    queue.setdefault("tasks", []).append(child)
    parent["repo_apply_child"] = child_id
    parent["repo_apply_attempts"] = int(parent.get("repo_apply_attempts", 0) or 0) + 1
    parent["repo_apply_created_at"] = now()
    parent["updated_at"] = now()
    return child

def dispatcher_candidate(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    referenced_children = {task.get("backlog_dispatcher_child") for task in tasks if task.get("backlog_dispatcher_child")}
    for task in tasks:
        status = normalize_status(task.get("status"))
        if status not in BACKLOG_RECOVERABLE_STATUSES:
            continue
        if task.get("id") in referenced_children:
            continue
        if task.get("source") == BACKLOG_DISPATCHER_SOURCE:
            continue
        if task.get("parent_task") or task.get("parent_task_id"):
            continue
        if worker_block_reason(task):
            continue
        repo_child_id = task.get("repo_apply_child")
        if active_child_exists(tasks, repo_child_id):
            continue
        if not child_allows_retry(tasks, repo_child_id):
            continue
        child_id = task.get("backlog_dispatcher_child")
        if active_child_exists(tasks, child_id):
            continue
        if not child_allows_retry(tasks, child_id):
            continue
        retries = int(task.get("backlog_dispatcher_attempts", 0) or 0)
        if retries >= 2:
            continue
        return task
    return None

def ensure_autonomous_backlog_fallback(state_updates: dict[str, Any] | None = None) -> bool:
    state_updates = state_updates or {}
    try:
        payload = cto_autonomous_delivery.start_next_backlog(execute=True)
    except Exception as exc:
        update_system_state(
            **state_updates,
            backlog_dispatcher_last_result="autonomous_backlog_error",
            backlog_dispatcher_fallback_error=str(exc)[:300],
        )
        log(f"BACKLOG_DISPATCH autonomous_fallback_error err={exc}")
        return False

    status = str(payload.get("status") or "UNKNOWN")
    if payload.get("ok") and status == "BACKLOG_CONTINUATION_CREATED":
        child = payload.get("child_task") or {}
        update_system_state(
            **state_updates,
            backlog_dispatcher_last_result="autonomous_backlog_created",
            backlog_dispatcher_last_parent=payload.get("parent_task_id"),
            backlog_dispatcher_last_child=child.get("id"),
            backlog_dispatcher_last_mode="autonomous_backlog_continuation",
        )
        log(
            "BACKLOG_DISPATCH autonomous_fallback_created "
            f"parent={payload.get('parent_task_id')} child={child.get('id')}"
        )
        return True

    update_system_state(
        **state_updates,
        backlog_dispatcher_last_result=f"autonomous_backlog_{status.lower()}",
        backlog_dispatcher_fallback_ok=bool(payload.get("ok")),
    )
    log(f"BACKLOG_DISPATCH autonomous_fallback_noop status={status} ok={payload.get('ok')}")
    return False

def ensure_single_backlog_task() -> bool:
    queue = read_json(QUEUE_PATH, {"tasks": []})
    queue, _changes = normalize_queue_payload(queue)
    tasks = queue.setdefault("tasks", [])
    progress_changes = propagate_parent_progress(queue)
    worker_pending = [t for t in tasks if is_worker_eligible_task(t)]
    worker_active = [
        t
        for t in worker_pending
        if normalize_status(t.get("status")) in {"PENDING", "QUEUED", "ASSIGNED", "RUNNING"}
    ]
    max_workers = max_parallel_workers()
    available_slots = max(0, max_workers - len(worker_active))
    state_updates = {
        "backlog_dispatcher_active": True,
        "backlog_dispatcher_mode": "parallel" if max_workers > 1 else "single",
        "backlog_dispatcher_max_parallel_tasks": max_workers,
        "backlog_dispatcher_last_tick": now(),
        "backlog_dispatcher_worker_active": len(worker_active),
        "backlog_dispatcher_available_slots": available_slots,
    }
    root_cause = cto_autonomous_delivery.root_cause_mode_status(queue)
    if root_cause.get("active"):
        if progress_changes:
            write_json(QUEUE_PATH, queue)
        update_system_state(
            **state_updates,
            backlog_dispatcher_last_result="root_cause_mode_active",
            backlog_dispatcher_parent_progress_changes=progress_changes,
            backlog_dispatcher_root_cause=root_cause,
        )
        log(
            "BACKLOG_DISPATCH root_cause_mode_active "
            f"deploy_retry={len(root_cause.get('deploy_retry_task_ids', []))} "
            f"pipeline_failed={len(root_cause.get('pipeline_failed_child_ids', []))}"
        )
        return False
    if available_slots <= 0:
        if progress_changes:
            write_json(QUEUE_PATH, queue)
        update_system_state(
            **state_updates,
            backlog_dispatcher_last_result="worker_active",
            backlog_dispatcher_parent_progress_changes=progress_changes,
        )
        return False

    created_children: list[dict[str, str]] = []
    approval_parent_id = ""
    queue_changed = False

    def remember_child(parent_id: str, child: dict[str, Any], mode: str) -> None:
        created_children.append(
            {
                "parent": parent_id,
                "child": str(child.get("id") or ""),
                "mode": mode,
                "worker": str(child.get("assigned_worker") or ""),
            }
        )
        worker_active.append(child)

    while len(created_children) < available_slots:
        apply_parent = repo_apply_candidate(tasks)
        if apply_parent:
            evaluation = approval_required_payload(task_text(apply_parent))
            if evaluation["approval_required"]:
                mark_approval_required(apply_parent, evaluation["critical_operation_findings"])
                approval_parent_id = str(apply_parent.get("id") or "")
                queue_changed = True
                log(f"BACKLOG_DISPATCH repo_apply_approval_required parent={approval_parent_id}")
                continue
            child = create_repo_apply_task(queue, apply_parent)
            remember_child(str(apply_parent.get("id") or ""), child, "apply")
            queue_changed = True
            log(f"BACKLOG_DISPATCH repo_apply_created child={child.get('id')} parent={apply_parent.get('id')}")
            continue

        parent = dispatcher_candidate(tasks)
        if not parent:
            break

        parent_id = str(parent.get("id") or "TASK")
        mode = backlog_dispatch_mode(normalize_status(parent.get("status")))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        child_id = f"CTO-DISPATCH-{stamp}-{safe_id(parent_id)}"
        risk = normalize_risk(parent.get("risk") or parent.get("risk_level") or "medium")
        if risk in {"high", "critical"}:
            mark_approval_required(parent, ["risk_requires_approval"])
            approval_parent_id = parent_id
            queue_changed = True
            log(f"BACKLOG_DISPATCH approval_required parent={parent_id} risk={risk}")
            continue

        title = parent.get("title") or parent_id
        child = {
            "id": child_id,
            "title": f"{mode.title()}: {str(title)[:80]}",
            "description": backlog_description(parent, mode),
            "status": TASK_STATUS_PENDING,
            "source": BACKLOG_DISPATCHER_SOURCE,
            "parent_task": parent_id,
            "risk": risk,
            "risk_level": risk,
            "assigned_worker": choose_worker(title),
            "worker_eligible": True,
            "dispatcher_mode": mode,
            "created_at": now(),
            "updated_at": now(),
            "repo_applied": False,
            "production_deployed": False,
            "validation_status": "PENDING" if mode == "validation" else "NOT_READY",
            "pipeline_status": "NOT_RUN",
            "delivery_level": "BACKLOG_DISPATCH",
        }
        tasks.append(child)
        parent["backlog_dispatcher_child"] = child_id
        parent["backlog_dispatcher_attempts"] = int(parent.get("backlog_dispatcher_attempts", 0) or 0) + 1
        parent["backlog_dispatcher_last_mode"] = mode
        parent["updated_at"] = now()
        remember_child(parent_id, child, mode)
        queue_changed = True
        log(f"BACKLOG_DISPATCH created child={child_id} parent={parent_id} mode={mode}")

    if created_children:
        progress_changes += propagate_parent_progress(queue)
        write_json(QUEUE_PATH, queue)
        last_child = created_children[-1]
        result = "parallel_children_created"
        if len(created_children) == 1:
            result = "repo_apply_created" if last_child["mode"] == "apply" else "created"
        final_state_updates = {
            **state_updates,
            "backlog_dispatcher_last_result": result,
            "backlog_dispatcher_last_parent": last_child["parent"],
            "backlog_dispatcher_last_child": last_child["child"],
            "backlog_dispatcher_last_children": created_children,
            "backlog_dispatcher_created_count": len(created_children),
            "backlog_dispatcher_last_mode": last_child["mode"],
            "backlog_dispatcher_worker_active": len(worker_active),
            "backlog_dispatcher_available_slots": max(0, max_workers - len(worker_active)),
            "backlog_dispatcher_parent_progress_changes": progress_changes,
        }
        update_system_state(**final_state_updates)
        return True

    if queue_changed:
        progress_changes += propagate_parent_progress(queue)
        write_json(QUEUE_PATH, queue)
        update_system_state(
            **state_updates,
            backlog_dispatcher_last_result="approval_required",
            backlog_dispatcher_last_parent=approval_parent_id,
            backlog_dispatcher_parent_progress_changes=progress_changes,
        )
        return False

    if ensure_autonomous_backlog_fallback(state_updates):
        return True
    if progress_changes:
        write_json(QUEUE_PATH, queue)
    recoverable = sum(1 for t in tasks if normalize_status(t.get("status")) in BACKLOG_RECOVERABLE_STATUSES)
    update_system_state(
        **state_updates,
        backlog_dispatcher_last_result="no_recoverable_worker_eligible_task",
        backlog_dispatcher_recoverable_count=recoverable,
        backlog_dispatcher_parent_progress_changes=progress_changes,
    )
    return False

def validation_candidate_count() -> int:
    queue = read_json(QUEUE_PATH, {"tasks": []})
    queue, _changes = normalize_queue_payload(queue)
    return sum(
        1
        for task in queue.get("tasks", [])
        if normalize_status(task.get("status")) == TASK_STATUS_READY_FOR_VALIDATION
    )

def run_validation_engine() -> bool:
    try:
        p = subprocess.run(
            [
                "python3",
                "supervisor/task_validation_engine.py",
                "--limit",
                str(VALIDATION_BATCH_SIZE),
                "--pipeline-max-age-seconds",
                str(VALIDATION_PIPELINE_MAX_AGE_SECONDS),
                "--json",
            ],
            cwd=str(APP),
            text=True,
            capture_output=True,
            timeout=180,
        )
        changed = 0
        if p.stdout.strip():
            try:
                payload = json.loads(p.stdout)
                changed = int(payload.get("changed", 0) or 0)
            except Exception:
                changed = 0
        log(f"VALIDATION_ENGINE rc={p.returncode} changed={changed} stdout={p.stdout[-500:]} stderr={p.stderr[-500:]}")
        return p.returncode == 0 and changed > 0
    except Exception as exc:
        log(f"VALIDATION_ENGINE_ERROR {exc}")
        return False

def maybe_run_validation(last_validation: float) -> tuple[float, bool]:
    if validation_candidate_count() <= 0:
        return last_validation, False
    current = time.monotonic()
    if current - last_validation < VALIDATION_INTERVAL_SECONDS:
        return last_validation, False
    return current, run_validation_engine()

def run_delivery_finalizer() -> bool:
    try:
        p = subprocess.run(
            [
                "python3",
                "supervisor/cto_autonomous_delivery.py",
                "finalize-latest",
                "--execute",
                "--wait",
            ],
            cwd=str(APP),
            text=True,
            capture_output=True,
            timeout=1200,
        )
        status = "UNKNOWN"
        if p.stdout.strip():
            try:
                payload = json.loads(p.stdout)
                status = str(payload.get("status") or status)
            except Exception:
                status = "UNPARSEABLE"
        log(f"DELIVERY_FINALIZER rc={p.returncode} status={status} stdout={p.stdout[-500:]} stderr={p.stderr[-500:]}")
        return p.returncode == 0
    except Exception as exc:
        log(f"DELIVERY_FINALIZER_ERROR {exc}")
        return False

def maybe_run_delivery(last_delivery: float, active_worker_task_count: int) -> tuple[float, bool]:
    if active_worker_task_count > 0:
        return last_delivery, False
    current = time.monotonic()
    if current - last_delivery < DELIVERY_INTERVAL_SECONDS:
        return last_delivery, False
    return current, run_delivery_finalizer()

def dispatch():
    try:
        p = subprocess.run(
            ["python3", "supervisor/supervisor_cli.py", "dispatch"],
            cwd=str(APP),
            text=True,
            capture_output=True,
            timeout=30,
        )
        log(f"DISPATCH rc={p.returncode} stdout={p.stdout[-500:]} stderr={p.stderr[-500:]}")
        return p.returncode == 0
    except Exception as exc:
        log(f"DISPATCH_ERROR {exc}")
        return False

def sleep_now():
    log("SLEEP_NOW requested")
    for w in WORKERS:
        update_worker_state(w, "SLEEPING", "queue_empty_sleep_mode")
        systemctl("stop", w)
    update_system_state(
        worker_sleep_wake_implemented=True,
        worker_fleet_mode="SLEEPING"
    )
    return {"ok": True, "mode": "SLEEPING"}

def wake_now():
    plan = worker_wake_plan()
    selected = set(plan["selected_workers"])
    max_workers = int(plan["parallel_limit"])
    log(
        "WAKE_NOW requested "
        f"pending={plan['pending_worker_eligible_count']} "
        f"active={plan['active_worker_eligible_count']} "
        f"awake={plan['awake_worker_count']} "
        f"desired={plan['desired_worker_count']} "
        f"selected={','.join(plan['selected_workers'])}"
    )
    if not selected:
        for w in WORKERS:
            update_worker_state(w, "SLEEPING", "wake_plan_no_worker_eligible_work")
        for w in plan["workers_to_stop"]:
            systemctl("stop", w)
        update_system_state(
            worker_sleep_wake_implemented=True,
            worker_fleet_mode="SLEEPING",
            worker_single_mode_active=False,
            worker_parallel_mode_active=False,
            worker_parallel_limit=max_workers,
            worker_single_mode_selected=[],
            worker_lifecycle_pending_count=plan["pending_worker_eligible_count"],
            worker_lifecycle_active_count=plan["active_worker_eligible_count"],
            worker_lifecycle_awake_count=plan["awake_worker_count"],
            worker_lifecycle_desired_count=plan["desired_worker_count"],
            worker_lifecycle_workers_to_start=[],
        )
        return {
            "ok": True,
            "mode": "SLEEPING",
            "selected_workers": [],
            "workers_to_start": [],
            "workers_to_stop": plan["workers_to_stop"],
            "parallel_limit": max_workers,
            "pending_worker_eligible_count": plan["pending_worker_eligible_count"],
            "active_worker_eligible_count": plan["active_worker_eligible_count"],
            "desired_worker_count": plan["desired_worker_count"],
            "awake_worker_count": plan["awake_worker_count"],
        }
    for w in WORKERS:
        if w in selected:
            update_worker_state(w, "IDLE", "woken_by_lifecycle_active_mode")
        else:
            update_worker_state(w, "SLEEPING", "wake_plan_not_selected")
    dispatch()
    for w in plan["workers_to_start"]:
        systemctl("start", w)
    for w in plan["workers_to_stop"]:
        systemctl("stop", w)
    update_system_state(
        worker_sleep_wake_implemented=True,
        worker_fleet_mode="AWAKE_PARALLEL" if max_workers > 1 else "AWAKE_SINGLE",
        worker_single_mode_active=max_workers == 1,
        worker_parallel_mode_active=max_workers > 1,
        worker_parallel_limit=max_workers,
        worker_single_mode_selected=sorted(selected),
        worker_lifecycle_pending_count=plan["pending_worker_eligible_count"],
        worker_lifecycle_active_count=plan["active_worker_eligible_count"],
        worker_lifecycle_awake_count=plan["awake_worker_count"],
        worker_lifecycle_desired_count=plan["desired_worker_count"],
        worker_lifecycle_workers_to_start=plan["workers_to_start"],
    )
    return {
        "ok": True,
        "mode": "AWAKE_PARALLEL" if max_workers > 1 else "AWAKE_SINGLE",
        "selected_workers": sorted(selected),
        "workers_to_start": plan["workers_to_start"],
        "workers_to_stop": plan["workers_to_stop"],
        "parallel_limit": max_workers,
        "pending_worker_eligible_count": plan["pending_worker_eligible_count"],
        "active_worker_eligible_count": plan["active_worker_eligible_count"],
        "desired_worker_count": plan["desired_worker_count"],
        "awake_worker_count": plan["awake_worker_count"],
    }

def update_system_state(**updates):
    data = read_json(SYSTEM_STATE_PATH, {})
    data.update(updates)
    write_json(SYSTEM_STATE_PATH, data)

def daemon():
    log("LIFECYCLE_DAEMON started")
    idle_cycles = 0
    last_validation = 0.0
    last_delivery = 0.0
    update_system_state(worker_lifecycle_daemon_active=True)

    while True:
        pending, running, active = queue_counts()
        last_validation, validation_changed = maybe_run_validation(last_validation)
        if validation_changed:
            pending, running, active = queue_counts()
        last_delivery, _delivery_changed = maybe_run_delivery(last_delivery, active)

        if active < max_parallel_workers():
            created = ensure_single_backlog_task()
            if created:
                pending, running, active = queue_counts()

        if pending > 0:
            idle_cycles = 0
            log(f"QUEUE_HAS_PENDING pending={pending}; waking workers")
            wake_now()

        elif should_sleep_workers(pending, active):
            idle_cycles += 1
            log(f"QUEUE_EMPTY idle_cycles={idle_cycles}")
            if idle_cycles >= SLEEP_AFTER_IDLE_CYCLES:
                state = read_json(SYSTEM_STATE_PATH, {})
                if state.get("worker_fleet_mode") == "SLEEPING":
                    log("QUEUE_EMPTY workers_already_sleeping")
                else:
                    sleep_now()
                idle_cycles = SLEEP_AFTER_IDLE_CYCLES
        else:
            idle_cycles = 0
            log(f"QUEUE_ACTIVE running={running}")

        time.sleep(POLL_SECONDS)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["sleep-now", "wake-now", "dispatch", "daemon", "status"])
    args = parser.parse_args()

    if args.command == "sleep-now":
        print(json.dumps(sleep_now(), indent=2, ensure_ascii=False))
    elif args.command == "wake-now":
        print(json.dumps(wake_now(), indent=2, ensure_ascii=False))
    elif args.command == "dispatch":
        print(json.dumps({"ok": dispatch()}, indent=2, ensure_ascii=False))
    elif args.command == "status":
        pending, running, active = queue_counts()
        print(json.dumps({
            "ok": True,
            "pending": pending,
            "running": running,
            "active": active,
            "workers": read_json(WORKERS_PATH, {"workers": []})
        }, indent=2, ensure_ascii=False))
    elif args.command == "daemon":
        daemon()

if __name__ == "__main__":
    main()
