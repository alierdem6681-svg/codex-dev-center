from __future__ import annotations

import argparse
import json
from pathlib import Path

from supervisor.deploy_guard import evaluate_deploy_action
from supervisor.output_guard import guard_for_telegram
from supervisor.task_queue import ensure_state, enqueue_task, list_tasks, read_json

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_STATE = ROOT / "state" / "system_state.json"
WORKERS_FILE = ROOT / "state" / "workers.json"
ROLES_FILE = ROOT / "supervisor" / "roles.json"


def status() -> dict:
    ensure_state()
    return {
        "system": read_json(SYSTEM_STATE, {}),
        "workers": read_json(WORKERS_FILE, {}),
        "queue": list_tasks(),
        "roles": read_json(ROLES_FILE, {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex Dev Center CTO/Supervisor")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("status")

    add = sub.add_parser("enqueue")
    add.add_argument("--title", required=True)
    add.add_argument("--message", required=True)
    add.add_argument("--worker", default=None)
    add.add_argument("--risk", default="low")

    guard = sub.add_parser("guard-output")
    guard.add_argument("--task-id", default="NO_TASK")
    guard.add_argument("text")

    deploy = sub.add_parser("check-deploy")
    deploy.add_argument("description")

    args = parser.parse_args()

    if args.command == "init":
        ensure_state()
        print(json.dumps({"ok": True}, indent=2))
    elif args.command == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    elif args.command == "enqueue":
        print(
            json.dumps(
                enqueue_task(args.title, args.message, "local", args.worker, args.risk),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "guard-output":
        print(guard_for_telegram(args.text, args.task_id))
    elif args.command == "check-deploy":
        print(json.dumps(evaluate_deploy_action(args.description), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
