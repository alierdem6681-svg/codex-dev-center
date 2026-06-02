#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .critical_operation_policy import approval_required_payload
    from .task_status_constants import (
        ACTIVE_TASK_STATUSES,
        TASK_STATUS_APPROVAL_REQUIRED,
        TASK_STATUS_DEPLOYED,
        TASK_STATUS_DONE,
        TASK_STATUS_PROPOSAL_DONE,
        atomic_write_json,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_status,
    )
except ImportError:
    from critical_operation_policy import approval_required_payload
    from task_status_constants import (
        ACTIVE_TASK_STATUSES,
        TASK_STATUS_APPROVAL_REQUIRED,
        TASK_STATUS_DEPLOYED,
        TASK_STATUS_DONE,
        TASK_STATUS_PROPOSAL_DONE,
        atomic_write_json,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_status,
    )


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()
SOURCE_ROOT = Path(os.environ.get("CODEX_DEV_CENTER_SOURCE", "/home/alierdem6681/codex-dev-center-github-export")).resolve()
STATE = ROOT / "state"
REPORTS = ROOT / "reports"
QUEUE = STATE / "task_queue.json"
DELIVERY_STATE = STATE / "cto_delivery_state.json"
DEPLOY_WORKFLOW = "Deploy to VM"
SMOKE_WORKFLOW = "VM Smoke Check"
CONFIRM_PHRASE = "DEPLOY-CODEX-VM"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    return default


def run(args: list[str], cwd: Path | None = None, timeout: int = 300) -> dict[str, Any]:
    try:
        proc = subprocess.run(args, cwd=str(cwd or ROOT), text=True, capture_output=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-5000:],
            "stderr": proc.stderr[-5000:],
            "cmd": " ".join(args),
        }
    except Exception as exc:
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": str(exc), "cmd": " ".join(args)}


def command_root() -> Path:
    return SOURCE_ROOT if (SOURCE_ROOT / ".git").exists() else ROOT


def policy() -> dict[str, Any]:
    template = read_json(ROOT / "state_templates/cto_delivery_policy.json", {})
    deploy = read_json(ROOT / "state_templates/deploy_policy.json", {})
    production = read_json(ROOT / "state_templates/production_policy.json", {})
    max_parallel = int(template.get("max_parallel_tasks") or deploy.get("max_parallel_tasks_until_stable") or 1)
    threshold = int(
        template.get("stable_successful_low_risk_deploy_threshold")
        or deploy.get("stable_successful_low_risk_deploy_threshold")
        or production.get("stable_successful_low_risk_deploy_threshold")
        or 3
    )
    return {
        "enabled": bool(template.get("enabled", True)),
        "max_parallel_tasks": max_parallel,
        "stable_successful_low_risk_deploy_threshold": threshold,
        "production_deploy_allowed_when_all_gates_pass": bool(
            template.get("production_deploy_allowed_when_all_gates_pass", True)
            and production.get("normal_app_deploy_allowed_when_all_gates_pass", True)
        ),
        "production_deploy_requires_user_approval_for_normal_app_changes": bool(
            template.get("production_deploy_requires_user_approval_for_normal_app_changes", False)
            or production.get("manual_approval_required_for_normal_app_deploy", False)
        ),
        "workflow": str(template.get("github_actions_workflow_name") or DEPLOY_WORKFLOW),
        "confirm_phrase": str(template.get("github_actions_confirm_phrase") or CONFIRM_PHRASE),
    }


def load_queue() -> dict[str, Any]:
    queue = read_json(QUEUE, {"tasks": []})
    normalized, changes = normalize_queue_payload(queue)
    if changes:
        atomic_write_json(QUEUE, normalized)
    return normalized


def task_text(task: dict[str, Any]) -> str:
    return "\n".join(str(task.get(key, "")) for key in ["title", "description", "raw_message"])


def find_task(task_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    queue = load_queue()
    for task in queue.get("tasks", []):
        if task.get("id") == task_id:
            return queue, task
    return queue, None


def queue_summary(queue: dict[str, Any] | None = None) -> dict[str, Any]:
    queue = queue or load_queue()
    tasks = queue.get("tasks", [])
    active = [task for task in tasks if normalize_status(task.get("status")) in ACTIVE_TASK_STATUSES]
    worker_active = [task for task in active if is_worker_eligible_task(task)]
    return {
        "task_count": len(tasks),
        "status_counts": dict(Counter(normalize_status(task.get("status")) for task in tasks)),
        "active_task_count": len(active),
        "worker_eligible_active_count": len(worker_active),
        "worker_eligible_active_ids": [task.get("id") for task in worker_active],
    }


def delivery_status() -> dict[str, Any]:
    cfg = policy()
    state = read_json(DELIVERY_STATE, {})
    successful = int(state.get("successful_low_risk_deploy_count", 0) or 0)
    stable = successful >= cfg["stable_successful_low_risk_deploy_threshold"]
    payload = {
        "ok": True,
        "checked_at": now(),
        "policy": cfg,
        "stable": stable,
        "successful_low_risk_deploy_count": successful,
        "queue": queue_summary(),
        "last_deploy_task_id": state.get("last_deploy_task_id"),
        "last_deploy_run_id": state.get("last_deploy_run_id"),
        "last_smoke_run_id": state.get("last_smoke_run_id"),
    }
    atomic_write_json(DELIVERY_STATE, payload)
    return payload


def evaluate_task(task: dict[str, Any]) -> dict[str, Any]:
    critical = approval_required_payload(task_text(task))
    status = normalize_status(task.get("status"))
    deployable_statuses = {TASK_STATUS_DONE, TASK_STATUS_PROPOSAL_DONE, TASK_STATUS_DEPLOYED}
    delivery_level = str(task.get("delivery_level") or "").upper()
    repo_applied = bool(
        task.get("repo_applied")
        or task.get("branch_merged")
        or task.get("merged_commit")
        or delivery_level in {"READY_FOR_DEPLOY", "MERGED", "DEPLOYED"}
    )
    return {
        "task_id": task.get("id"),
        "status": status,
        "risk": task.get("risk") or task.get("risk_level"),
        "assigned_worker": task.get("assigned_worker"),
        "worker_eligible": task.get("worker_eligible"),
        "repo_applied": repo_applied,
        "delivery_level": task.get("delivery_level"),
        "critical": critical,
        "ready_for_deploy_gate": status in deployable_statuses and repo_applied and not critical["approval_required"],
        "production_deployed": bool(task.get("production_deployed") or status == TASK_STATUS_DEPLOYED),
    }


def run_readiness() -> dict[str, Any]:
    result = run([sys.executable, "supervisor/production_readiness_suite.py", "--json"], cwd=ROOT, timeout=300)
    payload: dict[str, Any] = {}
    if result["stdout"].strip().startswith("{"):
        try:
            payload = json.loads(result["stdout"])
        except Exception:
            payload = {}
    if not payload:
        payload = read_json(STATE / "production_readiness_status.json", {})
    return {
        "ok": bool(result["ok"] and payload.get("status") == "PASS"),
        "result": result,
        "status": payload.get("status"),
        "score_percent": payload.get("score_percent"),
        "failed": payload.get("failed", []),
    }


def git_head() -> str:
    result = run(["git", "rev-parse", "HEAD"], cwd=command_root(), timeout=30)
    return result.get("stdout", "").strip()


def latest_run(workflow: str, head_sha: str = "") -> dict[str, Any]:
    args = [
        "gh",
        "run",
        "list",
        "--workflow",
        workflow,
        "--limit",
        "10",
        "--json",
        "databaseId,status,conclusion,createdAt,updatedAt,headBranch,headSha,name,url,event",
    ]
    result = run(args, cwd=command_root(), timeout=60)
    if not result["ok"]:
        return {"ok": False, "run_result": result}
    try:
        runs = json.loads(result["stdout"])
    except Exception as exc:
        return {"ok": False, "error": str(exc), "run_result": result}
    for item in runs:
        if not head_sha or item.get("headSha") == head_sha:
            return {"ok": True, "run": item}
    return {"ok": False, "error": "run_not_found", "runs": runs[:3]}


def wait_run(run_id: str, timeout_seconds: int = 900) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {"ok": False, "status": "not_started"}
    while time.time() < deadline:
        view = run(
            ["gh", "run", "view", run_id, "--json", "status,conclusion,headSha,url,createdAt,updatedAt,name,event"],
            cwd=command_root(),
            timeout=60,
        )
        if not view["ok"]:
            return {"ok": False, "view": view}
        payload = json.loads(view["stdout"])
        last = payload
        if payload.get("status") == "completed":
            return {"ok": payload.get("conclusion") == "success", "run": payload}
        time.sleep(5)
    return {"ok": False, "error": "timeout", "last": last}


def dispatch_workflow(workflow: str, wait: bool = False) -> dict[str, Any]:
    head = git_head()
    if workflow == DEPLOY_WORKFLOW:
        args = ["gh", "workflow", "run", workflow, "--ref", "main", "-f", f"confirm={CONFIRM_PHRASE}", "-f", "ref=main"]
    else:
        args = ["gh", "workflow", "run", workflow, "--ref", "main"]
    dispatched = run(args, cwd=command_root(), timeout=60)
    if not dispatched["ok"]:
        return {"ok": False, "dispatch": dispatched}
    time.sleep(3)
    latest = latest_run(workflow, head)
    if not latest.get("ok"):
        return {"ok": False, "dispatch": dispatched, "latest": latest}
    run_id = str(latest["run"].get("databaseId"))
    payload = {"ok": True, "dispatch": dispatched, "run": latest["run"]}
    if wait:
        payload["wait"] = wait_run(run_id)
        payload["ok"] = bool(payload["wait"].get("ok"))
    return payload


def mark_task_deployed(task_id: str, deploy_run: dict[str, Any], smoke_run: dict[str, Any] | None = None) -> dict[str, Any]:
    queue, task = find_task(task_id)
    if not task:
        return {"ok": False, "error": "task_not_found"}
    task["status"] = TASK_STATUS_DEPLOYED
    task["production_deployed"] = True
    task["delivery_level"] = "DEPLOYED"
    task["deploy_run_id"] = str(deploy_run.get("databaseId") or deploy_run.get("run", {}).get("databaseId") or "")
    task["deploy_run_url"] = deploy_run.get("url") or deploy_run.get("run", {}).get("url") or ""
    if smoke_run:
        task["smoke_run_id"] = str(smoke_run.get("databaseId") or smoke_run.get("run", {}).get("databaseId") or "")
        task["smoke_run_url"] = smoke_run.get("url") or smoke_run.get("run", {}).get("url") or ""
    task["updated_at"] = now()
    atomic_write_json(QUEUE, queue)

    state = read_json(DELIVERY_STATE, {})
    risk = str(task.get("risk") or task.get("risk_level") or "").lower()
    if risk == "low":
        state["successful_low_risk_deploy_count"] = int(state.get("successful_low_risk_deploy_count", 0) or 0) + 1
    state.update(
        {
            "last_deploy_task_id": task_id,
            "last_deploy_run_id": task.get("deploy_run_id"),
            "last_smoke_run_id": task.get("smoke_run_id", state.get("last_smoke_run_id")),
        }
    )
    atomic_write_json(DELIVERY_STATE, state)
    return {"ok": True, "task": task}


def mark_task_merged(task_id: str, commit: str = "") -> dict[str, Any]:
    queue, task = find_task(task_id)
    if not task:
        return {"ok": False, "error": "task_not_found"}
    task["repo_applied"] = True
    task["branch_merged"] = True
    task["delivery_level"] = "READY_FOR_DEPLOY"
    if commit:
        task["merged_commit"] = commit
    task["updated_at"] = now()
    atomic_write_json(QUEUE, queue)
    return {"ok": True, "task_id": task_id, "delivery_level": "READY_FOR_DEPLOY", "merged_commit": commit}


def set_task_approval_required(task_id: str, findings: list[str]) -> dict[str, Any]:
    queue, task = find_task(task_id)
    if not task:
        return {"ok": False, "error": "task_not_found"}
    task["status"] = TASK_STATUS_APPROVAL_REQUIRED
    task["worker_eligible"] = False
    task["approval_required"] = True
    task["approval_reason"] = "critical_infrastructure_operation"
    task["critical_operation_findings"] = findings
    task["updated_at"] = now()
    atomic_write_json(QUEUE, queue)
    return {"ok": True, "task_id": task_id, "status": TASK_STATUS_APPROVAL_REQUIRED, "findings": findings}


def dispatch_next(execute: bool = False) -> dict[str, Any]:
    cfg = policy()
    summary = queue_summary()
    if summary["worker_eligible_active_count"] >= cfg["max_parallel_tasks"]:
        return {"ok": True, "status": "WAIT_ACTIVE_TASK", "summary": summary}
    if not execute:
        return {"ok": True, "status": "DRY_RUN_READY_TO_DISPATCH", "summary": summary}
    dispatched = run([sys.executable, "supervisor/lifecycle_manager.py", "dispatch"], cwd=ROOT, timeout=60)
    return {"ok": dispatched["ok"], "status": "DISPATCH_ATTEMPTED", "dispatch": dispatched, "summary": queue_summary()}


def deploy_task(task_id: str, execute: bool = False, wait: bool = False, smoke: bool = True) -> dict[str, Any]:
    cfg = policy()
    queue, task = find_task(task_id)
    if not task:
        return {"ok": False, "status": "TASK_NOT_FOUND", "task_id": task_id}
    evaluation = evaluate_task(task)
    if evaluation["critical"]["approval_required"]:
        marked = set_task_approval_required(task_id, evaluation["critical"]["critical_operation_findings"]) if execute else {}
        return {"ok": False, "status": "APPROVAL_REQUIRED", "evaluation": evaluation, "marked": marked}
    if cfg["production_deploy_requires_user_approval_for_normal_app_changes"]:
        return {"ok": False, "status": "POLICY_REQUIRES_USER_APPROVAL", "evaluation": evaluation}
    if not cfg["production_deploy_allowed_when_all_gates_pass"]:
        return {"ok": False, "status": "AUTONOMOUS_PRODUCTION_DISABLED", "evaluation": evaluation}
    if not evaluation["ready_for_deploy_gate"] and not evaluation["production_deployed"]:
        return {"ok": False, "status": "TASK_NOT_READY_FOR_DEPLOY", "evaluation": evaluation}

    readiness = run_readiness()
    if not readiness["ok"]:
        return {"ok": False, "status": "GATES_NOT_PASS", "evaluation": evaluation, "readiness": readiness}
    if not execute:
        return {"ok": True, "status": "DRY_RUN_GATES_PASS_DEPLOY_ALLOWED", "evaluation": evaluation, "readiness": readiness}

    deploy = dispatch_workflow(DEPLOY_WORKFLOW, wait=wait)
    if not deploy["ok"]:
        return {"ok": False, "status": "DEPLOY_WORKFLOW_FAILED", "evaluation": evaluation, "readiness": readiness, "deploy": deploy}
    smoke_result: dict[str, Any] | None = None
    if smoke:
        smoke_result = dispatch_workflow(SMOKE_WORKFLOW, wait=wait)
        if not smoke_result["ok"]:
            return {
                "ok": False,
                "status": "SMOKE_WORKFLOW_FAILED",
                "evaluation": evaluation,
                "readiness": readiness,
                "deploy": deploy,
                "smoke": smoke_result,
            }
    marked = mark_task_deployed(task_id, deploy.get("run", {}), smoke_result.get("run", {}) if smoke_result else None)
    return {"ok": True, "status": "DEPLOYED", "evaluation": evaluation, "readiness": readiness, "deploy": deploy, "smoke": smoke_result, "marked": marked}


def latest_deploy_candidate() -> str:
    queue = load_queue()
    for task in reversed(queue.get("tasks", [])):
        evaluation = evaluate_task(task)
        if evaluation["ready_for_deploy_gate"] and not evaluation["production_deployed"]:
            return str(task.get("id"))
    return ""


def write_report(payload: dict[str, Any]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    lines = [
        "# CTO Autonomous Delivery Report",
        "",
        f"Generated at: {now()}",
        f"Status: {payload.get('status', 'PASS' if payload.get('ok') else 'FAIL')}",
        f"OK: {payload.get('ok')}",
        "",
        "## Summary",
        f"- Stable: {delivery_status().get('stable')}",
        f"- Max parallel tasks: {policy().get('max_parallel_tasks')}",
        f"- Production allowed when gates pass: {policy().get('production_deploy_allowed_when_all_gates_pass')}",
        f"- Critical operations require approval: true",
    ]
    if payload.get("task_id"):
        lines.append(f"- Task: {payload['task_id']}")
    if payload.get("readiness"):
        lines.append(f"- Readiness: {payload['readiness'].get('status')}")
    (REPORTS / "cto_autonomous_delivery_last_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="CTO autonomous delivery controller")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    evaluate = sub.add_parser("evaluate-task")
    evaluate.add_argument("task_id")
    dispatch = sub.add_parser("dispatch-next")
    dispatch.add_argument("--execute", action="store_true")
    merged = sub.add_parser("mark-merged")
    merged.add_argument("task_id")
    merged.add_argument("--commit", default="")
    deploy = sub.add_parser("deploy-ready")
    deploy.add_argument("task_id")
    deploy.add_argument("--execute", action="store_true")
    deploy.add_argument("--wait", action="store_true")
    deploy.add_argument("--no-smoke", action="store_true")
    latest = sub.add_parser("deploy-latest")
    latest.add_argument("--execute", action="store_true")
    latest.add_argument("--wait", action="store_true")
    latest.add_argument("--no-smoke", action="store_true")
    args = parser.parse_args()

    if args.cmd == "status":
        payload = delivery_status()
    elif args.cmd == "evaluate-task":
        _queue, task = find_task(args.task_id)
        payload = {"ok": bool(task), "task_id": args.task_id, "evaluation": evaluate_task(task) if task else None}
    elif args.cmd == "dispatch-next":
        payload = dispatch_next(execute=args.execute)
    elif args.cmd == "mark-merged":
        payload = mark_task_merged(args.task_id, args.commit)
    elif args.cmd == "deploy-ready":
        payload = deploy_task(args.task_id, execute=args.execute, wait=args.wait, smoke=not args.no_smoke)
    elif args.cmd == "deploy-latest":
        task_id = latest_deploy_candidate()
        payload = (
            deploy_task(task_id, execute=args.execute, wait=args.wait, smoke=not args.no_smoke)
            if task_id
            else {"ok": False, "status": "NO_DEPLOY_CANDIDATE"}
        )
        payload["task_id"] = task_id
    else:
        payload = {"ok": False, "status": "UNKNOWN_COMMAND"}

    write_report(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
