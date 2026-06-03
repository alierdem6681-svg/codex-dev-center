#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
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
        TASK_STATUS_FAILED,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PIPELINE_FAILED,
        TASK_STATUS_PROPOSAL_DONE,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_QUEUED,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_VALIDATION_FAILED,
        atomic_write_json,
        append_audit,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_risk,
        normalize_status,
        redact_sensitive_text,
        utc_now,
    )
except ImportError:
    from critical_operation_policy import approval_required_payload
    from task_status_constants import (
        ACTIVE_TASK_STATUSES,
        TASK_STATUS_APPROVAL_REQUIRED,
        TASK_STATUS_DEPLOYED,
        TASK_STATUS_DONE,
        TASK_STATUS_FAILED,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PIPELINE_FAILED,
        TASK_STATUS_PROPOSAL_DONE,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_QUEUED,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_VALIDATION_FAILED,
        atomic_write_json,
        append_audit,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_risk,
        normalize_status,
        redact_sensitive_text,
        utc_now,
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


def safe_slug(text: Any, limit: int = 56) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", str(text or "").strip()).strip("-").upper()
    return (cleaned[:limit].strip("-") or "BACKLOG")


def choose_worker(queue: dict[str, Any]) -> str:
    workers = ["worker-1", "worker-2", "worker-3", "worker-4"]
    tasks = queue.get("tasks", [])
    active_counts = {worker: 0 for worker in workers}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if not is_worker_eligible_task(task):
            continue
        if normalize_status(task.get("status")) not in ACTIVE_TASK_STATUSES:
            continue
        worker_id = task.get("assigned_worker")
        if worker_id in active_counts:
            active_counts[worker_id] += 1
    return min(workers, key=lambda worker: (active_counts[worker], workers.index(worker)))


def task_flag(task: dict[str, Any], key: str) -> bool:
    value = task.get(key)
    return value is True or str(value).strip().lower() in {"1", "true", "yes"}


def gate_status(value: Any) -> str:
    return str(value or "").strip().upper()


def gate_pass(value: Any) -> bool:
    return gate_status(value) == "PASS"


def active_approval_required_payload(task: dict[str, Any]) -> dict[str, Any]:
    status = normalize_status(task.get("status"))
    raw_findings = task.get("critical_operation_findings") or []
    if isinstance(raw_findings, list):
        findings = [str(item) for item in raw_findings]
    else:
        findings = [str(raw_findings)]
    active = bool(
        task_flag(task, "approval_required")
        or status == TASK_STATUS_APPROVAL_REQUIRED
        or gate_status(task.get("validation_status")) == "APPROVAL_REQUIRED"
    )
    return {
        "approval_required": active,
        "critical_operation_findings": sorted(set(findings)) if active else [],
        "status": "APPROVAL_REQUIRED" if active else "ALLOWED_WITH_GATES",
        "source": "structured_task_state",
    }


def deploy_gate_repo_applied(task: dict[str, Any]) -> bool:
    delivery_level = str(task.get("delivery_level") or "").upper()
    return bool(
        task.get("repo_applied")
        or task.get("branch_merged")
        or task.get("merged_commit")
        or delivery_level in {"READY_FOR_DEPLOY", "MERGED", "DEPLOYED"}
    )


def backlog_candidate_reason(task: dict[str, Any]) -> str:
    status = normalize_status(task.get("status"))
    if task_flag(task, "production_deployed"):
        return "already_deployed"
    if task_flag(task, "backlog_continuation_created"):
        return "continuation_already_created"
    if task.get("parent_task_id") and str(task.get("source", "")).lower() == "cto":
        return "already_child_task"
    if str(task.get("source", "")).lower() == "telegram" and status in ACTIVE_TASK_STATUSES:
        return "active_telegram_parent_reserved_for_cto"
    if status not in {
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PIPELINE_FAILED,
        TASK_STATUS_PROPOSAL_DONE,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_VALIDATION_FAILED,
        TASK_STATUS_DONE,
    }:
        return "status_not_recoverable_for_backlog_pilot"
    risk = normalize_risk(task.get("risk") or task.get("risk_level"))
    if risk not in {"low", "medium"}:
        return "risk_requires_approval"
    critical = approval_required_payload(task_text(task))
    if critical["approval_required"]:
        return "critical_operation_requires_approval"
    return ""


def is_backlog_candidate(task: dict[str, Any]) -> bool:
    return backlog_candidate_reason(task) == ""


def select_backlog_candidate(queue: dict[str, Any]) -> dict[str, Any] | None:
    priorities = {
        TASK_STATUS_FAILED_NO_PROPOSAL: 0,
        TASK_STATUS_FAILED: 1,
        TASK_STATUS_FAILED_TIMEOUT: 2,
        TASK_STATUS_FAILED_RETRYABLE: 3,
        TASK_STATUS_VALIDATION_FAILED: 4,
        TASK_STATUS_PIPELINE_FAILED: 5,
        TASK_STATUS_PROPOSAL_READY: 6,
        TASK_STATUS_PROPOSAL_DONE: 7,
        TASK_STATUS_READY_FOR_VALIDATION: 8,
        TASK_STATUS_DONE: 9,
    }
    candidates = [task for task in queue.get("tasks", []) if isinstance(task, dict) and is_backlog_candidate(task)]
    candidates.sort(
        key=lambda task: (
            0 if normalize_risk(task.get("risk") or task.get("risk_level")) == "low" else 1,
            priorities.get(normalize_status(task.get("status")), 9),
            str(task.get("created_at") or ""),
            str(task.get("id") or ""),
        )
    )
    return candidates[0] if candidates else None


def create_backlog_continuation_task(queue: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    parent_id = str(parent.get("id") or "unknown-parent")
    title = str(parent.get("title") or parent.get("description") or parent_id)
    risk = normalize_risk(parent.get("risk") or parent.get("risk_level"))
    if risk not in {"low", "medium"}:
        risk = "medium"
    task_id = f"CTO-BACKLOG-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}-{safe_slug(title)}"
    parent_status = normalize_status(parent.get("status"))
    description = "\n".join(
        [
            f"Parent task: {parent_id}",
            f"Parent status: {parent_status}",
            "CTO backlog continuation pilot.",
            "Worker görevi: parent rapor/proposal/workspace kayıtlarını güvenli şekilde incele, uygulanabilir küçük bir repo/app iyileştirme önerisi hazırla, test planı ve risk özeti üret.",
            "Ana repo dosyalarını doğrudan değiştirme; production deploy yapma; secret/env/token/private key/IAM/billing/DNS/firewall/database destructive işlemlerine dokunma.",
            "Çıktı beklentisi: PLAN.md, CHANGE_PROPOSAL.md, TEST_PLAN.md, RISK_REVIEW.md, LIVING_DOCS_CHECKLIST.md, WORKER_SUMMARY.md.",
        ]
    )
    child = {
        "id": task_id,
        "parent_task_id": parent_id,
        "parent_status": parent_status,
        "title": "Backlog continuation: " + redact_sensitive_text(title)[:140],
        "description": description,
        "raw_message": "",
        "source": "cto",
        "priority": "normal",
        "status": TASK_STATUS_QUEUED,
        "risk": risk,
        "risk_level": risk,
        "assigned_worker": choose_worker(queue),
        "worker_eligible": True,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "repo_applied": False,
        "staging_deployed": False,
        "production_deployed": False,
        "delivery_level": "BACKLOG_CONTINUATION_QUEUED",
        "cto_orchestrated": True,
        "requires_pipeline_before_deploy": True,
    }
    parent["backlog_continuation_created"] = True
    parent["backlog_continuation_task_id"] = task_id
    parent["backlog_continuation_created_at"] = utc_now()
    parent["updated_at"] = utc_now()
    queue.setdefault("tasks", []).append(child)
    return child


def start_next_backlog(execute: bool = False) -> dict[str, Any]:
    cfg = policy()
    queue = load_queue()
    summary = queue_summary(queue)
    if summary["worker_eligible_active_count"] >= cfg["max_parallel_tasks"]:
        return {"ok": True, "status": "WAIT_ACTIVE_TASK", "summary": summary}

    candidate = select_backlog_candidate(queue)
    if not candidate:
        return {"ok": False, "status": "NO_BACKLOG_CANDIDATE", "summary": summary}

    evaluation = approval_required_payload(task_text(candidate))
    if evaluation["approval_required"]:
        if execute:
            set_task_approval_required(str(candidate.get("id")), evaluation["critical_operation_findings"])
        return {"ok": False, "status": "APPROVAL_REQUIRED", "candidate_id": candidate.get("id"), "evaluation": evaluation}

    if not execute:
        return {
            "ok": True,
            "status": "DRY_RUN_BACKLOG_CANDIDATE_READY",
            "candidate_id": candidate.get("id"),
            "candidate_status": normalize_status(candidate.get("status")),
            "candidate_risk": normalize_risk(candidate.get("risk") or candidate.get("risk_level")),
            "summary": summary,
        }

    child = create_backlog_continuation_task(queue, candidate)
    normalized, changes = normalize_queue_payload(queue)
    atomic_write_json(QUEUE, normalized)
    append_audit(
        ROOT,
        "cto_backlog_continuation_created",
        {
            "parent_task_id": candidate.get("id"),
            "child_task_id": child.get("id"),
            "worker": child.get("assigned_worker"),
            "risk": child.get("risk"),
            "normalization_changes": len(changes),
        },
    )
    state = read_json(DELIVERY_STATE, {})
    state.update(
        {
            "last_backlog_parent_task_id": candidate.get("id"),
            "last_backlog_child_task_id": child.get("id"),
            "last_backlog_dispatch_at": now(),
            "max_parallel_tasks": cfg["max_parallel_tasks"],
        }
    )
    atomic_write_json(DELIVERY_STATE, state)
    dispatched = run([sys.executable, "supervisor/lifecycle_manager.py", "dispatch"], cwd=ROOT, timeout=60)
    return {
        "ok": True,
        "status": "BACKLOG_CONTINUATION_CREATED",
        "parent_task_id": candidate.get("id"),
        "child_task": child,
        "normalization_changes": changes,
        "dispatch": dispatched,
        "summary": queue_summary(),
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
    status = normalize_status(task.get("status"))
    deployable_statuses = {TASK_STATUS_DONE, TASK_STATUS_DEPLOYED}
    critical = active_approval_required_payload(task)
    repo_applied = deploy_gate_repo_applied(task)
    validation_pass = gate_pass(task.get("validation_status"))
    pipeline_pass = gate_pass(task.get("pipeline_status"))
    ready_for_deploy_gate = (
        status in deployable_statuses
        and repo_applied
        and validation_pass
        and pipeline_pass
        and not critical["approval_required"]
    )
    return {
        "task_id": task.get("id"),
        "status": status,
        "risk": task.get("risk") or task.get("risk_level"),
        "assigned_worker": task.get("assigned_worker"),
        "worker_eligible": task.get("worker_eligible"),
        "repo_applied": repo_applied,
        "validation_status": task.get("validation_status"),
        "validation_pass": validation_pass,
        "pipeline_status": task.get("pipeline_status"),
        "pipeline_pass": pipeline_pass,
        "delivery_level": task.get("delivery_level"),
        "critical": critical,
        "ready_for_deploy_gate": ready_for_deploy_gate,
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


def main_head() -> str:
    root = command_root()
    run(["git", "fetch", "origin", "main", "--prune"], cwd=root, timeout=120)
    result = run(["git", "rev-parse", "origin/main"], cwd=root, timeout=30)
    head = result.get("stdout", "").strip()
    return head or git_head()


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
    head = main_head()
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


def mark_task_pr_conflict(task_id: str, pr: dict[str, Any], reason: str) -> dict[str, Any]:
    queue, task = find_task(task_id)
    if not task:
        return {"ok": False, "error": "task_not_found"}
    task["status"] = TASK_STATUS_FAILED_RETRYABLE
    task["delivery_level"] = "PR_CONFLICT"
    task["deployment_status"] = "MERGE_CONFLICT"
    task["merge_blocked"] = True
    task["merge_blocked_reason"] = reason
    task["merge_state_status"] = str(pr.get("mergeStateStatus") or "")
    task["worker_eligible"] = False
    task["backlog_continuation_created"] = True
    if pr.get("number"):
        task["pull_request_number"] = pr.get("number")
    if pr.get("url"):
        task["pull_request_url"] = pr.get("url")
    task["updated_at"] = now()
    atomic_write_json(QUEUE, queue)
    return {"ok": True, "task_id": task_id, "delivery_level": "PR_CONFLICT", "reason": reason}


def mark_task_deploy_retry(task_id: str, failure_status: str) -> dict[str, Any]:
    queue, task = find_task(task_id)
    if not task:
        return {"ok": False, "error": "task_not_found"}
    task["deployment_status"] = "DEPLOY_RETRY_REQUIRED"
    task["deploy_retry_required"] = True
    task["last_deploy_failure_status"] = failure_status
    task["updated_at"] = now()
    atomic_write_json(QUEUE, queue)
    return {"ok": True, "task_id": task_id, "deployment_status": "DEPLOY_RETRY_REQUIRED"}


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
        return {"ok": False, "status": "APPROVAL_REQUIRED", "evaluation": evaluation}
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
    if not smoke:
        marked = mark_task_deploy_retry(task_id, "SMOKE_REQUIRED_FOR_DEPLOYED")
        return {"ok": False, "status": "SMOKE_REQUIRED_FOR_DEPLOYED", "evaluation": evaluation, "readiness": readiness, "marked": marked}

    deploy = dispatch_workflow(DEPLOY_WORKFLOW, wait=wait)
    if not deploy["ok"]:
        marked = mark_task_deploy_retry(task_id, "DEPLOY_WORKFLOW_FAILED")
        return {"ok": False, "status": "DEPLOY_WORKFLOW_FAILED", "evaluation": evaluation, "readiness": readiness, "deploy": deploy, "marked": marked}
    smoke_result: dict[str, Any] | None = None
    if smoke:
        smoke_result = dispatch_workflow(SMOKE_WORKFLOW, wait=wait)
        if not smoke_result["ok"]:
            marked = mark_task_deploy_retry(task_id, "SMOKE_WORKFLOW_FAILED")
            return {
                "ok": False,
                "status": "SMOKE_WORKFLOW_FAILED",
                "evaluation": evaluation,
                "readiness": readiness,
                "deploy": deploy,
                "smoke": smoke_result,
                "marked": marked,
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


def pr_ready_candidate() -> str:
    queue = load_queue()
    for task in reversed(queue.get("tasks", [])):
        critical = active_approval_required_payload(task)
        if critical["approval_required"]:
            continue
        if bool(task.get("production_deployed") or task.get("repo_applied") or task.get("branch_merged")):
            continue
        if str(task.get("delivery_level") or "").upper() != "PR_READY":
            continue
        if not task.get("pull_request_number"):
            continue
        if str(task.get("validation_status") or "").upper() != "PASS":
            continue
        if str(task.get("pipeline_status") or "").upper() != "PASS":
            continue
        return str(task.get("id"))
    return ""


def merge_pr_task(task_id: str, execute: bool = False) -> dict[str, Any]:
    queue, task = find_task(task_id)
    if not task:
        return {"ok": False, "status": "TASK_NOT_FOUND", "task_id": task_id}
    critical = active_approval_required_payload(task)
    if critical["approval_required"]:
        return {"ok": False, "status": "APPROVAL_REQUIRED", "critical": critical}
    if str(task.get("delivery_level") or "").upper() != "PR_READY":
        return {"ok": False, "status": "TASK_NOT_PR_READY", "task_id": task_id}
    if str(task.get("validation_status") or "").upper() != "PASS" or str(task.get("pipeline_status") or "").upper() != "PASS":
        return {"ok": False, "status": "GATES_NOT_PASS", "task_id": task_id}

    number = str(task.get("pull_request_number") or "").strip()
    if not number:
        return {"ok": False, "status": "PR_NUMBER_MISSING", "task_id": task_id}

    view = run(
        ["gh", "pr", "view", number, "--json", "number,url,state,isDraft,mergeStateStatus,headRefName,baseRefName,mergeCommit"],
        cwd=command_root(),
        timeout=60,
    )
    if not view["ok"]:
        return {"ok": False, "status": "PR_VIEW_FAILED", "task_id": task_id, "view": view}
    try:
        pr = json.loads(view["stdout"] or "{}")
    except Exception as exc:
        return {"ok": False, "status": "PR_VIEW_PARSE_FAILED", "task_id": task_id, "error": str(exc)}

    if pr.get("isDraft"):
        return {"ok": False, "status": "PR_IS_DRAFT", "task_id": task_id, "pr": pr}
    if pr.get("baseRefName") and pr.get("baseRefName") != "main":
        return {"ok": False, "status": "PR_BASE_NOT_MAIN", "task_id": task_id, "pr": pr}

    if pr.get("state") == "MERGED":
        merge_commit = ((pr.get("mergeCommit") or {}).get("oid") or "").strip()
        marked = mark_task_merged(task_id, merge_commit) if execute else {}
        return {"ok": True, "status": "ALREADY_MERGED", "task_id": task_id, "pr": pr, "marked": marked}
    if pr.get("state") != "OPEN":
        return {"ok": False, "status": "PR_NOT_OPEN", "task_id": task_id, "pr": pr}
    merge_state = str(pr.get("mergeStateStatus") or "").upper()
    if merge_state and merge_state not in {"CLEAN", "UNKNOWN"}:
        marked = mark_task_pr_conflict(task_id, pr, f"merge_state_{merge_state.lower()}") if execute else {}
        return {"ok": False, "status": "PR_NOT_MERGEABLE", "task_id": task_id, "pr": pr, "marked": marked}
    if not execute:
        return {"ok": True, "status": "DRY_RUN_PR_READY_TO_MERGE", "task_id": task_id, "pr": pr}

    merged = run(
        [
            "gh",
            "pr",
            "merge",
            number,
            "--squash",
            "--delete-branch",
            "--subject",
            f"Worker apply {task_id}",
            "--body",
            "Autonomous CTO merge after worker local gates PASS. Critical infrastructure operations remain blocked.",
        ],
        cwd=command_root(),
        timeout=300,
    )
    if not merged["ok"]:
        merge_error = f"{merged.get('stdout', '')}\n{merged.get('stderr', '')}".lower()
        if "not mergeable" in merge_error or "cannot be cleanly" in merge_error:
            marked = mark_task_pr_conflict(task_id, pr, "merge_command_not_mergeable")
            return {"ok": False, "status": "PR_NOT_MERGEABLE", "task_id": task_id, "pr": pr, "merge": merged, "marked": marked}
        return {"ok": False, "status": "PR_MERGE_FAILED", "task_id": task_id, "pr": pr, "merge": merged}
    time.sleep(3)
    after = run(["gh", "pr", "view", number, "--json", "number,url,state,mergeCommit"], cwd=command_root(), timeout=60)
    merge_commit = ""
    after_payload: dict[str, Any] = {}
    if after["ok"]:
        try:
            after_payload = json.loads(after["stdout"] or "{}")
            merge_commit = ((after_payload.get("mergeCommit") or {}).get("oid") or "").strip()
        except Exception:
            after_payload = {}
    if not merge_commit:
        merge_commit = main_head()
    marked = mark_task_merged(task_id, merge_commit)
    return {
        "ok": True,
        "status": "PR_MERGED",
        "task_id": task_id,
        "pr": pr,
        "merge": merged,
        "after": after_payload,
        "marked": marked,
    }


def finalize_latest(execute: bool = False, wait: bool = False, smoke: bool = True) -> dict[str, Any]:
    task_id = latest_deploy_candidate()
    if task_id:
        payload = deploy_task(task_id, execute=execute, wait=wait, smoke=smoke)
        payload["task_id"] = task_id
        return payload

    pr_task = pr_ready_candidate()
    if not pr_task:
        return {"ok": False, "status": "NO_DELIVERY_CANDIDATE", "task_id": ""}

    merged = merge_pr_task(pr_task, execute=execute)
    if not merged.get("ok"):
        merged["task_id"] = pr_task
        return merged
    if not execute:
        return {"ok": True, "status": "DRY_RUN_PR_READY_TO_MERGE_THEN_DEPLOY", "task_id": pr_task, "merge": merged}
    deployed = deploy_task(pr_task, execute=True, wait=wait, smoke=smoke)
    deployed["merge"] = merged
    deployed["task_id"] = pr_task
    return deployed


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
    backlog = sub.add_parser("start-next-backlog")
    backlog.add_argument("--execute", action="store_true")
    merged = sub.add_parser("mark-merged")
    merged.add_argument("task_id")
    merged.add_argument("--commit", default="")
    merge_pr = sub.add_parser("merge-pr-ready")
    merge_pr.add_argument("task_id")
    merge_pr.add_argument("--execute", action="store_true")
    deploy = sub.add_parser("deploy-ready")
    deploy.add_argument("task_id")
    deploy.add_argument("--execute", action="store_true")
    deploy.add_argument("--wait", action="store_true")
    deploy.add_argument("--no-smoke", action="store_true")
    latest = sub.add_parser("deploy-latest")
    latest.add_argument("--execute", action="store_true")
    latest.add_argument("--wait", action="store_true")
    latest.add_argument("--no-smoke", action="store_true")
    finalize = sub.add_parser("finalize-latest")
    finalize.add_argument("--execute", action="store_true")
    finalize.add_argument("--wait", action="store_true")
    finalize.add_argument("--no-smoke", action="store_true")
    args = parser.parse_args()

    if args.cmd == "status":
        payload = delivery_status()
    elif args.cmd == "evaluate-task":
        _queue, task = find_task(args.task_id)
        payload = {"ok": bool(task), "task_id": args.task_id, "evaluation": evaluate_task(task) if task else None}
    elif args.cmd == "dispatch-next":
        payload = dispatch_next(execute=args.execute)
    elif args.cmd == "start-next-backlog":
        payload = start_next_backlog(execute=args.execute)
    elif args.cmd == "mark-merged":
        payload = mark_task_merged(args.task_id, args.commit)
    elif args.cmd == "merge-pr-ready":
        payload = merge_pr_task(args.task_id, execute=args.execute)
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
    elif args.cmd == "finalize-latest":
        payload = finalize_latest(execute=args.execute, wait=args.wait, smoke=not args.no_smoke)
    else:
        payload = {"ok": False, "status": "UNKNOWN_COMMAND"}

    write_report(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
