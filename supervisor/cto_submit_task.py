#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .cto_task_router import submit_task, trigger_lifecycle
except ImportError:
    from cto_task_router import submit_task, trigger_lifecycle

DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit a CTO task through the central router")
    parser.add_argument("--runtime", default=str(DEFAULT_ROOT))
    parser.add_argument("--source", required=True, choices=["telegram", "windows_codex_ssh", "dashboard", "local", "cto"])
    parser.add_argument("--priority", default="normal", choices=["low", "normal", "high", "urgent"])
    parser.add_argument("--title", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--risk", default=None, choices=["low", "medium", "high", "critical"])
    parser.add_argument("--requested-by", default="")
    parser.add_argument("--split", action="store_true")
    parser.add_argument("--no-split", action="store_true")
    parser.add_argument("--worker-eligible", action="store_true")
    parser.add_argument("--no-worker-eligible", action="store_true")
    args = parser.parse_args()

    split = None
    if args.split:
        split = True
    if args.no_split:
        split = False
    worker_eligible = None
    if args.worker_eligible:
        worker_eligible = True
    if args.no_worker_eligible:
        worker_eligible = False

    root = Path(args.runtime).resolve()
    result = submit_task(
        root=root,
        source=args.source,
        title=args.title,
        message=args.message,
        priority=args.priority,
        risk=args.risk,
        requested_by=args.requested_by,
        split=split,
        worker_eligible=worker_eligible,
    )
    if any(t.get("worker_eligible") for t in [result["task"], *result["subtasks"]]):
        result["lifecycle"] = trigger_lifecycle(root)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
