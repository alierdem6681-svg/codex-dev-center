#!/usr/bin/env python3
import argparse
import json
import os
import time
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
WORKERS_PATH = STATE / "workers.json"
QUEUE_PATH = STATE / "task_queue.json"
SYSTEM_STATE_PATH = STATE / "system_state.json"

WORKERS = ["worker-1", "worker-2", "worker-3", "worker-4"]
POLL_SECONDS = 5
SLEEP_AFTER_IDLE_CYCLES = 4
ACTIVE_TASK_STATUSES = {"PENDING", "QUEUED", "ASSIGNED", "RUNNING"}
APPROVAL_RISKS = {"HIGH", "CRITICAL"}

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
            w["current_task"] = None if status == "SLEEPING" else w.get("current_task")
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
    tasks = q.get("tasks", [])
    worker_tasks = [t for t in tasks if is_worker_eligible_task(t)]
    pending = [t for t in worker_tasks if str(t.get("status", "")).upper() in ("PENDING", "QUEUED", "ASSIGNED")]
    running = [t for t in worker_tasks if str(t.get("status", "")).upper() == "RUNNING"]
    active = pending + running
    return len(pending), len(running), len(active)

def is_worker_eligible_task(task):
    status = str(task.get("status", "")).upper()
    source = str(task.get("source", "")).lower()
    risk = str(task.get("risk") or task.get("risk_level") or "low").upper()
    return status in ACTIVE_TASK_STATUSES and source != "telegram" and risk not in APPROVAL_RISKS

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
    log("WAKE_NOW requested")
    for w in WORKERS:
        systemctl("start", w)
        update_worker_state(w, "IDLE", "woken_by_lifecycle")
    dispatch()
    update_system_state(
        worker_sleep_wake_implemented=True,
        worker_fleet_mode="AWAKE"
    )
    return {"ok": True, "mode": "AWAKE"}

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
