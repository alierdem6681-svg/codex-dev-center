#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supervisor.state_file_lock import state_file_lock
from supervisor.task_status_constants import (
    ACTIVE_TASK_STATUSES,
    TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP,
    TASK_STATUS_FAILED_NO_PROPOSAL,
    TASK_STATUS_FAILED_RETRYABLE,
    TASK_STATUS_VALIDATION_FAILED,
    TASK_STATUS_APPROVAL_REQUIRED,
    atomic_write_json,
    normalize_queue_payload,
    normalize_status,
    read_json,
    utc_now,
)


CLEANUP_CANDIDATE_STATUSES = ACTIVE_TASK_STATUSES | {
    TASK_STATUS_FAILED_RETRYABLE,
    TASK_STATUS_VALIDATION_FAILED,
    TASK_STATUS_APPROVAL_REQUIRED,
    TASK_STATUS_FAILED_NO_PROPOSAL,
}


def status_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(normalize_status(task.get("status")) for task in tasks))


def active_count(tasks: list[dict[str, Any]]) -> int:
    return sum(1 for task in tasks if normalize_status(task.get("status")) in ACTIVE_TASK_STATUSES)


def cleanup_candidate_count(tasks: list[dict[str, Any]]) -> int:
    return sum(1 for task in tasks if normalize_status(task.get("status")) in CLEANUP_CANDIDATE_STATUSES)


def write_report(report_path: Path, payload: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Queue Owner Cleanup Report",
        "",
        f"Generated at: {payload['cleanup_at']}",
        f"Archive path: {payload['archive_path']}",
        f"Original task count: {payload['original_task_count']}",
        f"Original active task count: {payload['original_active_task_count']}",
        f"Cleanup candidate count: {payload['cleanup_candidate_count']}",
        f"Active queue remaining: {payload['active_queue_remaining']}",
        f"Cleanup status: {payload['cleanup_status']}",
        f"System state: {payload['system_state']}",
        "",
        "## Original Status Counts",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(payload["original_status_counts"].items()))
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cleanup(root: Path, archive_path: Path, execute: bool = False) -> dict[str, Any]:
    root = root.resolve()
    archive_path = archive_path.resolve()
    state = root / "state"
    reports = root / "reports"
    queue_path = state / "task_queue.json"
    workers_path = state / "workers.json"
    system_state_path = state / "system_state.json"
    cleanup_at = utc_now()

    archive_path.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any]
    with state_file_lock(queue_path):
        queue = read_json(queue_path, {"tasks": []})
        queue, _changes = normalize_queue_payload(queue)
        tasks = [task for task in queue.get("tasks", []) if isinstance(task, dict)]
        original_counts = status_counts(tasks)
        original_active = active_count(tasks)
        cleanup_candidates = cleanup_candidate_count(tasks)
        archived_tasks = []
        for task in tasks:
            archived = dict(task)
            archived["cleanup_status"] = TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP
            archived["cleanup_at"] = cleanup_at
            archived_tasks.append(archived)

        payload = {
            "ok": True,
            "executed": execute,
            "cleanup_at": cleanup_at,
            "archive_path": str(archive_path),
            "queue_path": str(queue_path),
            "cleanup_status": TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP,
            "system_state": "READY_FOR_NEW_TASKS" if execute else "DRY_RUN",
            "original_task_count": len(tasks),
            "original_active_task_count": original_active,
            "cleanup_candidate_count": cleanup_candidates,
            "original_status_counts": original_counts,
            "active_queue_remaining": 0 if execute else original_active,
        }

        (archive_path / "task_queue_before_owner_cleanup.json").write_text(
            json.dumps(queue, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (archive_path / "task_queue_owner_cleanup_cancelled_tasks.json").write_text(
            json.dumps({"tasks": archived_tasks, "updated_at": cleanup_at}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (archive_path / "queue_owner_cleanup_summary.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        if execute:
            atomic_write_json(
                queue_path,
                {
                    "tasks": [],
                    "cleanup_status": TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP,
                    "cleanup_at": cleanup_at,
                    "archived_task_count": len(tasks),
                    "archived_active_task_count": original_active,
                    "archive_path": str(archive_path),
                },
            )

    if execute:
        with state_file_lock(workers_path):
            workers = read_json(workers_path, {"workers": []})
            for worker in workers.get("workers", []):
                worker["status"] = "IDLE"
                worker["current_task"] = None
                worker["last_seen"] = cleanup_at
                worker["note"] = "owner_cleanup_ready_for_new_tasks"
            atomic_write_json(workers_path, workers)

        with state_file_lock(system_state_path):
            system_state = read_json(system_state_path, {})
            system_state.update(
                {
                    "system_state": "READY_FOR_NEW_TASKS",
                    "state": "READY_FOR_NEW_TASKS",
                    "phase": "READY_FOR_NEW_TASKS",
                    "ready_for_new_tasks": True,
                    "active_queue_remaining": 0,
                    "queue_cleanup_status": TASK_STATUS_CANCELLED_BY_OWNER_CLEANUP,
                    "queue_cleanup_archive_path": str(archive_path),
                    "queue_cleanup_at": cleanup_at,
                    "queue_cleanup_original_task_count": payload["original_task_count"],
                    "queue_cleanup_original_active_task_count": payload["original_active_task_count"],
                    "queue_cleanup_candidate_count": payload["cleanup_candidate_count"],
                    "worker_fleet_mode": "IDLE",
                    "worker_lifecycle_daemon_active": True,
                    "backlog_dispatcher_active": True,
                    "backlog_dispatcher_last_result": "owner_cleanup_queue_empty",
                    "task_recovery_engine_active": True,
                    "updated_at": cleanup_at,
                }
            )
            atomic_write_json(system_state_path, system_state)

        cleanup_state = state / "queue_owner_cleanup_status.json"
        atomic_write_json(cleanup_state, payload)
        write_report(reports / "queue_owner_cleanup_last_report.md", payload)

    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive and clear the active Codex task queue after owner cleanup.")
    parser.add_argument("--root", default="/opt/codex-dev-center")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    payload = cleanup(Path(args.root), Path(args.archive), execute=args.execute)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
