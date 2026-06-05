#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
REPORTS = APP / "reports"
WORKSPACES = APP / "workspaces"
MODULE = APP / "modules" / "codex_execution"

def now():
    return datetime.now(timezone.utc).isoformat()

def read_json(path, default):
    try:
        if Path(path).exists():
            return json.loads(Path(path).read_text())
    except Exception:
        pass
    return default

def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    tmp = Path(path).with_suffix(Path(path).suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)

def log(msg):
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "codex_execution.log").open("a", encoding="utf-8") as f:
        f.write(f"{now()} {msg}\n")

def policy():
    base = read_json(STATE / "codex_execution_policy.json", {})
    module_settings = read_json(MODULE / "settings.json", {})
    merged = module_settings | base
    return merged

def get_task(task_id):
    q = read_json(STATE / "task_queue.json", {"tasks": []})
    for task in q.get("tasks", []):
        if task.get("id") == task_id:
            return task
    return None

def safe_task_id(task_id):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in task_id)

def prepare_workspace(task_id):
    task = get_task(task_id)
    if not task:
        raise SystemExit(f"Task not found: {task_id}")

    sid = safe_task_id(task_id)
    workspace = WORKSPACES / sid
    workspace.mkdir(parents=True, exist_ok=True)

    # Context snapshot
    context_dir = workspace / "context"
    context_dir.mkdir(exist_ok=True)

    for rel in [
        "AGENTS.md",
        "constitution/ANAYASA.md",
        "docs/MODULAR_ARCHITECTURE_STANDARD.md",
        "docs/CTO_FULL_AUTHORITY_POLICY.md",
        "docs/WORKER_LIFECYCLE_POLICY.md",
        "docs/DRIFT_CONTROL_POLICY.md",
        "docs/HANDOVER.md",
        "docs/ROADMAP.md",
        "memory/project_memory.md",
        "state/system_state.json",
        "state/module_registry.json",
        "state/module_settings.json",
        "state/action_catalog.json",
        "state/worker_profiles.json",
        "state/codex_execution_policy.json",
    ]:
        src = APP / rel
        if src.exists():
            dst = context_dir / rel.replace("/", "__")
            dst.write_text(src.read_text(errors="replace"), encoding="utf-8")

    prompt = f"""# Codex Task Execution Prompt

You are operating inside Codex Dev Center.

Task ID:
{task_id}

Task title:
{task.get("title", "")}

Task description:
{task.get("description", "")}

Risk:
{task.get("risk", "low")}

Mandatory rules:
- Read AGENTS.md and context files first.
- Keep every change modular.
- Do not touch production.
- Do not read secrets.
- Do not perform GCloud mutate operations.
- Write logs and report.
- Update handover if a real change is made.
- Do not send long code/terminal output to Telegram.
- Capture technical output to logs.

This workspace is pipeline-gated. Do not request user approval; report a failure if required gates cannot pass.
"""
    (workspace / "CODEX_TASK_PROMPT.md").write_text(prompt, encoding="utf-8")
    (workspace / "task.json").write_text(json.dumps(task, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (workspace / "README.md").write_text(f"# Workspace for {task_id}\n\nPrepared at: {now()}\n", encoding="utf-8")

    log(f"PREPARE_WORKSPACE task={task_id} workspace={workspace}")
    print(json.dumps({"ok": True, "task_id": task_id, "workspace": str(workspace)}, indent=2, ensure_ascii=False))

def request_approval(task_id):
    task = get_task(task_id)
    if not task:
        raise SystemExit(f"Task not found: {task_id}")

    log(f"REQUEST_APPROVAL_DISABLED_PIPELINE_ONLY task={task_id}")
    print(json.dumps({
        "ok": True,
        "task_id": task_id,
        "approval_required": False,
        "approval_gate_disabled": True,
        "gate_rule": "pipeline_pass_only",
        "next_action": "run_pipeline_gated_execution"
    }, indent=2, ensure_ascii=False))

def run_task(task_id):
    pol = policy()
    if not pol.get("enabled", False) or not pol.get("unattended_execution_enabled", False):
        log(f"RUN_BLOCKED_POLICY task={task_id}")
        print(json.dumps({
            "ok": False,
            "blocked": True,
            "reason": "codex_execution_disabled_or_pipeline_gate_not_configured",
            "task_id": task_id,
            "next_action": "enable_unattended_execution_after_pipeline_gate"
        }, indent=2, ensure_ascii=False))
        return

    task = get_task(task_id)
    if not task:
        raise SystemExit(f"Task not found: {task_id}")

    sid = safe_task_id(task_id)
    workspace = WORKSPACES / sid
    if not workspace.exists():
        prepare_workspace(task_id)

    codex_path = shutil.which("codex")
    if not codex_path:
        print(json.dumps({"ok": False, "error": "codex_cli_not_found"}, indent=2, ensure_ascii=False))
        return

    # Bu bölüm pipeline-gated execution policy açılana kadar çalışmaz.
    log_file = LOGS / f"codex_task_{sid}.log"
    prompt_file = workspace / "CODEX_TASK_PROMPT.md"

    cmd = [codex_path]
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"{now()} WOULD_RUN_INTERACTIVE_CODEX task={task_id} prompt={prompt_file}\n")
        f.write("Unattended execution policy is pipeline-gated; no user approval is requested.\n")

    print(json.dumps({
        "ok": True,
        "task_id": task_id,
        "workspace": str(workspace),
        "log": str(log_file),
        "note": "interactive/unattended execution hook prepared"
    }, indent=2, ensure_ascii=False))

def status():
    pol = policy()
    print(json.dumps({
        "ok": True,
        "policy": pol,
        "workspaces": sorted([p.name for p in WORKSPACES.glob("*")]) if WORKSPACES.exists() else [],
        "codex_cli_found": shutil.which("codex") is not None,
    }, indent=2, ensure_ascii=False))

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--task-id", required=True)
    p.set_defaults(func=lambda a: prepare_workspace(a.task_id))

    p = sub.add_parser("request-approval")
    p.add_argument("--task-id", required=True)
    p.set_defaults(func=lambda a: request_approval(a.task_id))

    p = sub.add_parser("run")
    p.add_argument("--task-id", required=True)
    p.set_defaults(func=lambda a: run_task(a.task_id))

    p = sub.add_parser("status")
    p.set_defaults(func=lambda a: status())

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
