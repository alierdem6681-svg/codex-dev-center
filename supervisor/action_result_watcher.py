#!/usr/bin/env python3
import base64
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

try:
    from .state_file_lock import state_file_lock
    from .task_status_constants import (
        TASK_STATUS_DEPLOYED,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_NO_CHANGE,
        TASK_STATUS_READY_FOR_VALIDATION,
        atomic_write_json,
        normalize_queue_payload,
        normalize_status,
        read_json as read_state_json,
    )
except ImportError:
    from state_file_lock import state_file_lock
    from task_status_constants import (
        TASK_STATUS_DEPLOYED,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_NO_CHANGE,
        TASK_STATUS_READY_FOR_VALIDATION,
        atomic_write_json,
        normalize_queue_payload,
        normalize_status,
        read_json as read_state_json,
    )

PROJECT_ID = "eterna-498108"
APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
REPORTS = APP / "reports"

EXPECTED = [
    "PLAN.md",
    "CHANGE_PROPOSAL.md",
    "TEST_PLAN.md",
    "RISK_REVIEW.md",
    "LIVING_DOCS_CHECKLIST.md",
    "WORKER_SUMMARY.md",
]

ACTION_WATCHER_TERMINAL_SKIP_STATUSES = {
    "ARCHIVED",
    "ARCHIVED_STALE",
    "APPROVAL_REQUIRED",
    "BLOCKED",
    "CANCELLED",
    "CANCELLED_BY_OWNER_CLEANUP",
    "DEPLOYED",
    "DONE",
    "NO_CHANGE",
}

REPO_APPLY_NO_CHANGE_RESULTS = {
    "repo_apply_worker_failed_without_changes",
    "repo_apply_worker_completed_without_changes_noop",
    "repo_apply_worker_no_changes_after_nonzero_terminal",
    "repo_apply_no_changes_terminal_reconciled",
}

def now():
    return datetime.now(timezone.utc).isoformat()

def read_json(path, default):
    return read_state_json(Path(path), default)

def write_json(path, data):
    atomic_write_json(Path(path), data)

def metadata_token():
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())["access_token"]

def secret_value(name):
    token = metadata_token()
    url = f"https://secretmanager.googleapis.com/v1/projects/{PROJECT_ID}/secrets/{name}/versions/latest:access"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    return base64.b64decode(data["payload"]["data"]).decode().strip()

def send_message(text):
    try:
        token = secret_value("codex-telegram-bot-token")
        chat_id = secret_value("codex-telegram-chat-id")
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": text[:3900],
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot" + token + "/sendMessage",
            data=data,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as e:
        with (LOGS / "action_result_watcher.log").open("a", encoding="utf-8") as f:
            f.write(now() + " telegram_error=" + str(e)[:300] + "\n")
        return False

def safe_id(task_id):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in task_id)[:120]

def find_workspace(task_id, worker):
    sid = safe_id(task_id)
    patterns = []
    if worker:
        patterns.append(f"worker_{worker}_{sid}_*")
    patterns.append(f"worker_*_{sid}_*")
    matches = []
    for pattern in patterns:
        matches += list((APP / "workspaces").glob(pattern))
    return sorted(set(matches))[-1] if matches else None

def run_key(task_id):
    m = re.match(r"^(CTO-ACTION-\d{8}-\d{6})-", task_id or "")
    return m.group(1) if m else None

def is_deployed_record(task):
    status = normalize_status(task.get("status"))
    delivery_level = normalize_status(task.get("delivery_level"))
    deployment_status = str(task.get("deployment_status") or "").upper()
    return (
        status == TASK_STATUS_DEPLOYED
        or delivery_level == TASK_STATUS_DEPLOYED
        or deployment_status in {"DEPLOYED", "LIVE"}
        or task.get("production_deployed") is True
    )


def is_pr_ready_repo_apply_record(task):
    result = str(task.get("result") or "")
    delivery_level = str(task.get("delivery_level") or "").upper()
    return (
        bool(task.get("pull_request_url"))
        or result == "repo_apply_pr_ready_pipeline_passed"
        or delivery_level == "PR_READY"
    )


def should_skip_action_result_task(task):
    status = normalize_status(task.get("status"))
    result = str(task.get("result") or "").lower()
    return (
        status in ACTION_WATCHER_TERMINAL_SKIP_STATUSES
        or result.startswith("cancelled_")
        or bool(task.get("misroute_cancelled_by"))
    )


def task_children(tasks, parent_id):
    children = []
    for task in tasks:
        if str(task.get("parent_task") or "") == parent_id or str(task.get("parent_task_id") or "") == parent_id:
            children.append(task)
    return children


def has_no_commit_files(task):
    commit_files = task.get("commit_files")
    if isinstance(commit_files, list):
        return len(commit_files) == 0
    changed_files = task.get("changed_files")
    if isinstance(changed_files, list):
        return len(changed_files) == 0
    outcome = task.get("repo_apply_outcome")
    if isinstance(outcome, dict) and "changed_paths_count" in outcome:
        try:
            return int(outcome.get("changed_paths_count") or 0) == 0
        except Exception:
            return False
    return False


def no_change_repo_apply_child(tasks, parent_id):
    for child in task_children(tasks, parent_id):
        status = normalize_status(child.get("status"))
        result = str(child.get("result") or "")
        child_id = str(child.get("id") or "")
        mode = str(child.get("execution_mode") or child.get("dispatcher_mode") or "").lower()
        is_apply = child_id.startswith("CTO-APPLY-") or mode in {"repo_apply", "apply", "implementation"}
        if status == TASK_STATUS_NO_CHANGE and is_apply:
            return child
        if is_apply and result in REPO_APPLY_NO_CHANGE_RESULTS and has_no_commit_files(child):
            return child
    return None


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    qpath = STATE / "task_queue.json"
    ready_for_validation = 0
    failed_no_proposal = 0
    running = 0
    deployed_preserved = 0
    details = []
    with state_file_lock(qpath):
        q = read_json(qpath, {"tasks": []})
        q, _changes = normalize_queue_payload(q)
        tasks = q.get("tasks", [])
        action_tasks = [t for t in tasks if str(t.get("id", "")).startswith("CTO-ACTION-")]

        if not action_tasks:
            print("WATCHER=NO_ACTION_TASKS")
            return 0

        keys = [run_key(t.get("id")) for t in action_tasks if run_key(t.get("id"))]
        latest_key = sorted(keys)[-1] if keys else None
        current = [t for t in action_tasks if run_key(t.get("id")) == latest_key] if latest_key else action_tasks[-10:]
        current_ids = {t.get("id") for t in current}

        for t in current:
            tid = t.get("id")
            worker = t.get("assigned_worker")
            ws = t.get("workspace") or ""
            if not ws:
                found = find_workspace(tid, worker)
                ws = str(found) if found else ""

            created = 0
            if ws and Path(ws).exists():
                created = sum(1 for x in EXPECTED if (Path(ws) / x).exists())

            status = normalize_status(t.get("status"))

            if should_skip_action_result_task(t):
                details.append(f"{tid}: TERMINAL_SKIP")
                continue

            if is_deployed_record(t):
                deployed_preserved += 1
                details.append(f"{tid}: DEPLOYED_PRESERVED")
                continue

            no_change_child = no_change_repo_apply_child(tasks, str(tid))
            if no_change_child:
                t["status"] = TASK_STATUS_NO_CHANGE
                t["result"] = "child_repo_apply_no_change_terminal"
                t["delivery_level"] = TASK_STATUS_NO_CHANGE
                t["validation_status"] = "NO_CHANGE"
                t["pipeline_status"] = "NOT_REQUIRED"
                t["repo_applied"] = False
                t["staging_deployed"] = False
                t["production_deployed"] = False
                t["active_child_task_id"] = no_change_child.get("id")
                t["updated_at"] = now()
                details.append(f"{tid}: NO_CHANGE_CHILD {no_change_child.get('id')}")
                continue

            if is_pr_ready_repo_apply_record(t):
                t["status"] = "DONE"
                t["result"] = "repo_apply_pr_ready_pipeline_passed"
                t["delivery_level"] = "PR_READY"
                t["validation_status"] = t.get("validation_status") or "PASS"
                t["pipeline_status"] = t.get("pipeline_status") or "PASS"
                t["repo_applied"] = False
                t["staging_deployed"] = False
                t["production_deployed"] = False
                t["updated_at"] = now()
                details.append(f"{tid}: PR_READY_PRESERVED")
                continue

            if created >= 4:
                t["status"] = TASK_STATUS_READY_FOR_VALIDATION
                t["result"] = "worker_output_ready_for_validation_not_done"
                t["delivery_level"] = TASK_STATUS_READY_FOR_VALIDATION
                t["validation_status"] = "PENDING"
                t["pipeline_status"] = "NOT_RUN"
                t["repo_applied"] = False
                t["staging_deployed"] = False
                t["production_deployed"] = False
                t["workspace"] = ws
                t["updated_at"] = now()
                ready_for_validation += 1

                report_path = REPORTS / f"{tid}_{worker}_READY_FOR_VALIDATION_REPORT.md"
                report_path.write_text(
                    "ACTION TASK READY FOR VALIDATION REPORT\n\n"
                    f"Task: {tid}\n"
                    f"Worker: {worker}\n"
                    f"Workspace: {ws}\n"
                    f"Created files: {created}/6\n"
                    "Validation status: PENDING\n"
                    "Pipeline status: NOT_RUN\n"
                    "Repo applied: false\n"
                    "Staging deployed: false\n"
                    "Production deployed: false\n",
                    encoding="utf-8"
                )
                t["report_path"] = str(report_path)
                details.append(f"{tid}: READY_FOR_VALIDATION ({created}/6)")
            elif status in ["RUNNING", "ASSIGNED", "PENDING", "QUEUED"]:
                running += 1
                details.append(f"{tid}: {status} ({created}/6)")
            else:
                t["status"] = TASK_STATUS_FAILED_NO_PROPOSAL
                t["result"] = "failed_no_proposal_output"
                t["delivery_level"] = TASK_STATUS_FAILED_NO_PROPOSAL
                t["repo_applied"] = False
                t["staging_deployed"] = False
                t["production_deployed"] = False
                t["updated_at"] = now()
                failed_no_proposal += 1
                details.append(f"{tid}: FAILED_NO_PROPOSAL ({created}/6)")

        q["updated_at"] = now()
        write_json(qpath, q)

    # Worker state temizliği: running iş yoksa idle göster.
    wpath = STATE / "workers.json"
    with state_file_lock(wpath):
        workers = read_json(wpath, {"workers": []})
        if running == 0:
            for w in workers.get("workers", []):
                if w.get("current_task") in current_ids:
                    w["status"] = "IDLE"
                    w["current_task"] = None
                    w["note"] = "action_watcher_reconciled"
                    w["last_seen"] = now()
            write_json(wpath, workers)

    spath = STATE / "system_state.json"
    state = read_json(spath, {})
    state.update({
        "phase": "step_22b_action_result_watcher_active",
        "action_result_watcher_active": True,
        "latest_action_run": latest_key,
        "latest_action_ready_for_validation": ready_for_validation,
        "latest_action_failed_no_proposal": failed_no_proposal,
        "latest_action_running": running,
        "latest_action_deployed_preserved": deployed_preserved,
        "production_deploy_requires_explicit_approval": False,
        "production_deploy_allowed_when_all_gates_pass": True,
        "updated_at": now(),
    })
    write_json(spath, state)

    report = REPORTS / "STEP_22B_ACTION_WATCHER_LAST_REPORT.md"
    report.write_text(
        "STEP 22B ACTION WATCHER REPORT\n\n"
        f"Run: {latest_key}\n"
        f"Ready for validation: {ready_for_validation}\n"
        f"Failed no proposal: {failed_no_proposal}\n"
        f"Running: {running}\n"
        f"Deployed preserved: {deployed_preserved}\n"
        "Production state: unchanged\n\n"
        + "\n".join(details) + "\n",
        encoding="utf-8"
    )

    # Tekrar tekrar spam atmasın.
    notify_marker = STATE / "action_watcher_last_notified.txt"
    previous = notify_marker.read_text().strip() if notify_marker.exists() else ""
    signature = f"{latest_key}|{ready_for_validation}|{failed_no_proposal}|{running}"

    if running == 0 and (ready_for_validation or failed_no_proposal) and previous != signature:
        text = (
            "CTO Action görev özeti:\n\n"
            f"Run: {latest_key}\n"
            f"Doğrulama bekleyen: {ready_for_validation}\n"
            f"Proposal üretemeyen: {failed_no_proposal}\n"
            f"Devam eden: {running}\n\n"
            "Production yapılmadı.\n"
            "Ana repo değişikliği yapılmadı.\n"
            "Sonraki adım: Proposal çıktılarına göre Controlled Apply + Quality Gate planı."
        )
        send_message(text)
        notify_marker.write_text(signature)

    with (LOGS / "action_result_watcher.log").open("a", encoding="utf-8") as f:
        f.write(now() + f" run={latest_key} ready_for_validation={ready_for_validation} failed={failed_no_proposal} running={running}\n")

    print("WATCHER=OK")
    print("RUN=" + str(latest_key))
    print("READY_FOR_VALIDATION=" + str(ready_for_validation))
    print("FAILED_NO_PROPOSAL=" + str(failed_no_proposal))
    print("RUNNING=" + str(running))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
