from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
QUEUE_FILE = STATE_DIR / "task_queue.json"
WORKERS_FILE = STATE_DIR / "workers.json"

WORKER_IDS = ["worker-1", "worker-2", "worker-3", "worker-4"]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_state() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not QUEUE_FILE.exists():
        write_json(QUEUE_FILE, {"tasks": []})
    if not WORKERS_FILE.exists():
        write_json(
            WORKERS_FILE,
            {
                "updated_at": utc_now(),
                "workers": [
                    {"id": worker_id, "status": "idle", "current_task": None}
                    for worker_id in WORKER_IDS
                ],
            },
        )


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp_path.replace(path)


def next_task_id(queue: dict[str, Any]) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    count = len(queue.get("tasks", [])) + 1
    return f"TASK-{today}-{count:04d}"


def choose_worker(worker_hint: str | None = None) -> str:
    if worker_hint in WORKER_IDS:
        return worker_hint
    return "worker-1"


def enqueue_task(
    title: str,
    raw_message: str,
    source: str = "local",
    worker: str | None = None,
    risk_level: str = "low",
) -> dict[str, Any]:
    ensure_state()
    queue = read_json(QUEUE_FILE, {"tasks": []})
    task = {
        "id": next_task_id(queue),
        "title": title,
        "source": source,
        "raw_message": raw_message,
        "assigned_worker": choose_worker(worker),
        "risk_level": risk_level,
        "status": "queued",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "log_path": f"logs/{next_task_id(queue)}.log",
        "report_path": f"reports/{next_task_id(queue)}_REPORT.md",
    }
    queue.setdefault("tasks", []).append(task)
    write_json(QUEUE_FILE, queue)
    return task


def list_tasks() -> dict[str, Any]:
    ensure_state()
    return read_json(QUEUE_FILE, {"tasks": []})


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex Dev Center task queue")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("enqueue")
    add.add_argument("--title", required=True)
    add.add_argument("--message", required=True)
    add.add_argument("--source", default="local")
    add.add_argument("--worker", default=None)
    add.add_argument("--risk", default="low")

    sub.add_parser("list")
    sub.add_parser("init")
    args = parser.parse_args()

    if args.command == "init":
        ensure_state()
        print(json.dumps({"ok": True, "queue": str(QUEUE_FILE)}, indent=2))
    elif args.command == "enqueue":
        task = enqueue_task(args.title, args.message, args.source, args.worker, args.risk)
        print(json.dumps(task, ensure_ascii=False, indent=2))
    elif args.command == "list":
        print(json.dumps(list_tasks(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
