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
ACTIVE_WORKFLOW_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}
SUCCESSFUL_WORKFLOW_STATUS = "completed"
SUCCESSFUL_WORKFLOW_CONCLUSION = "success"
MERGE_FAILURE_CONFLICT_MARKERS = (
    "not mergeable",
    "cannot be cleanly",
    "merge conflict",
    "conflict",
    "dirty",
)


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
        "local_vm_deploy_fallback_enabled": bool(
            task_flag(deploy, "local_vm_deploy_fallback_enabled")
            or task_flag(production, "local_vm_deploy_fallback_enabled")
            or task_flag({"env": os.environ.get("CODEX_LOCAL_DEPLOY_FALLBACK")}, "env")
        ),
        "local_vm_deploy_fallback_allowed_actor": str(
            deploy.get("local_vm_deploy_fallback_allowed_actor")
            or production.get("local_vm_deploy_fallback_allowed_actor")
            or "cto_finalizer"
        ),
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


def local_deploy_fallback_enabled() -> bool:
    cfg = policy()
    actor = os.environ.get("CODEX_DEPLOY_ACTOR", "").strip()
    allowed_actor = str(cfg.get("local_vm_deploy_fallback_allowed_actor") or "cto_finalizer")
    return bool(
        cfg.get("local_vm_deploy_fallback_enabled")
        and (task_flag({"env": os.environ.get("CODEX_LOCAL_DEPLOY_FALLBACK")}, "env") or not actor or actor == allowed_actor)
    )


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
    task_id = str(task.get("id") or "")
    root_task_id = str(task.get("root_task_id") or task_id)
    result = str(task.get("result") or "").lower()
    if task.get("final_reconcile") or task.get("superseded_by_deploy"):
        return "superseded_or_reconciled_task"
    if "superseded" in result or result.startswith("cancelled_scope_guard"):
        return "superseded_or_scope_cancelled_task"
    if task_id.startswith("CTO-ACTION-20260604-140243-") or root_task_id.startswith("CTO-ACTION-20260604-140243-"):
        return "duplicate_observed_issue_batch_superseded"
    if task_flag(task, "production_deployed"):
        return "already_deployed"
    if task_flag(task, "backlog_continuation_created"):
        return "continuation_already_created"
    if task.get("repo_apply_child"):
        return "repo_apply_child_already_created"
    if task.get("backlog_dispatcher_child"):
        return "backlog_dispatcher_child_already_created"
    if str(task.get("source", "")).lower() == "cto_backlog_dispatcher":
        return "backlog_dispatcher_child_not_backlog_candidate"
    if task.get("parent_task_id") and str(task.get("source", "")).lower() == "cto":
        return "already_child_task"
    if str(task.get("source", "")).lower() == "telegram" and status in ACTIVE_TASK_STATUSES:
        return "active_telegram_parent_reserved_for_cto"
    if status == TASK_STATUS_DONE:
        return "done_task_not_backlog_candidate"
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
    }:
        return "status_not_recoverable_for_backlog_pilot"
    if status == TASK_STATUS_PIPELINE_FAILED and (
        task.get("parent_task")
        or task.get("parent_task_id")
        or str(task.get("source") or "").lower() == "cto_backlog_dispatcher"
        or str(task.get("id") or "").startswith("CTO-APPLY-")
    ):
        return "pipeline_failed_requires_root_cause_mode"
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


def root_cause_mode_status(queue: dict[str, Any] | None = None) -> dict[str, Any]:
    queue = queue or load_queue()
    tasks = [task for task in queue.get("tasks", []) if isinstance(task, dict)]
    deploy_failure_statuses = {
        "DEPLOY_WORKFLOW_FAILED",
        "SMOKE_WORKFLOW_FAILED",
        "LOCAL_DEPLOY_FALLBACK_FAILED",
        "FAILED_PRODUCTION",
        "FAILED_HEALTH_CHECK",
        "DEPLOY_WORKFLOW_REQUIRED",
    }
    deploy_retry_tasks = []
    pipeline_failed_children = []
    delivery_ready_tasks = []
    for task in tasks:
        if task_flag(task, "production_deployed") or normalize_status(task.get("status")) == TASK_STATUS_DEPLOYED:
            continue
        deployment_status = str(task.get("deployment_status") or "").upper()
        failure_status = str(task.get("last_deploy_failure_status") or "").upper()
        delivery_level = str(task.get("delivery_level") or "").upper()
        if task_flag(task, "deploy_retry_required") or deployment_status == "DEPLOY_RETRY_REQUIRED" or failure_status in deploy_failure_statuses:
            deploy_retry_tasks.append(str(task.get("id") or ""))
        if normalize_status(task.get("status")) == TASK_STATUS_PIPELINE_FAILED and (
            task.get("parent_task")
            or task.get("parent_task_id")
            or str(task.get("source") or "").lower() == "cto_backlog_dispatcher"
            or str(task.get("id") or "").startswith("CTO-APPLY-")
        ):
            pipeline_failed_children.append(str(task.get("id") or ""))
        if delivery_level in {"PR_READY", "READY_FOR_DEPLOY"}:
            delivery_ready_tasks.append(str(task.get("id") or ""))
    active = bool(deploy_retry_tasks or (pipeline_failed_children and delivery_ready_tasks))
    return {
        "ok": True,
        "active": active,
        "status": "ROOT_CAUSE_MODE_ACTIVE" if active else "ROOT_CAUSE_CLEAR",
        "deploy_retry_task_ids": [task_id for task_id in deploy_retry_tasks if task_id],
        "pipeline_failed_child_ids": [task_id for task_id in pipeline_failed_children if task_id],
        "delivery_ready_task_ids": [task_id for task_id in delivery_ready_tasks if task_id],
        "reason": "deploy_or_pipeline_root_cause_required" if active else "no_root_cause_blocker",
    }


def _is_pipeline_failed_child(task: dict[str, Any]) -> bool:
    return normalize_status(task.get("status")) == TASK_STATUS_PIPELINE_FAILED and (
        task.get("parent_task")
        or task.get("parent_task_id")
        or str(task.get("source") or "").lower() == "cto_backlog_dispatcher"
        or str(task.get("id") or "").startswith("CTO-APPLY-")
    )


def _first_failed_pipeline_gate(task: dict[str, Any]) -> dict[str, Any] | None:
    results = task.get("pipeline_results")
    if not isinstance(results, list):
        return None
    for item in results:
        if isinstance(item, dict) and not item.get("ok"):
            return item
    return None


def _pipeline_failure_root_cause(task: dict[str, Any]) -> str:
    explicit = str(task.get("failure_class") or task.get("last_error_code") or "").strip()
    if explicit:
        return redact_sensitive_text(explicit)[:120]
    if not (task.get("workspace") or task.get("repo_clone") or task.get("repo_worktree")):
        return "workspace_missing"
    failed_gate = _first_failed_pipeline_gate(task)
    if failed_gate:
        gate_name = str(failed_gate.get("name") or "pipeline_gate").strip() or "pipeline_gate"
        return f"{gate_name}_failed"[:120]
    return redact_sensitive_text(str(task.get("result") or "pipeline_failed"))[:120]


def _pipeline_failure_last_error(task: dict[str, Any]) -> str:
    failed_gate = _first_failed_pipeline_gate(task)
    if failed_gate:
        gate_name = str(failed_gate.get("name") or "pipeline_gate").strip() or "pipeline_gate"
        return redact_sensitive_text(f"{gate_name}: returncode={failed_gate.get('returncode', '-')}"[:240])
    for key in ("last_error_code", "result", "failure_class"):
        value = str(task.get(key) or "").strip()
        if value:
            return redact_sensitive_text(value[:240])
    return "pipeline_failed"


def _pipeline_failure_recommendation(root_cause: str) -> str:
    normalized = root_cause.lower()
    if "workspace_missing" in normalized:
        return "Verify isolated workspace/repo clone creation and record the workspace path before rerun; fail early if the path is missing."
    if "timeout" in normalized:
        return "Rerun with smaller scope and inspect the stalled gate before retrying the same apply branch."
    if "secret" in normalized or "unsafe" in normalized or "approval" in normalized:
        return "Do not retry automatically; keep the task blocked for policy review."
    return "Inspect the failed local gate, fix the smallest affected repo path, then rerun validation before retry."


def _pipeline_failure_retryable(root_cause: str) -> bool:
    normalized = root_cause.lower()
    if any(blocker in normalized for blocker in ("secret", "unsafe", "approval", "critical")):
        return False
    return True


def pipeline_failed_root_cause_report(queue: dict[str, Any] | None = None) -> dict[str, Any]:
    if queue is None:
        queue = load_queue()
    tasks = [task for task in queue.get("tasks", []) if isinstance(task, dict)]
    failures = []
    for task in tasks:
        if not _is_pipeline_failed_child(task):
            continue
        root_cause = _pipeline_failure_root_cause(task)
        failures.append(
            {
                "task_id": str(task.get("id") or ""),
                "parent_task_id": str(task.get("parent_task_id") or task.get("parent_task") or ""),
                "root_cause": root_cause,
                "last_error": _pipeline_failure_last_error(task),
                "retryable": _pipeline_failure_retryable(root_cause),
                "recommended_fix": _pipeline_failure_recommendation(root_cause),
                "new_root_task_required": False,
            }
        )
    return {
        "ok": True,
        "status": "ROOT_CAUSE_REPORT" if failures else "NO_PIPELINE_FAILED_CHILD",
        "pipeline_failed_count": len(failures),
        "new_root_task_required": False,
        "failures": failures,
    }


def start_next_backlog(execute: bool = False) -> dict[str, Any]:
    cfg = policy()
    queue = load_queue()
    summary = queue_summary(queue)
    root_cause = root_cause_mode_status(queue)
    if root_cause["active"]:
        if execute:
            state = read_json(DELIVERY_STATE, {})
            state.update(
                {
                    "root_cause_mode_active": True,
                    "root_cause_mode_reason": root_cause["reason"],
                    "last_backlog_dispatch_at": now(),
                }
            )
            atomic_write_json(DELIVERY_STATE, state)
        return {"ok": True, "status": "ROOT_CAUSE_MODE_ACTIVE", "root_cause": root_cause, "summary": summary}
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
    deployment_status = str(task.get("deployment_status") or "").upper()
    deploy_retry_required = task_flag(task, "deploy_retry_required") or deployment_status == "DEPLOY_RETRY_REQUIRED"
    deploy_in_progress = bool(not deploy_retry_required and (task.get("deploy_in_progress") or deployment_status == "DEPLOY_IN_PROGRESS"))
    ready_for_deploy_gate = (
        status in deployable_statuses
        and repo_applied
        and validation_pass
        and pipeline_pass
        and not critical["approval_required"]
        and not deploy_in_progress
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
        "deploy_in_progress": deploy_in_progress,
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


def fast_forward_main_after_merge() -> dict[str, Any]:
    root = command_root()
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, timeout=30)
    status = run(["git", "status", "--porcelain"], cwd=root, timeout=30)
    if not branch.get("ok") or not status.get("ok"):
        return {"ok": False, "status": "GIT_STATUS_UNAVAILABLE", "branch": branch, "worktree_status": status}
    dirty = [line for line in status.get("stdout", "").splitlines() if line.strip()]
    if dirty:
        return {"ok": False, "status": "GIT_WORKTREE_DIRTY", "dirty_files": dirty[:20]}
    if branch.get("stdout", "").strip() != "main":
        return {"ok": False, "status": "GIT_BRANCH_NOT_MAIN", "branch": branch.get("stdout", "").strip()}
    fetch = run(["git", "fetch", "origin", "main", "--prune"], cwd=root, timeout=120)
    if not fetch.get("ok"):
        return {"ok": False, "status": "GIT_FETCH_FAILED", "fetch": fetch}
    before = run(["git", "rev-parse", "HEAD"], cwd=root, timeout=30)
    ff = run(["git", "merge", "--ff-only", "origin/main"], cwd=root, timeout=120)
    after = run(["git", "rev-parse", "HEAD"], cwd=root, timeout=30)
    return {
        "ok": bool(ff.get("ok")),
        "status": "FAST_FORWARDED" if before.get("stdout") != after.get("stdout") else "ALREADY_UP_TO_DATE",
        "before": before.get("stdout", "").strip(),
        "after": after.get("stdout", "").strip(),
        "fetch": fetch,
        "merge": ff,
    }


def workflow_runs(workflow: str) -> dict[str, Any]:
    args = [
        "gh",
        "run",
        "list",
        "--workflow",
        workflow,
        "--limit",
        "30",
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
    return {"ok": True, "runs": runs}


def latest_run(workflow: str, head_sha: str = "") -> dict[str, Any]:
    payload = workflow_runs(workflow)
    if not payload["ok"]:
        return payload
    runs = payload["runs"]
    for item in runs:
        if not head_sha or item.get("headSha") == head_sha:
            return {"ok": True, "run": item}
    return {"ok": False, "error": "run_not_found", "runs": runs[:3]}


def active_run(workflow: str, head_sha: str) -> dict[str, Any]:
    payload = workflow_runs(workflow)
    if not payload["ok"]:
        return payload
    for item in payload["runs"]:
        if item.get("headSha") == head_sha and str(item.get("status") or "").lower() in ACTIVE_WORKFLOW_STATUSES:
            return {"ok": True, "run": item}
    return {"ok": False, "error": "active_run_not_found"}


def successful_run(workflow: str, head_sha: str) -> dict[str, Any]:
    payload = workflow_runs(workflow)
    if not payload["ok"]:
        return payload
    for item in payload["runs"]:
        if (
            item.get("headSha") == head_sha
            and str(item.get("status") or "").lower() == SUCCESSFUL_WORKFLOW_STATUS
            and str(item.get("conclusion") or "").lower() == SUCCESSFUL_WORKFLOW_CONCLUSION
        ):
            return {"ok": True, "run": item}
    return {"ok": False, "error": "successful_run_not_found"}


def merge_failure_conflict_reason(result: dict[str, Any], pr: dict[str, Any]) -> str:
    merge_state = str(pr.get("mergeStateStatus") or "").upper()
    if merge_state and merge_state not in {"CLEAN", "UNKNOWN"}:
        return f"merge_state_{merge_state.lower()}"
    text = "\n".join(str(result.get(key) or "") for key in ("stdout", "stderr", "cmd")).lower()
    if any(marker in text for marker in MERGE_FAILURE_CONFLICT_MARKERS):
        return "merge_command_not_mergeable"
    if "exit status 1" in text and ("merge" in text or "pull request" in text):
        return "merge_command_git_exit_status_1"
    return ""


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
    success = successful_run(workflow, head)
    if success.get("ok"):
        return {
            "ok": True,
            "status": "WORKFLOW_SUCCESS_REUSED",
            "run": success["run"],
            "deduped": True,
            "dedupe_reason": "successful_run_for_origin_main_commit",
        }
    existing = active_run(workflow, head)
    if existing.get("ok"):
        run_id = str(existing["run"].get("databaseId"))
        payload = {"ok": True, "status": "WORKFLOW_ALREADY_RUNNING", "run": existing["run"], "deduped": True}
        if wait:
            payload["wait"] = wait_run(run_id)
            payload["ok"] = bool(payload["wait"].get("ok"))
            if payload["wait"].get("run"):
                payload["run"] = payload["wait"]["run"]
            payload["status"] = "WORKFLOW_ALREADY_RUNNING_COMPLETED" if payload["ok"] else "WORKFLOW_ALREADY_RUNNING_FAILED"
        return payload
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
    payload = {"ok": True, "status": "WORKFLOW_DISPATCHED", "dispatch": dispatched, "run": latest["run"]}
    if wait:
        payload["wait"] = wait_run(run_id)
        payload["ok"] = bool(payload["wait"].get("ok"))
        if payload["wait"].get("run"):
            payload["run"] = payload["wait"]["run"]
        payload["status"] = "WORKFLOW_COMPLETED" if payload["ok"] else "WORKFLOW_FAILED"
    return payload


def workflow_run_successful(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    run_payload = payload.get("run") or {}
    return (
        str(run_payload.get("status") or "").lower() == SUCCESSFUL_WORKFLOW_STATUS
        and str(run_payload.get("conclusion") or "").lower() == SUCCESSFUL_WORKFLOW_CONCLUSION
    )


def record_task_workflow_run(task_id: str, kind: str, run_payload: dict[str, Any], result_status: str = "") -> dict[str, Any]:
    queue, task = find_task(task_id)
    if not task:
        return {"ok": False, "error": "task_not_found"}
    prefix = "deploy" if kind == "deploy" else "smoke"
    run_id = str(run_payload.get("databaseId") or "")
    run_url = str(run_payload.get("url") or "")
    head_sha = str(run_payload.get("headSha") or "")
    task[f"{prefix}_run_id"] = run_id
    task[f"{prefix}_run_url"] = run_url
    if head_sha:
        task[f"{prefix}_commit"] = head_sha
    task[f"{prefix}_workflow_status"] = str(run_payload.get("status") or "")
    task[f"{prefix}_workflow_conclusion"] = str(run_payload.get("conclusion") or "")
    if result_status:
        task[f"{prefix}_workflow_result"] = result_status
    task["updated_at"] = now()
    atomic_write_json(QUEUE, queue)
    return {"ok": True, "task_id": task_id, "kind": prefix, "run_id": run_id, "run_url": run_url}


def mark_task_deployed(task_id: str, deploy_run: dict[str, Any], smoke_run: dict[str, Any] | None = None) -> dict[str, Any]:
    queue, task = find_task(task_id)
    if not task:
        return {"ok": False, "error": "task_not_found"}
    task["status"] = TASK_STATUS_DEPLOYED
    task["production_deployed"] = True
    task["delivery_level"] = "DEPLOYED"
    task["deploy_in_progress"] = False
    task["deploy_retry_required"] = False
    task.pop("last_deploy_failure_status", None)
    task["deployment_status"] = "DEPLOYED"
    task["deploy_run_id"] = str(deploy_run.get("databaseId") or deploy_run.get("run", {}).get("databaseId") or "")
    task["deploy_run_url"] = deploy_run.get("url") or deploy_run.get("run", {}).get("url") or ""
    task["deploy_workflow_status"] = str(deploy_run.get("status") or "")
    task["deploy_workflow_conclusion"] = str(deploy_run.get("conclusion") or "")
    if deploy_run.get("local_vm_fallback"):
        task["local_vm_deploy_fallback_used"] = True
        task["local_vm_deploy_fallback_status"] = str(deploy_run.get("controller_status") or "PASS")
    if deploy_run.get("headSha"):
        task["deploy_commit"] = str(deploy_run.get("headSha"))
    if smoke_run:
        task["smoke_run_id"] = str(smoke_run.get("databaseId") or smoke_run.get("run", {}).get("databaseId") or "")
        task["smoke_run_url"] = smoke_run.get("url") or smoke_run.get("run", {}).get("url") or ""
        task["smoke_workflow_status"] = str(smoke_run.get("status") or "")
        task["smoke_workflow_conclusion"] = str(smoke_run.get("conclusion") or "")
        if smoke_run.get("headSha"):
            task["smoke_commit"] = str(smoke_run.get("headSha"))
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
    task["deploy_in_progress"] = False
    task["deploy_retry_required"] = True
    task["last_deploy_failure_status"] = failure_status
    task["updated_at"] = now()
    atomic_write_json(QUEUE, queue)
    return {"ok": True, "task_id": task_id, "deployment_status": "DEPLOY_RETRY_REQUIRED"}


def mark_task_deploy_in_progress(task_id: str) -> dict[str, Any]:
    queue, task = find_task(task_id)
    if not task:
        return {"ok": False, "error": "task_not_found"}
    task["deploy_in_progress"] = True
    task["deployment_status"] = "DEPLOY_IN_PROGRESS"
    task["updated_at"] = now()
    atomic_write_json(QUEUE, queue)
    return {"ok": True, "task_id": task_id, "deployment_status": "DEPLOY_IN_PROGRESS"}


def local_deploy_run_payload(controller_payload: dict[str, Any]) -> dict[str, Any]:
    head = main_head()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    ok = bool(controller_payload.get("ok") and controller_payload.get("status") == "PASS")
    return {
        "databaseId": f"local-{stamp}",
        "url": "",
        "headSha": head,
        "status": "completed",
        "conclusion": "success" if ok else "failure",
        "local_vm_fallback": True,
        "controller_status": str(controller_payload.get("status") or "UNKNOWN"),
    }


def run_local_deploy_fallback(task: dict[str, Any]) -> dict[str, Any]:
    if not local_deploy_fallback_enabled():
        return {"ok": False, "status": "LOCAL_VM_FALLBACK_DISABLED"}
    env = os.environ.copy()
    env.update(
        {
            "CODEX_LOCAL_DEPLOY_FALLBACK": "1",
            "CODEX_DEPLOY_ACTOR": "cto_finalizer",
            "CODEX_PRODUCTION_DEPLOY_DESCRIPTION": f"cto_finalizer_local_fallback task_id={redact_sensitive_text(task.get('id', ''))[:160]}",
        }
    )
    try:
        proc = subprocess.run(
            [sys.executable, "supervisor/production_deploy_controller.py", "start", "--auto"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=1800,
            env=env,
        )
    except Exception as exc:
        return {"ok": False, "status": "LOCAL_VM_FALLBACK_EXCEPTION", "error": str(exc)}
    controller_payload: dict[str, Any] = {}
    if proc.stdout.strip().startswith("{"):
        try:
            controller_payload = json.loads(proc.stdout)
        except Exception:
            controller_payload = {}
    ok = proc.returncode == 0 and bool(controller_payload.get("ok")) and controller_payload.get("status") == "PASS"
    return {
        "ok": ok,
        "status": "LOCAL_VM_FALLBACK_DEPLOYED" if ok else "LOCAL_DEPLOY_FALLBACK_FAILED",
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
        "controller": controller_payload,
        "run": local_deploy_run_payload(controller_payload),
    }


def deploy_with_local_fallback(task_id: str, task: dict[str, Any], evaluation: dict[str, Any], readiness: dict[str, Any], in_progress: dict[str, Any], reason: str) -> dict[str, Any]:
    local_fallback = run_local_deploy_fallback(task)
    if local_fallback.get("ok"):
        marked = mark_task_deployed(task_id, local_fallback.get("run", {}), None)
        return {
            "ok": True,
            "status": "DEPLOYED",
            "deployment_path": reason,
            "evaluation": evaluation,
            "readiness": readiness,
            "local_deploy_fallback": local_fallback,
            "in_progress": in_progress,
            "marked": marked,
        }
    failure_status = str(local_fallback.get("status") or "LOCAL_DEPLOY_FALLBACK_FAILED")
    marked = mark_task_deploy_retry(task_id, failure_status)
    return {
        "ok": False,
        "status": failure_status,
        "deployment_path": reason,
        "evaluation": evaluation,
        "readiness": readiness,
        "local_deploy_fallback": local_fallback,
        "in_progress": in_progress,
        "marked": marked,
    }


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
    if evaluation["production_deployed"]:
        return {"ok": True, "status": "ALREADY_DEPLOYED", "evaluation": evaluation, "task_id": task_id}
    if evaluation["deploy_in_progress"]:
        return {"ok": True, "status": "DEPLOY_IN_PROGRESS", "evaluation": evaluation, "task_id": task_id}
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

    in_progress = mark_task_deploy_in_progress(task_id)
    if task_flag({"env": os.environ.get("CODEX_LOCAL_DEPLOY_FALLBACK")}, "env") and local_deploy_fallback_enabled():
        return deploy_with_local_fallback(
            task_id,
            task,
            evaluation,
            readiness,
            in_progress,
            "local_vm_fallback_requested",
        )
    deploy = dispatch_workflow(DEPLOY_WORKFLOW, wait=wait)
    deploy_record = record_task_workflow_run(task_id, "deploy", deploy.get("run", {}), deploy.get("status", "")) if deploy.get("run") else {}
    if not deploy["ok"]:
        payload = deploy_with_local_fallback(
            task_id,
            task,
            evaluation,
            readiness,
            in_progress,
            "local_vm_fallback_after_workflow_failure",
        )
        payload["deploy"] = deploy
        payload["deploy_record"] = deploy_record
        return payload
    if not workflow_run_successful(deploy):
        return {
            "ok": True,
            "status": "DEPLOY_IN_PROGRESS",
            "evaluation": evaluation,
            "readiness": readiness,
            "deploy": deploy,
            "in_progress": in_progress,
            "deploy_record": deploy_record,
        }
    smoke_result: dict[str, Any] | None = None
    smoke_record: dict[str, Any] = {}
    if smoke:
        smoke_result = dispatch_workflow(SMOKE_WORKFLOW, wait=wait)
        smoke_record = record_task_workflow_run(task_id, "smoke", smoke_result.get("run", {}), smoke_result.get("status", "")) if smoke_result.get("run") else {}
        if not smoke_result["ok"]:
            marked = mark_task_deploy_retry(task_id, "SMOKE_WORKFLOW_FAILED")
            return {
                "ok": False,
                "status": "SMOKE_WORKFLOW_FAILED",
                "evaluation": evaluation,
                "readiness": readiness,
                "deploy": deploy,
                "smoke": smoke_result,
                "in_progress": in_progress,
                "deploy_record": deploy_record,
                "smoke_record": smoke_record,
                "marked": marked,
            }
        if not workflow_run_successful(smoke_result):
            return {
                "ok": True,
                "status": "SMOKE_IN_PROGRESS",
                "evaluation": evaluation,
                "readiness": readiness,
                "deploy": deploy,
                "smoke": smoke_result,
                "in_progress": in_progress,
                "deploy_record": deploy_record,
                "smoke_record": smoke_record,
            }
    marked = mark_task_deployed(task_id, deploy.get("run", {}), smoke_result.get("run", {}) if smoke_result else None)
    return {
        "ok": True,
        "status": "DEPLOYED",
        "evaluation": evaluation,
        "readiness": readiness,
        "deploy": deploy,
        "smoke": smoke_result,
        "in_progress": in_progress,
        "deploy_record": deploy_record,
        "smoke_record": smoke_record,
        "marked": marked,
    }


def latest_deploy_candidate() -> str:
    queue = load_queue()
    for task in reversed(queue.get("tasks", [])):
        evaluation = evaluate_task(task)
        if evaluation["ready_for_deploy_gate"] and not evaluation["production_deployed"]:
            return str(task.get("id"))
    return ""


def pr_ready_candidate() -> str:
    candidates = pr_ready_candidates()
    return candidates[0] if candidates else ""


def pr_ready_candidates() -> list[str]:
    queue = load_queue()
    candidates: list[str] = []
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
        candidates.append(str(task.get("id")))
    return candidates


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
        source_sync = fast_forward_main_after_merge() if execute else {}
        return {"ok": True, "status": "ALREADY_MERGED", "task_id": task_id, "pr": pr, "marked": marked, "source_sync": source_sync}
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
        after_failure = run(
            ["gh", "pr", "view", number, "--json", "number,url,state,isDraft,mergeStateStatus,headRefName,baseRefName,mergeCommit"],
            cwd=command_root(),
            timeout=60,
        )
        after_pr: dict[str, Any] = {}
        if after_failure["ok"]:
            try:
                after_pr = json.loads(after_failure["stdout"] or "{}")
            except Exception:
                after_pr = {}
        if after_pr.get("state") == "MERGED":
            merge_commit = ((after_pr.get("mergeCommit") or {}).get("oid") or "").strip()
            marked = mark_task_merged(task_id, merge_commit)
            source_sync = fast_forward_main_after_merge()
            return {
                "ok": True,
                "status": "ALREADY_MERGED",
                "task_id": task_id,
                "pr": after_pr,
                "merge": merged,
                "after_failure": after_failure,
                "marked": marked,
                "source_sync": source_sync,
            }
        conflict_pr = after_pr or pr
        conflict_reason = merge_failure_conflict_reason(merged, conflict_pr)
        if conflict_reason:
            marked = mark_task_pr_conflict(task_id, conflict_pr, conflict_reason)
            return {
                "ok": False,
                "status": "PR_NOT_MERGEABLE",
                "task_id": task_id,
                "pr": conflict_pr,
                "merge": merged,
                "after_failure": after_failure,
                "marked": marked,
            }
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
    source_sync = fast_forward_main_after_merge()
    return {
        "ok": True,
        "status": "PR_MERGED",
        "task_id": task_id,
        "pr": pr,
        "merge": merged,
        "after": after_payload,
        "marked": marked,
        "source_sync": source_sync,
    }


def finalize_latest(execute: bool = False, wait: bool = False, smoke: bool = True) -> dict[str, Any]:
    task_id = latest_deploy_candidate()
    if task_id:
        payload = deploy_task(task_id, execute=execute, wait=wait, smoke=smoke)
        payload["task_id"] = task_id
        return payload

    skipped: list[dict[str, Any]] = []
    for pr_task in pr_ready_candidates():
        merged = merge_pr_task(pr_task, execute=execute)
        if not merged.get("ok"):
            merged["task_id"] = pr_task
            if merged.get("status") == "PR_NOT_MERGEABLE":
                skipped.append({"task_id": pr_task, "status": merged.get("status"), "pr": merged.get("pr")})
                continue
            merged["skipped"] = skipped
            return merged
        if not execute:
            return {
                "ok": True,
                "status": "DRY_RUN_PR_READY_TO_MERGE_THEN_DEPLOY",
                "task_id": pr_task,
                "merge": merged,
                "skipped": skipped,
            }
        deployed = deploy_task(pr_task, execute=True, wait=wait, smoke=smoke)
        deployed["merge"] = merged
        deployed["task_id"] = pr_task
        deployed["skipped"] = skipped
        return deployed
    return {"ok": False, "status": "NO_DELIVERY_CANDIDATE", "task_id": "", "skipped": skipped}


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
    sub.add_parser("root-cause-status")
    sub.add_parser("root-cause-report")
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
    elif args.cmd == "root-cause-status":
        payload = root_cause_mode_status()
    elif args.cmd == "root-cause-report":
        payload = pipeline_failed_root_cause_report()
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
