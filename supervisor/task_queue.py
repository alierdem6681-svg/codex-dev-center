from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .cto_task_router import build_task_envelope, canonical_source, classify_task_route, task_metadata_from_envelope
    from .task_status_constants import (
        TASK_STATUS_ROUTED,
        TASK_STATUS_QUEUED,
        atomic_write_json,
        normalize_queue_payload,
        normalize_risk,
        utc_now,
    )
except ImportError:
    from cto_task_router import build_task_envelope, canonical_source, classify_task_route, task_metadata_from_envelope
    from task_status_constants import (
        TASK_STATUS_ROUTED,
        TASK_STATUS_QUEUED,
        atomic_write_json,
        normalize_queue_payload,
        normalize_risk,
        utc_now,
    )

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
    atomic_write_json(path, data)


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
    task_id = next_task_id(queue)
    risk = normalize_risk(risk_level)
    source = canonical_source(source)
    route = classify_task_route(f"{title}\n{raw_message}")
    envelope = build_task_envelope(
        source=source,
        title=title,
        message=raw_message,
        risk=risk,
        route=route,
        requested_worker_eligible=None,
    )
    router_metadata = task_metadata_from_envelope(envelope)
    worker_eligible = bool(router_metadata["worker_eligible"])
    task = {
        "id": task_id,
        "title": title,
        "source": source,
        "raw_message": raw_message,
        "assigned_worker": choose_worker(worker) if worker_eligible else None,
        "risk": risk,
        "risk_level": risk,
        "status": TASK_STATUS_QUEUED if worker_eligible else TASK_STATUS_ROUTED,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "log_path": f"logs/{task_id}.log",
        "report_path": f"reports/{task_id}_REPORT.md",
        "task_class": route["task_class"],
        "control_type": route["control_type"],
        "delivery_mode": route["delivery_mode"],
        "pipeline_lane": route["pipeline_lane"],
        "intent_domain": route.get("intent_domain", ""),
    }
    task.update(router_metadata)
    queue.setdefault("tasks", []).append(task)
    queue, _changes = normalize_queue_payload(queue)
    write_json(QUEUE_FILE, queue)
    return task


def list_tasks() -> dict[str, Any]:
    ensure_state()
    queue = read_json(QUEUE_FILE, {"tasks": []})
    queue, changes = normalize_queue_payload(queue)
    if changes:
        write_json(QUEUE_FILE, queue)
    return queue


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
