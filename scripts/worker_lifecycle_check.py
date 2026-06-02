#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

ACTIVE_TASK_STATUSES = {"PENDING", "QUEUED", "ASSIGNED", "RUNNING"}
WORKER_IDS = ["worker-1", "worker-2", "worker-3", "worker-4"]


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return default


def service_status(service: str) -> str:
    if shutil.which("systemctl") is None:
        return "systemctl_unavailable"
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", service],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return f"error:{exc}"
    return (proc.stdout or proc.stderr or "unknown").strip() or "unknown"


def worker_state_map(runtime: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(runtime / "state" / "workers.json", {"workers": []})
    workers = {}
    for worker in payload.get("workers", []):
        worker_id = worker.get("id")
        if isinstance(worker_id, str):
            workers[worker_id] = worker
    return workers


def active_tasks(runtime: Path) -> list[dict[str, Any]]:
    payload = read_json(runtime / "state" / "task_queue.json", {"tasks": []})
    tasks = payload.get("tasks", [])
    return [
        task
        for task in tasks
        if str(task.get("status", "")).upper() in ACTIVE_TASK_STATUSES
    ]


def check(runtime: Path) -> dict[str, Any]:
    tasks = active_tasks(runtime)
    states = worker_state_map(runtime)
    services = {worker: service_status(f"codex-{worker}") for worker in WORKER_IDS}

    errors: list[str] = []
    warnings: list[str] = []

    for worker_id in WORKER_IDS:
        state = states.get(worker_id, {})
        status = str(state.get("status", "")).upper()
        current_task = state.get("current_task")
        service = services.get(worker_id, "unknown")

        if status in {"IDLE", "SLEEPING", "STOPPED"} and current_task:
            errors.append(f"{worker_id}: {status} worker has current_task={current_task}")

        if status == "RUNNING" and current_task and service != "active":
            errors.append(f"{worker_id}: RUNNING current_task={current_task} but service={service}")

    active_worker_services = [
        worker_id for worker_id, status in services.items() if status == "active"
    ]
    if tasks and not active_worker_services:
        errors.append(
            f"queue_has_active_tasks={len(tasks)} but no worker service is active"
        )

    if not tasks and not active_worker_services:
        fleet_mode = "SLEEPING"
    elif active_worker_services:
        fleet_mode = "AWAKE"
    else:
        fleet_mode = "UNKNOWN"

    system_state = read_json(runtime / "state" / "system_state.json", {})
    configured_mode = system_state.get("worker_fleet_mode")
    if not tasks and configured_mode not in (None, "", "SLEEPING", "AWAKE"):
        warnings.append(f"unexpected worker_fleet_mode={configured_mode}")

    return {
        "ok": not errors,
        "runtime": str(runtime),
        "active_task_count": len(tasks),
        "active_worker_services": active_worker_services,
        "worker_service_status": services,
        "worker_fleet_mode": fleet_mode,
        "state_worker_fleet_mode": configured_mode,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", default="/opt/codex-dev-center")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = check(Path(args.runtime))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"worker_lifecycle_ok={result['ok']}")
        print(f"worker_fleet_mode={result['worker_fleet_mode']}")
        print(f"active_task_count={result['active_task_count']}")
        for worker_id, status in result["worker_service_status"].items():
            print(f"{worker_id}={status}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
        for error in result["errors"]:
            print(f"error: {error}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
