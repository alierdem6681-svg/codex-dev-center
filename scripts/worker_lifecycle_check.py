#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

ACTIVE_TASK_STATUSES = {"PENDING", "QUEUED", "ASSIGNED", "RUNNING"}
APPROVAL_RISKS = {"HIGH", "CRITICAL"}
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


def task_status(task: dict[str, Any]) -> str:
    return str(task.get("status", "")).upper()


def task_risk(task: dict[str, Any]) -> str:
    return str(task.get("risk") or task.get("risk_level") or "low").upper()


def is_active_task(task: dict[str, Any]) -> bool:
    return task_status(task) in ACTIVE_TASK_STATUSES


def worker_block_reason(task: dict[str, Any]) -> str:
    source = str(task.get("source", "")).lower()
    if source == "telegram":
        return "telegram_reserved_for_cto"
    if task_risk(task) in APPROVAL_RISKS:
        return "approval_required"
    return ""


def task_summary(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "status": task.get("status"),
        "source": task.get("source"),
        "risk": task.get("risk") or task.get("risk_level"),
        "assigned_worker": task.get("assigned_worker"),
        "title": str(task.get("title") or "")[:120],
    }


def split_active_tasks(runtime: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    payload = read_json(runtime / "state" / "task_queue.json", {"tasks": []})
    all_active = [task for task in payload.get("tasks", []) if is_active_task(task)]
    worker_tasks = []
    excluded = []
    for task in all_active:
        reason = worker_block_reason(task)
        if reason:
            item = task_summary(task)
            item["worker_block_reason"] = reason
            excluded.append(item)
        else:
            worker_tasks.append(task)
    return all_active, worker_tasks, excluded


def worker_state_map(runtime: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(runtime / "state" / "workers.json", {"workers": []})
    workers = {}
    for worker in payload.get("workers", []):
        worker_id = worker.get("id")
        if isinstance(worker_id, str):
            workers[worker_id] = worker
    return workers


def repair_worker_fleet(runtime: Path) -> list[dict[str, Any]]:
    commands = [
        ["python3", "supervisor/task_recovery_engine.py"],
        ["python3", "supervisor/lifecycle_manager.py", "wake-now"],
    ]
    results = []
    for command in commands:
        try:
            proc = subprocess.run(
                command,
                cwd=str(runtime),
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
            results.append(
                {
                    "command": " ".join(command),
                    "returncode": proc.returncode,
                    "stdout_tail": proc.stdout[-800:],
                    "stderr_tail": proc.stderr[-800:],
                }
            )
        except Exception as exc:
            results.append({"command": " ".join(command), "error": str(exc)})
    time.sleep(5)
    return results


def evaluate(runtime: Path, repair: bool = False) -> dict[str, Any]:
    all_active, worker_tasks, excluded_tasks = split_active_tasks(runtime)
    states = worker_state_map(runtime)
    services = {worker: service_status(f"codex-{worker}") for worker in WORKER_IDS}
    active_worker_services = [
        worker_id for worker_id, status in services.items() if status == "active"
    ]

    repair_log: list[dict[str, Any]] = []
    if repair and worker_tasks and not active_worker_services:
        repair_log = repair_worker_fleet(runtime)
        all_active, worker_tasks, excluded_tasks = split_active_tasks(runtime)
        states = worker_state_map(runtime)
        services = {worker: service_status(f"codex-{worker}") for worker in WORKER_IDS}
        active_worker_services = [
            worker_id for worker_id, status in services.items() if status == "active"
        ]

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

    if worker_tasks and not active_worker_services:
        sample = [task_summary(task) for task in worker_tasks[:5]]
        errors.append(
            "worker_eligible_active_tasks="
            + str(len(worker_tasks))
            + " but no worker service is active; sample="
            + json.dumps(sample, ensure_ascii=False)
        )

    if not worker_tasks and not active_worker_services:
        fleet_mode = "SLEEPING"
    elif active_worker_services:
        fleet_mode = "AWAKE"
    else:
        fleet_mode = "UNKNOWN"

    system_state = read_json(runtime / "state" / "system_state.json", {})
    configured_mode = system_state.get("worker_fleet_mode")
    if not worker_tasks and configured_mode not in (None, "", "SLEEPING", "AWAKE"):
        warnings.append(f"unexpected worker_fleet_mode={configured_mode}")

    return {
        "ok": not errors,
        "runtime": str(runtime),
        "active_task_count": len(all_active),
        "worker_eligible_active_task_count": len(worker_tasks),
        "excluded_active_task_count": len(excluded_tasks),
        "excluded_active_tasks": excluded_tasks[:10],
        "active_worker_services": active_worker_services,
        "worker_service_status": services,
        "worker_fleet_mode": fleet_mode,
        "state_worker_fleet_mode": configured_mode,
        "repair_attempted": bool(repair_log),
        "repair_log": repair_log,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", default="/opt/codex-dev-center")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()

    result = evaluate(Path(args.runtime), repair=args.repair)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"worker_lifecycle_ok={result['ok']}")
        print(f"worker_fleet_mode={result['worker_fleet_mode']}")
        print(f"active_task_count={result['active_task_count']}")
        print(f"worker_eligible_active_task_count={result['worker_eligible_active_task_count']}")
        print(f"excluded_active_task_count={result['excluded_active_task_count']}")
        for worker_id, status in result["worker_service_status"].items():
            print(f"{worker_id}={status}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
        for error in result["errors"]:
            print(f"error: {error}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
