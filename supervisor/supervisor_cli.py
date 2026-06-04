#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

try:
    from .task_status_constants import (
        ACTIVE_TASK_STATUSES,
        TASK_STATUS_ASSIGNED,
        TASK_STATUS_DONE,
        TASK_STATUS_PENDING,
        TASK_STATUS_QUEUED,
        TASK_STATUS_READY_FOR_VALIDATION,
        atomic_write_json,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_risk,
        normalize_status,
    )
    from .worker_dispatch import assign_tasks_to_idle_workers, load_worker_profiles
except ImportError:
    from task_status_constants import (
        ACTIVE_TASK_STATUSES,
        TASK_STATUS_ASSIGNED,
        TASK_STATUS_DONE,
        TASK_STATUS_PENDING,
        TASK_STATUS_QUEUED,
        TASK_STATUS_READY_FOR_VALIDATION,
        atomic_write_json,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_risk,
        normalize_status,
    )
    from worker_dispatch import assign_tasks_to_idle_workers, load_worker_profiles

APP_DIR = Path("/opt/codex-dev-center")
STATE_DIR = APP_DIR / "state"
LOG_DIR = APP_DIR / "logs"
REPORT_DIR = APP_DIR / "reports"

STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

def now():
    return datetime.now(timezone.utc).isoformat()

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

    workers = read_json(workers_path, {"workers": []})
    queue = read_json(queue_path, {"tasks": []})

    queue, _changes = normalize_queue_payload(queue)
    dispatchable_statuses = {TASK_STATUS_PENDING, TASK_STATUS_QUEUED}
    pending_tasks = [
        t
        for t in queue.get("tasks", [])
        if is_worker_eligible_task(t) and normalize_status(t.get("status")) in dispatchable_statuses
    ]

    assignments = []
    profiles = load_worker_profiles(STATE_DIR.parent)
    for worker, task in assign_tasks_to_idle_workers(workers.get("workers", []), pending_tasks, profiles):
        worker["status"] = TASK_STATUS_ASSIGNED
        worker["current_task"] = task["id"]
        worker["last_seen"] = now()
        task["status"] = TASK_STATUS_ASSIGNED
        task["assigned_worker"] = worker["id"]
        task["updated_at"] = now()
        assignments.append({"worker": worker["id"], "task": task["id"]})

    write_json(workers_path, workers)
    write_json(queue_path, queue)

    for item in assignments:
        log(f"DISPATCH worker={item['worker']} task={item['task']}")

    print(json.dumps({"ok": True, "assignments": assignments}, indent=2, ensure_ascii=False))

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
