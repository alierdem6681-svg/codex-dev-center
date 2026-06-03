#!/usr/bin/env python3
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from .task_status_constants import is_worker_eligible_task
    from .direct_cto_job_recovery import reconcile_stale_jobs
except ImportError:
    from task_status_constants import is_worker_eligible_task
    from direct_cto_job_recovery import reconcile_stale_jobs

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
REPORTS = APP / "reports"

SERVICES = [
    "codex-panel",
    "codex-lifecycle",
    "codex-cto",
    "codex-worker-1",
    "codex-worker-2",
    "codex-worker-3",
    "codex-worker-4",
]
def now():
    return datetime.now(timezone.utc).isoformat()

def log(msg):
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "service_watchdog.log").open("a", encoding="utf-8") as f:
        f.write(f"{now()} {msg}\n")

def run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, cwd=str(APP), text=True, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)

def is_active(service):
    rc, out, _ = run(["systemctl", "is-active", service])
    return rc == 0 and out == "active"

def restart(service):
    rc, out, err = run(["sudo", "systemctl", "restart", service])
    log(f"restart service={service} rc={rc} err={err[-200:]}")
    return rc == 0

def enable(service):
    rc, out, err = run(["sudo", "systemctl", "enable", service])
    log(f"enable service={service} rc={rc} err={err[-200:]}")
    return rc == 0

def read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default

def write_json(path, data):
    data["updated_at"] = now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

def queue_has_active_tasks():
    q = read_json(STATE / "task_queue.json", {"tasks": []})
    return any(is_worker_eligible_task(t) for t in q.get("tasks", []))

def lifecycle(command):
    rc, out, err = run(["python3", "supervisor/lifecycle_manager.py", command], timeout=60)
    log(f"lifecycle command={command} rc={rc} err={err[-200:]}")
    return rc == 0

def drift_check():
    rc, out, err = run(["python3", "supervisor/drift_checker.py"], timeout=90)
    log(f"drift_check rc={rc} err={err[-200:]}")
    return rc == 0

def health_once():
    result = {
        "checked_at": now(),
        "services": {},
        "restarted": [],
        "queue_has_tasks": queue_has_active_tasks(),
        "actions": []
    }

    core_services = ["codex-panel", "codex-direct-cto", "codex-lifecycle", "codex-watchdog"]
    worker_services = ["codex-worker-1", "codex-worker-2", "codex-worker-3", "codex-worker-4"]

    for svc in core_services:
        enable(svc)
        active = is_active(svc)
        result["services"][svc] = "active" if active else "inactive"
        if not active:
            if restart(svc):
                result["restarted"].append(svc)
                result["services"][svc] = "restarted"

    for svc in worker_services:
        enable(svc)
        active = is_active(svc)
        result["services"][svc] = "active" if active else "inactive"

    if result["queue_has_tasks"]:
        lifecycle("wake-now")
        result["actions"].append("wake_workers")
    else:
        lifecycle("sleep-now")
        result["actions"].append("sleep_workers")

    drift_check()
    result["actions"].append("drift_check")

    direct_cto_recovery = reconcile_stale_jobs(APP)
    result["direct_cto_recovery"] = direct_cto_recovery
    if direct_cto_recovery.get("changed"):
        result["actions"].append("direct_cto_stale_job_recovery")

    write_json(STATE / "service_health.json", result)

    ss = read_json(STATE / "system_state.json", {})
    ss["service_watchdog_ready"] = True
    ss["last_service_health_check"] = result["checked_at"]
    ss["service_watchdog_last_restarted"] = result["restarted"]
    write_json(STATE / "system_state.json", ss)

    REPORTS.mkdir(parents=True, exist_ok=True)
    REPORTS.joinpath("SERVICE_HEALTH_REPORT.md").write_text(
        "# SERVICE HEALTH REPORT\n\n"
        f"Tarih: {result['checked_at']}\n\n"
        "Services:\n" + "\n".join([f"- {k}: {v}" for k, v in result["services"].items()]) + "\n\n"
        "Restarted:\n" + "\n".join([f"- {x}" for x in result["restarted"]] or ["- Yok"]) + "\n\n"
        "Actions:\n" + "\n".join([f"- {x}" for x in result["actions"]]) + "\n",
        encoding="utf-8"
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))

def daemon():
    log("watchdog daemon started")
    while True:
        health_once()
        time.sleep(30)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "daemon":
        daemon()
    else:
        health_once()
