#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .task_status_constants import read_json
except ImportError:
    from task_status_constants import read_json

DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def slim_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "parent_task_id": task.get("parent_task_id"),
        "title": task.get("title"),
        "source": task.get("source"),
        "priority": task.get("priority"),
        "status": task.get("status"),
        "risk": task.get("risk") or task.get("risk_level"),
        "assigned_worker": task.get("assigned_worker"),
        "worker_eligible": task.get("worker_eligible"),
        "delivery_level": task.get("delivery_level"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "result": task.get("result"),
        "report_path": task.get("report_path"),
        "workspace": task.get("workspace"),
    }


def trace(root: Path, task_id: str) -> dict[str, Any]:
    queue = read_json(root / "state" / "task_queue.json", {"tasks": []})
    matches = [task for task in queue.get("tasks", []) if task.get("id") == task_id or task.get("parent_task_id") == task_id]
    jobs_dir = root / "state" / "direct_cto_jobs"
    jobs = []
    if jobs_dir.exists():
        for path in jobs_dir.glob("*.json"):
            payload = read_json(path, {})
            if payload.get("router_task_id") == task_id:
                jobs.append(
                    {
                        "id": payload.get("id"),
                        "status": payload.get("status"),
                        "created_at": payload.get("created_at"),
                        "updated_at": payload.get("updated_at"),
                        "result": payload.get("result"),
                    }
                )
    return {"ok": bool(matches or jobs), "task_id": task_id, "tasks": [slim_task(t) for t in matches], "jobs": jobs}


def main() -> int:
    parser = argparse.ArgumentParser(description="Trace a CTO task without dumping raw messages")
    parser.add_argument("task_id")
    parser.add_argument("--runtime", default=str(DEFAULT_ROOT))
    args = parser.parse_args()
    result = trace(Path(args.runtime).resolve(), args.task_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
