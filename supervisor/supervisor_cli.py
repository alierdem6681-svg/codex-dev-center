#!/usr/bin/env python3
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

try:
    from .memory_os_context import task_is_memory_os
    from .state_file_lock import state_file_lock
    from .task_status_constants import (
        ACTIVE_TASK_STATUSES,
        TASK_STATUS_ASSIGNED,
        TASK_STATUS_DONE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PENDING,
        TASK_STATUS_QUEUED,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_RUNNING,
        atomic_write_json,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_risk,
        normalize_status,
    )
except ImportError:
    from memory_os_context import task_is_memory_os
    from state_file_lock import state_file_lock
    from task_status_constants import (
        ACTIVE_TASK_STATUSES,
        TASK_STATUS_ASSIGNED,
        TASK_STATUS_DONE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PENDING,
        TASK_STATUS_QUEUED,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_RUNNING,
        atomic_write_json,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_risk,
        normalize_status,
    )

APP_DIR = Path("/opt/codex-dev-center")
STATE_DIR = APP_DIR / "state"
LOG_DIR = APP_DIR / "logs"
REPORT_DIR = APP_DIR / "reports"

STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

try:
    DISPATCH_STALE_CLAIM_SECONDS = max(1, int(os.environ.get("CODEX_DISPATCH_STALE_CLAIM_SECONDS", "1800")))
except ValueError:
    DISPATCH_STALE_CLAIM_SECONDS = 1800

def now():
    return datetime.now(timezone.utc).isoformat()

def parse_iso_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default

def stale_claim_started_at(task):
    for key in ("claimed_at", "assigned_at", "started_at", "updated_at", "created_at"):
        parsed = parse_iso_datetime(task.get(key))
        if parsed is not None:
            return parsed
    return None

def worker_actively_owns_task(task, workers_by_id):
    task_id = str(task.get("id") or "")
    worker_id = str(task.get("worker_id") or task.get("assigned_worker") or "")
    worker = workers_by_id.get(worker_id)
    if not worker:
        return False
    status = str(worker.get("status") or "").strip().upper()
    current_task = str(worker.get("current_task") or "")
    return current_task == task_id and status in {"ASSIGNED", "RUNNING", "REVIEWING"}

def reconcile_stale_dispatch_claims(queue, workers, stale_seconds=None):
    stale_seconds = positive_int(stale_seconds, DISPATCH_STALE_CLAIM_SECONDS)
    workers_by_id = {str(w.get("id") or ""): w for w in workers.get("workers", [])}
    current_time = datetime.now(timezone.utc)
    current_iso = current_time.isoformat()
    requeued = []
    terminal = []

    for task in queue.get("tasks", []):
        status = normalize_status(task.get("status"))
        if status not in {TASK_STATUS_ASSIGNED, TASK_STATUS_RUNNING}:
            continue
        if not is_worker_eligible_task(task):
            continue
        if worker_actively_owns_task(task, workers_by_id):
            continue

        started_at = stale_claim_started_at(task)
        if started_at is None:
            continue
        age_seconds = max(0, int((current_time - started_at).total_seconds()))
        if age_seconds < stale_seconds:
            continue

        task_id = str(task.get("id") or "")
        previous_worker = str(task.get("worker_id") or task.get("assigned_worker") or "")
        attempt = positive_int(task.get("attempt"), 1)
        max_attempts = positive_int(task.get("max_attempts"), attempt)
        if max_attempts < attempt:
            max_attempts = attempt

        worker = workers_by_id.get(previous_worker)
        if worker and str(worker.get("current_task") or "") == task_id:
            worker_status = str(worker.get("status") or "").strip().upper()
            if worker_status not in {"ASSIGNED", "RUNNING", "REVIEWING"}:
                worker["current_task"] = None
                worker["last_seen"] = current_iso
                worker["note"] = f"stale_claim_reconciled:{task_id}"

        task["last_error_code"] = "stale_claim_timeout"
        task["previous_worker_id"] = previous_worker
        task["stale_claim_detected_at"] = current_iso
        task["claimed_at"] = None
        task["started_at"] = None
        task["assigned_worker"] = None
        task["worker_id"] = ""
        task["updated_at"] = current_iso

        if attempt < max_attempts:
            task["attempt"] = attempt + 1
            task["max_attempts"] = max_attempts
            task["status"] = TASK_STATUS_PENDING
            task["delivery_level"] = "RETRY_DISPATCH_PENDING"
            task["result"] = "stale_claim_timeout_retry_scheduled"
            task["dispatch_requeue_reason"] = "stale_claim_timeout"
            task["finished_at"] = None
            requeued.append(
                {
                    "task": task_id,
                    "previous_worker": previous_worker,
                    "attempt": task["attempt"],
                    "max_attempts": max_attempts,
                    "age_seconds": age_seconds,
                }
            )
            continue

        task["attempt"] = attempt
        task["max_attempts"] = max_attempts
        task["status"] = TASK_STATUS_FAILED_TIMEOUT
        task["delivery_level"] = TASK_STATUS_FAILED_TIMEOUT
        task["result"] = "stale_claim_timeout_max_attempts_reached"
        task["finished_at"] = current_iso
        terminal.append(
            {
                "task": task_id,
                "previous_worker": previous_worker,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "age_seconds": age_seconds,
            }
        )

    return requeued, terminal

def read_json(path, default):
    try:
        p = Path(path)
        if not p.exists():
            return default
        return json.loads(p.read_text())
    except Exception:
        return default

def write_json(path, data):
    atomic_write_json(Path(path), data)

def worker_state_transaction_lock_path():
    return STATE_DIR / "worker_state_transaction"

def bind_memory_os_dispatch_context(task):
    if not task_is_memory_os(task):
        return
    root_task_id = str(
        task.get("memory_os_scope_root_task_id")
        or task.get("root_task_id")
        or task.get("parent_task_id")
        or task.get("id")
        or ""
    )
    if root_task_id:
        task["memory_os_scope_root_task_id"] = root_task_id
        task.setdefault("root_task_id", root_task_id)
    task["dispatch_context_domain"] = "memory_os"
    task["memory_os_dispatch_context_bound"] = True

def log(msg):
    with open(LOG_DIR / "supervisor.log", "a", encoding="utf-8") as f:
        f.write(f"{now()} {msg}\n")

def status(_args):
    system_state = read_json(STATE_DIR / "system_state.json", {})
    workers = read_json(STATE_DIR / "workers.json", {"workers": []})
    queue = read_json(STATE_DIR / "task_queue.json", {"tasks": []})
    approvals = read_json(STATE_DIR / "approvals.json", {"approvals": []})

    result = {
        "ok": True,
        "system_phase": system_state.get("phase", "unknown"),
        "production_deploy_enabled": system_state.get("production_deploy_enabled", False),
        "dashboard_live_update_enabled": system_state.get("dashboard_live_update_enabled", False),
        "workers_total": len(workers.get("workers", [])),
        "workers": workers.get("workers", []),
        "tasks_total": len(queue.get("tasks", [])),
        "pending_tasks": len([t for t in queue.get("tasks", []) if normalize_status(t.get("status")) in ACTIVE_TASK_STATUSES]),
        "approvals_pending": len([a for a in approvals.get("approvals", []) if a.get("status") == "PENDING"]),
        "updated_at": now()
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))

def add_task(args):
    queue_path = STATE_DIR / "task_queue.json"
    queue = read_json(queue_path, {"tasks": []})
    tasks = queue.setdefault("tasks", [])

    task_id = f"TASK-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    task = {
        "id": task_id,
        "title": args.title,
        "description": args.description or args.title,
        "status": TASK_STATUS_PENDING,
        "assigned_worker": None,
        "risk": normalize_risk(args.risk),
        "risk_level": normalize_risk(args.risk),
        "source": args.source,
        "priority": args.priority,
        "worker_eligible": args.source != "telegram" and normalize_risk(args.risk) not in {"high", "critical"},
        "created_at": now(),
        "updated_at": now()
    }
    tasks.append(task)
    queue, _changes = normalize_queue_payload(queue)
    write_json(queue_path, queue)
    log(f"TASK_ADDED {task_id} {args.title}")
    print(json.dumps({"ok": True, "task": task}, indent=2, ensure_ascii=False))

def set_worker(args):
    workers_path = STATE_DIR / "workers.json"
    data = read_json(workers_path, {"workers": []})
    found = False
    for w in data.get("workers", []):
        if w.get("id") == args.worker:
            w["status"] = args.status
            w["current_task"] = args.current_task
            w["last_seen"] = now()
            found = True
            break
    if not found:
        print(json.dumps({"ok": False, "error": "worker_not_found"}, indent=2, ensure_ascii=False))
        sys.exit(1)
    write_json(workers_path, data)
    log(f"WORKER_SET {args.worker} {args.status} {args.current_task or ''}")
    print(json.dumps({"ok": True, "worker": args.worker, "status": args.status}, indent=2, ensure_ascii=False))

def dispatch(_args):
    workers_path = STATE_DIR / "workers.json"
    queue_path = STATE_DIR / "task_queue.json"

    with state_file_lock(worker_state_transaction_lock_path()):
        with state_file_lock(queue_path):
            with state_file_lock(workers_path):
                workers = read_json(workers_path, {"workers": []})
                queue = read_json(queue_path, {"tasks": []})

                stale_requeued, stale_terminal = reconcile_stale_dispatch_claims(queue, workers)
                idle_workers = [
                    w
                    for w in workers.get("workers", [])
                    if w.get("status") in ("IDLE", "READY") and not w.get("current_task")
                ]
                idle_by_id = {str(w.get("id") or ""): w for w in idle_workers}
                queue, _changes = normalize_queue_payload(queue)
                dispatchable_statuses = {TASK_STATUS_PENDING, TASK_STATUS_QUEUED}
                pending_tasks = [
                    t
                    for t in queue.get("tasks", [])
                    if is_worker_eligible_task(t) and normalize_status(t.get("status")) in dispatchable_statuses
                ]

                assignments = []
                assigned_task_ids = set()

                def assign(worker, task):
                    claim_time = now()
                    worker["status"] = TASK_STATUS_ASSIGNED
                    worker["current_task"] = task["id"]
                    worker["last_seen"] = claim_time
                    task["status"] = TASK_STATUS_ASSIGNED
                    task["assigned_worker"] = worker["id"]
                    task["worker_id"] = worker["id"]
                    task["updated_at"] = claim_time
                    bind_memory_os_dispatch_context(task)
                    assigned_task_ids.add(task["id"])
                    assignments.append({"worker": worker["id"], "task": task["id"]})

                for task in pending_tasks:
                    preferred = str(task.get("assigned_worker") or "")
                    worker = idle_by_id.get(preferred)
                    if not worker:
                        continue
                    assign(worker, task)
                    idle_by_id.pop(preferred, None)

                remaining_idle = [w for w in idle_workers if str(w.get("id") or "") in idle_by_id]
                for task in pending_tasks:
                    if task.get("id") in assigned_task_ids:
                        continue
                    if not remaining_idle:
                        break
                    assign(remaining_idle.pop(0), task)

                write_json(queue_path, queue)
                write_json(workers_path, workers)

    for item in stale_requeued:
        log(
            f"DISPATCH_STALE_REQUEUED task={item['task']} previous_worker={item['previous_worker']} "
            f"attempt={item['attempt']}/{item['max_attempts']} age_seconds={item['age_seconds']}"
        )

    for item in stale_terminal:
        log(
            f"DISPATCH_STALE_TERMINAL task={item['task']} previous_worker={item['previous_worker']} "
            f"attempt={item['attempt']}/{item['max_attempts']} age_seconds={item['age_seconds']}"
        )

    for item in assignments:
        log(f"DISPATCH worker={item['worker']} task={item['task']}")

    print(
        json.dumps(
            {
                "ok": True,
                "assignments": assignments,
                "stale_requeued": stale_requeued,
                "stale_terminal": stale_terminal,
            },
            indent=2,
            ensure_ascii=False,
        )
    )

def completion_target_status(task):
    if task.get("validation_status") == "PASS" and task.get("pipeline_status") == "PASS":
        return TASK_STATUS_DONE, "manual_completion_validated_pipeline_passed"
    return TASK_STATUS_READY_FOR_VALIDATION, "manual_completion_requires_validation_pipeline_pass"

def complete_task(args):
    queue_path = STATE_DIR / "task_queue.json"
    workers_path = STATE_DIR / "workers.json"
    queue = read_json(queue_path, {"tasks": []})
    workers = read_json(workers_path, {"workers": []})

    found = False
    completed_status = None
    for t in queue.get("tasks", []):
        if t.get("id") == args.task_id:
            target_status, default_result = completion_target_status(t)
            t["status"] = target_status
            t["result"] = args.result if target_status == TASK_STATUS_DONE else default_result
            t["delivery_level"] = target_status
            if target_status != TASK_STATUS_DONE:
                t["validation_status"] = t.get("validation_status") or "PENDING"
                t["pipeline_status"] = t.get("pipeline_status") or "NOT_RUN"
            t["updated_at"] = now()
            completed_status = target_status
            found = True
            break

    for w in workers.get("workers", []):
        if w.get("current_task") == args.task_id:
            w["status"] = "IDLE"
            w["current_task"] = None
            w["last_seen"] = now()

    write_json(queue_path, queue)
    write_json(workers_path, workers)
    log(f"TASK_COMPLETION_RECORDED {args.task_id} {completed_status} {args.result}")

    if not found:
        print(json.dumps({"ok": False, "error": "task_not_found"}, indent=2, ensure_ascii=False))
        sys.exit(1)

    print(json.dumps({"ok": True, "task_id": args.task_id, "status": completed_status}, indent=2, ensure_ascii=False))

def main():
    parser = argparse.ArgumentParser(description="Codex Dev Center Supervisor CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status")
    p.set_defaults(func=status)

    p = sub.add_parser("add-task")
    p.add_argument("--title", required=True)
    p.add_argument("--description", default="")
    p.add_argument("--risk", default="low", choices=["low", "medium", "high", "critical"])
    p.add_argument("--source", default="local")
    p.add_argument("--priority", default="normal")
    p.set_defaults(func=add_task)

    p = sub.add_parser("set-worker")
    p.add_argument("--worker", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--current-task", default=None)
    p.set_defaults(func=set_worker)

    p = sub.add_parser("dispatch")
    p.set_defaults(func=dispatch)

    p = sub.add_parser("complete-task")
    p.add_argument("--task-id", required=True)
    p.add_argument("--result", default="completed")
    p.set_defaults(func=complete_task)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
