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
    from .task_status_constants import (
        ACTIVE_TASK_STATUSES,
        TASK_STATUS_FAILED,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PENDING,
        TASK_STATUS_PIPELINE_FAILED,
        TASK_STATUS_PROPOSAL_DONE,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_VALIDATION_FAILED,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_risk,
        normalize_status,
        worker_block_reason,
    )
except ImportError:
    from task_status_constants import (
        ACTIVE_TASK_STATUSES,
        TASK_STATUS_FAILED,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PENDING,
        TASK_STATUS_PIPELINE_FAILED,
        TASK_STATUS_PROPOSAL_DONE,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_VALIDATION_FAILED,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_risk,
        normalize_status,
        worker_block_reason,
    )

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
WORKERS_PATH = STATE / "workers.json"
QUEUE_PATH = STATE / "task_queue.json"
SYSTEM_STATE_PATH = STATE / "system_state.json"

WORKERS = ["worker-1", "worker-2", "worker-3", "worker-4"]
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
    TASK_STATUS_READY_FOR_VALIDATION,
    TASK_STATUS_VALIDATION_FAILED,
}

def now():
    return datetime.now(timezone.utc).isoformat()

def log(msg):
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "lifecycle.log").open("a", encoding="utf-8") as f:
        f.write(f"{now()} {msg}\n")

def read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as exc:
        log(f"READ_JSON_ERROR path={path} err={exc}")
    return default

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    tmp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)

def safe_id(value):
    out = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(value or "TASK"))
    return out[:90] or "TASK"

def service_name(worker):
    return f"codex-{worker}"

def systemctl(action, worker):
    svc = service_name(worker)
    cmd = ["sudo", "/bin/systemctl", action, svc]
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        log(f"SYSTEMCTL action={action} svc={svc} rc={p.returncode} stderr={p.stderr[-300:]}")
        return p.returncode == 0
    except Exception as exc:
        log(f"SYSTEMCTL_ERROR action={action} worker={worker} err={exc}")
        return False

def update_worker_state(worker_id, status, note=""):
    data = read_json(WORKERS_PATH, {"workers": []})
    found = False
    for w in data.get("workers", []):
        if w.get("id") == worker_id:
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

def queue_counts():
    q = read_json(QUEUE_PATH, {"tasks": []})
    q, _changes = normalize_queue_payload(q)
    tasks = q.get("tasks", [])
    worker_tasks = [t for t in tasks if is_worker_eligible_task(t)]
    pending = [t for t in worker_tasks if normalize_status(t.get("status")) in ("PENDING", "QUEUED", "ASSIGNED")]
    running = [t for t in worker_tasks if normalize_status(t.get("status")) == "RUNNING"]
    active = pending + running
    return len(pending), len(running), len(active)

def choose_worker(title):
    text = str(title or "").lower()
    if any(x in text for x in ["dashboard", "panel", "ui", "frontend"]):
        return "worker-2"
    if any(x in text for x in ["service", "watcher", "deploy", "rollback", "lifecycle"]):
        return "worker-3"
    if any(x in text for x in ["quality", "test", "gate", "validation", "pipeline"]):
        return "worker-4"
    return "worker-1"

def selected_workers_for_single_mode() -> list[str]:
    queue = read_json(QUEUE_PATH, {"tasks": []})
    queue, _changes = normalize_queue_payload(queue)
    tasks = [
        task
        for task in queue.get("tasks", [])
        if is_worker_eligible_task(task) and normalize_status(task.get("status")) in {"PENDING", "QUEUED", "ASSIGNED", "RUNNING"}
    ]
    for status in ["RUNNING", "ASSIGNED", "PENDING", "QUEUED"]:
        for task in tasks:
            if normalize_status(task.get("status")) != status:
                continue
            worker_id = task.get("assigned_worker")
            if worker_id in WORKERS:
                return [worker_id]
            return [choose_worker(task.get("title") or task.get("id"))]
    return ["worker-1"]

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
        return normalize_status(task.get("status")) in retryable
    return True

def backlog_dispatch_mode(status: str) -> str:
    if status in {TASK_STATUS_PROPOSAL_DONE, TASK_STATUS_PROPOSAL_READY, TASK_STATUS_READY_FOR_VALIDATION}:
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
        "Do not mutate production, secrets, IAM, billing, DNS, firewall, credentials, database, or Google Ads."
    )

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

def ensure_single_backlog_task() -> bool:
    queue = read_json(QUEUE_PATH, {"tasks": []})
    queue, _changes = normalize_queue_payload(queue)
    tasks = queue.setdefault("tasks", [])
    worker_pending = [t for t in tasks if is_worker_eligible_task(t)]
    worker_active = [
        t
        for t in worker_pending
        if normalize_status(t.get("status")) in {"PENDING", "QUEUED", "ASSIGNED", "RUNNING"}
    ]
    state_updates = {
        "backlog_dispatcher_active": True,
        "backlog_dispatcher_mode": "single",
        "backlog_dispatcher_last_tick": now(),
        "backlog_dispatcher_worker_active": len(worker_active),
    }
    if worker_active:
        update_system_state(**state_updates, backlog_dispatcher_last_result="worker_active")
        return False

    parent = dispatcher_candidate(tasks)
    if not parent:
        recoverable = sum(1 for t in tasks if normalize_status(t.get("status")) in BACKLOG_RECOVERABLE_STATUSES)
        update_system_state(
            **state_updates,
            backlog_dispatcher_last_result="no_recoverable_worker_eligible_task",
            backlog_dispatcher_recoverable_count=recoverable,
        )
        return False

    parent_id = str(parent.get("id") or "TASK")
    mode = backlog_dispatch_mode(normalize_status(parent.get("status")))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    child_id = f"CTO-DISPATCH-{stamp}-{safe_id(parent_id)}"
    risk = normalize_risk(parent.get("risk") or parent.get("risk_level") or "medium")
    if risk in {"high", "critical"}:
        update_system_state(**state_updates, backlog_dispatcher_last_result="approval_required")
        return False

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
    write_json(QUEUE_PATH, queue)
    update_system_state(
        **state_updates,
        backlog_dispatcher_last_result="created",
        backlog_dispatcher_last_parent=parent_id,
        backlog_dispatcher_last_child=child_id,
        backlog_dispatcher_last_mode=mode,
    )
    log(f"BACKLOG_DISPATCH created child={child_id} parent={parent_id} mode={mode}")
    return True

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
    selected = set(selected_workers_for_single_mode())
    log(f"WAKE_NOW requested selected={','.join(sorted(selected))}")
    for w in WORKERS:
        if w in selected:
            systemctl("start", w)
            update_worker_state(w, "IDLE", "woken_by_lifecycle_single_mode")
        else:
            update_worker_state(w, "SLEEPING", "single_mode_not_selected")
            systemctl("stop", w)
    dispatch()
    update_system_state(
        worker_sleep_wake_implemented=True,
        worker_fleet_mode="AWAKE_SINGLE",
        worker_single_mode_active=True,
        worker_single_mode_selected=sorted(selected),
    )
    return {"ok": True, "mode": "AWAKE_SINGLE", "selected_workers": sorted(selected)}

def update_system_state(**updates):
    data = read_json(SYSTEM_STATE_PATH, {})
    data.update(updates)
    write_json(SYSTEM_STATE_PATH, data)

def daemon():
    log("LIFECYCLE_DAEMON started")
    idle_cycles = 0
    update_system_state(worker_lifecycle_daemon_active=True)

    while True:
        pending, running, active = queue_counts()
        if active == 0:
            created = ensure_single_backlog_task()
            if created:
                pending, running, active = queue_counts()

        if pending > 0:
            idle_cycles = 0
            log(f"QUEUE_HAS_PENDING pending={pending}; waking workers")
            wake_now()

        elif active == 0:
            idle_cycles += 1
            log(f"QUEUE_EMPTY idle_cycles={idle_cycles}")
            if idle_cycles >= SLEEP_AFTER_IDLE_CYCLES:
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
