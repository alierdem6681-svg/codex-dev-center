#!/usr/bin/env python3
import json, os, time, subprocess
from pathlib import Path
from datetime import datetime, timezone

try:
    from .state_file_lock import state_file_lock
    from .task_status_constants import (
        TASK_STATUS_FAILED,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PENDING,
        TASK_STATUS_PROPOSAL_DONE,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_STALLED,
        atomic_write_json,
        normalize_queue_payload,
        normalize_status,
        read_json as read_state_json,
        worker_block_reason,
    )
except ImportError:
    from state_file_lock import state_file_lock
    from task_status_constants import (
        TASK_STATUS_FAILED,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PENDING,
        TASK_STATUS_PROPOSAL_DONE,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_STALLED,
        atomic_write_json,
        normalize_queue_payload,
        normalize_status,
        read_json as read_state_json,
        worker_block_reason,
    )

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
REPORTS = APP / "reports"
LOGS = APP / "logs"

EXPECTED = [
    "PLAN.md",
    "CHANGE_PROPOSAL.md",
    "TEST_PLAN.md",
    "RISK_REVIEW.md",
    "LIVING_DOCS_CHECKLIST.md",
    "WORKER_SUMMARY.md",
]

RECOVERABLE_FAILURE_STATUSES = {
    TASK_STATUS_FAILED,
    TASK_STATUS_FAILED_NO_PROPOSAL,
    TASK_STATUS_FAILED_RETRYABLE,
    TASK_STATUS_FAILED_TIMEOUT,
    TASK_STATUS_STALLED,
}
RECOVERABLE_OUTPUT_STATUSES = RECOVERABLE_FAILURE_STATUSES | {
    TASK_STATUS_PROPOSAL_DONE,
    TASK_STATUS_PROPOSAL_READY,
    TASK_STATUS_READY_FOR_VALIDATION,
    "RUNNING",
    "ASSIGNED",
}

def now():
    return datetime.now(timezone.utc).isoformat()

def load_json(path, default):
    return read_state_json(Path(path), default)

def save_json(path, data):
    atomic_write_json(Path(path), data)

def safe_id(value):
    out = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(value))
    return out[:120] or "TASK"

def codex_lines():
    try:
        p = subprocess.run(
            ["bash", "-lc", "ps -eo pid,ppid,stat,etime,cmd | grep '[c]odex exec' || true"],
            cwd=str(APP),
            text=True,
            capture_output=True,
            timeout=10,
        )
        return p.stdout.splitlines()
    except Exception:
        return []

def task_has_process(task_id):
    return any(task_id in line for line in codex_lines())

def find_workspace(task_id, worker):
    matches = []
    sid = safe_id(task_id)
    if worker:
        matches += list((APP / "workspaces").glob(f"worker_{worker}_{sid}_*"))
    matches += list((APP / "workspaces").glob(f"worker_*_{sid}_*"))
    return sorted(set(matches))[-1] if matches else None

def created_files(workspace):
    if not workspace or not Path(workspace).exists():
        return []
    return [name for name in EXPECTED if (Path(workspace) / name).exists()]

def tail_text(path, limit=1200):
    try:
        p = Path(path)
        if p.exists():
            return p.read_text(errors="replace")[-limit:]
    except Exception:
        pass
    return ""

def classify_failure(workspace, returncode=None):
    if not workspace:
        return "workspace_missing"
    ws = Path(workspace)
    text = (tail_text(ws / "codex.out") + "\n" + tail_text(ws / "codex.err")).lower()
    if returncode == 124 and not text.strip():
        return "timeout_empty_output"
    if not text.strip():
        return "empty_output"
    if returncode == 124 or "timeout" in text or "return code: 124" in text:
        return "timeout"
    if "permission denied" in text:
        return "permission_denied"
    if "reading additional input from stdin" in text and not tail_text(ws / "codex.out").strip():
        return "codex_no_final_output"
    if len(created_files(ws)) == 0:
        return "no_proposal_files"
    if len(created_files(ws)) < 4:
        return "partial_proposal"
    return "unknown"

def choose_worker(title):
    text = str(title).lower()
    if any(x in text for x in ["dashboard", "panel", "ui", "frontend"]):
        return "worker-2"
    if any(x in text for x in ["watcher", "staging", "rollback", "service", "devops"]):
        return "worker-3"
    if any(x in text for x in ["quality", "test", "risk", "gate", "simulation"]):
        return "worker-4"
    return "worker-1"

def retry_description(task, reason):
    title = task.get("title") or task.get("id")
    return (
        f"Recovery retry for: {title}. "
        f"Previous failure reason: {reason}. "
        "Use smaller scope. In isolated workspace create exactly: "
        "PLAN.md, CHANGE_PROPOSAL.md, TEST_PLAN.md, RISK_REVIEW.md, "
        "LIVING_DOCS_CHECKLIST.md, WORKER_SUMMARY.md. "
        "Do not modify main repo. Do not deploy. Do not use IAM, secret, database, DNS, firewall, billing, or GCloud mutate."
    )

def main():
    qpath = STATE / "task_queue.json"
    wpath = STATE / "workers.json"
    spath = STATE / "system_state.json"

    recovered = 0
    stale = 0
    retry_created = 0
    details = []
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    with state_file_lock(qpath):
        queue = load_json(qpath, {"tasks": []})
        queue, _changes = normalize_queue_payload(queue)
        tasks = queue.setdefault("tasks", [])
        existing = {t.get("id") for t in tasks}

        for task in list(tasks):
            tid = str(task.get("id", ""))

            status = normalize_status(task.get("status", ""))
            if status not in RECOVERABLE_OUTPUT_STATUSES:
                continue
            if worker_block_reason(task):
                continue
            if task.get("parent_task") and str(task.get("source", "")).startswith("cto_"):
                continue
            worker = task.get("assigned_worker")
            title = task.get("title") or tid

            workspace = task.get("workspace") or ""
            if not workspace:
                found = find_workspace(tid, worker)
                workspace = str(found) if found else ""

            files = created_files(workspace)
            active = task_has_process(tid)

            if len(files) >= 4:
                task["status"] = TASK_STATUS_READY_FOR_VALIDATION
                task["result"] = "worker_output_ready_for_validation_not_done"
                task["delivery_level"] = TASK_STATUS_READY_FOR_VALIDATION
                task["workspace"] = workspace
                task["validation_status"] = "PENDING"
                task["pipeline_status"] = "NOT_RUN"
                task["repo_applied"] = False
                task["staging_deployed"] = False
                task["production_deployed"] = False
                task["updated_at"] = now()
                recovered += 1
                details.append(f"{tid}|READY_FOR_VALIDATION|files={len(files)}")
                continue

            if 0 < len(files) < 4:
                task["status"] = TASK_STATUS_PROPOSAL_READY
                task["result"] = "partial_worker_proposal_ready_for_cto_review"
                task["delivery_level"] = TASK_STATUS_PROPOSAL_READY
                task["workspace"] = workspace
                task["validation_status"] = "NOT_READY"
                task["pipeline_status"] = "NOT_RUN"
                task["repo_applied"] = False
                task["staging_deployed"] = False
                task["production_deployed"] = False
                task["updated_at"] = now()
                recovered += 1
                details.append(f"{tid}|PROPOSAL_READY|files={len(files)}")
                continue

            if status in ["RUNNING", "ASSIGNED"] and not active:
                task["status"] = TASK_STATUS_FAILED_NO_PROPOSAL
                task["result"] = "stale_without_active_codex_process"
                task["delivery_level"] = TASK_STATUS_FAILED_NO_PROPOSAL
                task["repo_applied"] = False
                task["staging_deployed"] = False
                task["production_deployed"] = False
                task["updated_at"] = now()
                stale += 1
                status = TASK_STATUS_FAILED_NO_PROPOSAL
                details.append(f"{tid}|STALE_TO_FAILED_NO_PROPOSAL")

            if status in RECOVERABLE_FAILURE_STATUSES:
                reason = classify_failure(workspace, task.get("codex_return_code"))
                task["failure_class"] = reason
                if reason == "timeout_empty_output":
                    task["status"] = TASK_STATUS_FAILED_TIMEOUT
                    task["delivery_level"] = TASK_STATUS_FAILED_TIMEOUT
                else:
                    task["delivery_level"] = TASK_STATUS_FAILED_NO_PROPOSAL
                task["repo_applied"] = False
                task["staging_deployed"] = False
                task["production_deployed"] = False

                retries = int(task.get("recovery_retry_count", 0) or 0)
                if retries < 2 and retry_created < 1:
                    retry_id = f"RECOVERY-{run_id}-{safe_id(tid)}-R{retries + 1}"
                    if retry_id not in existing:
                        retry_worker = choose_worker(title)
                        tasks.append({
                            "id": retry_id,
                            "title": "Recovery: " + str(title)[:80],
                            "description": retry_description(task, reason),
                            "source": "cto_recovery_engine",
                            "parent_task": tid,
                            "status": TASK_STATUS_PENDING,
                            "risk": "medium",
                            "assigned_worker": retry_worker,
                            "created_at": now(),
                            "updated_at": now(),
                            "delivery_level": "BACKLOG",
                            "repo_applied": False,
                            "staging_deployed": False,
                            "production_deployed": False,
                            "failure_class": reason,
                        })
                        existing.add(retry_id)
                        task["recovery_retry_count"] = retries + 1
                        task["recovery_retry_task"] = retry_id
                        retry_created += 1
                        details.append(f"{tid}|RETRY_CREATED|{retry_id}|reason={reason}")

        queue["updated_at"] = now()
        save_json(qpath, queue)

    with state_file_lock(wpath):
        workers = load_json(wpath, {"workers": []})
        for w in workers.get("workers", []):
            if w.get("status") in ["IDLE", "SLEEPING"] and w.get("current_task"):
                w["current_task"] = None
                w["note"] = "recovery_engine_cleanup"
                w["last_seen"] = now()
        save_json(wpath, workers)

    state = load_json(spath, {})
    queue_empty = not tasks

    state.update({
        "phase": "READY_FOR_NEW_TASKS" if queue_empty and state.get("ready_for_new_tasks") else "step_23a_task_recovery_engine_active",
        "system_state": "READY_FOR_NEW_TASKS" if queue_empty and state.get("ready_for_new_tasks") else state.get("system_state"),
        "state": "READY_FOR_NEW_TASKS" if queue_empty and state.get("ready_for_new_tasks") else state.get("state"),
        "task_recovery_engine_active": True,
        "task_recovery_last_run": now(),
        "task_recovery_ready_for_validation_or_proposal_ready": recovered,
        "task_recovery_normalized_stale": stale,
        "task_recovery_retry_created": retry_created,
        "production_deployed": False,
        "repo_changes_applied": False,
        "staging_deployed": False,
        "updated_at": now(),
    })
    save_json(spath, state)

    REPORTS.mkdir(parents=True, exist_ok=True)
    report = REPORTS / "STEP_23A_TASK_RECOVERY_ENGINE_LAST_REPORT.md"
    report.write_text(
        "STEP 23A TASK RECOVERY ENGINE REPORT\n\n"
        f"Ready for validation or proposal ready: {recovered}\n"
        f"Stale normalized: {stale}\n"
        f"Retry tasks created: {retry_created}\n"
        "Production deployed: false\n"
        "Repo applied: false\n"
        "Staging deployed: false\n\n"
        + "\n".join(details[:120]) + "\n",
        encoding="utf-8",
    )

    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "task_recovery_engine.log").open("a", encoding="utf-8") as f:
        f.write(now() + f" recovered={recovered} stale={stale} retry={retry_created}\n")

    if retry_created or stale:
        try:
            subprocess.run(["python3", "supervisor/lifecycle_manager.py", "wake-now"], cwd=str(APP), timeout=30, text=True, capture_output=True)
        except Exception:
            pass

    print("RECOVERY=OK")
    print("READY_FOR_VALIDATION_OR_PROPOSAL_READY=" + str(recovered))
    print("NORMALIZED_STALE=" + str(stale))
    print("RETRY_CREATED=" + str(retry_created))
    print("PHASE=" + state["phase"])

if __name__ == "__main__":
    main()
