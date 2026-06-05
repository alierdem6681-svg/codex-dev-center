#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .critical_operation_policy import critical_operation_findings
    from .state_file_lock import state_file_lock
    from .task_status_constants import (
        TASK_STATUS_APPROVAL_REQUIRED,
        TASK_STATUS_DONE,
        TASK_STATUS_PIPELINE_FAILED,
        TASK_STATUS_PROPOSAL_DONE,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_VALIDATION_FAILED,
        atomic_write_json,
        normalize_queue_payload,
        normalize_status,
        redact_sensitive_text,
        utc_now,
    )
except ImportError:
    from critical_operation_policy import critical_operation_findings
    from state_file_lock import state_file_lock
    from task_status_constants import (
        TASK_STATUS_APPROVAL_REQUIRED,
        TASK_STATUS_DONE,
        TASK_STATUS_PIPELINE_FAILED,
        TASK_STATUS_PROPOSAL_DONE,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_VALIDATION_FAILED,
        atomic_write_json,
        normalize_queue_payload,
        normalize_status,
        redact_sensitive_text,
        utc_now,
    )


APP_DIR = Path(os.environ.get("CODEX_DEV_CENTER_HOME", "/opt/codex-dev-center")).resolve()
STATE_DIR = APP_DIR / "state"
REPORT_DIR = APP_DIR / "reports"
LOG_DIR = APP_DIR / "logs"
WORKSPACES_DIR = APP_DIR / "workspaces"

EXPECTED_WORKER_FILES = [
    "PLAN.md",
    "CHANGE_PROPOSAL.md",
    "TEST_PLAN.md",
    "RISK_REVIEW.md",
    "LIVING_DOCS_CHECKLIST.md",
    "WORKER_SUMMARY.md",
]

MIN_EXPECTED_FILES = 4
DEFAULT_LIMIT = 5

SAFE_POLICY_MARKERS = (
    "do not",
    "dont",
    "don't",
    "not mutate",
    "no mutate",
    "yapma",
    "yapmayacak",
    "yapilmayacak",
    "yapılmayacak",
    "yapilmaz",
    "yapılmaz",
    "yapılamaz",
    "okuma",
    "okunmayacak",
    "gösterme",
    "gosterme",
    "yazma",
    "rotate etme",
    "kapalı",
    "kapali",
    "kapsam disi",
    "kapsam dışı",
    "approval_required",
    "requires_approval",
    "blocked",
    "yasak",
    "forbidden",
    "critical exception",
    "kritik altyapi",
    "kritik altyapı",
    "dokunulmayacak",
    "dokunulmaz",
    "riskler",
    "risk:",
    "high risk",
    "yuksek risk",
    "yüksek risk",
    "riskli",
    "ornek",
    "örnek",
    "example",
    "donmeli",
    "dönmeli",
    "azaltim",
    "azaltım",
    "mitigation",
)


def runtime_paths(runtime: Path) -> dict[str, Path]:
    runtime = runtime.resolve()
    return {
        "root": runtime,
        "queue": runtime / "state" / "task_queue.json",
        "pipeline": runtime / "state" / "production_readiness_status.json",
        "status": runtime / "state" / "task_validation_status.json",
        "report": runtime / "reports" / "task_validation_engine_last_report.md",
        "log": runtime / "logs" / "task_validation_engine.log",
        "workspaces": runtime / "workspaces",
    }


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    return default


def append_log(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_payload = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"created_at": utc_now(), **safe_payload}, ensure_ascii=False, sort_keys=True) + "\n")


def safe_id(value: Any) -> str:
    out = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(value or "TASK"))
    return out[:120] or "TASK"


def find_workspace(runtime: Path, task: dict[str, Any]) -> Path | None:
    workspace = task.get("workspace")
    if workspace and Path(str(workspace)).exists():
        return Path(str(workspace))

    task_id = str(task.get("id") or "")
    worker = task.get("assigned_worker")
    patterns = []
    sid = safe_id(task_id)
    if worker:
        patterns.append(f"worker_{worker}_{sid}_*")
    patterns.append(f"worker_*_{sid}_*")

    matches: list[Path] = []
    workspaces_dir = runtime / "workspaces"
    for pattern in patterns:
        matches.extend(workspaces_dir.glob(pattern))
    return sorted(set(matches))[-1] if matches else None


def created_files(workspace: Path | None) -> list[str]:
    if not workspace or not workspace.exists():
        return []
    return [name for name in EXPECTED_WORKER_FILES if (workspace / name).exists()]


def useful_lines_for_scan(task: dict[str, Any], workspace: Path | None, limit_per_file: int = 12000) -> list[str]:
    lines: list[str] = []
    for key in ("title", "description", "raw_message"):
        value = task.get(key)
        if value:
            lines.extend(str(value).splitlines())

    if workspace and workspace.exists():
        for name in EXPECTED_WORKER_FILES:
            path = workspace / name
            if not path.exists():
                continue
            try:
                lines.extend(path.read_text(encoding="utf-8", errors="replace")[:limit_per_file].splitlines())
            except Exception:
                continue
    return lines


def actionable_critical_findings(lines: list[str]) -> list[str]:
    findings: set[str] = set()
    safe_context_remaining = 0
    for line in lines:
        text = str(line or "").strip()
        if not text:
            safe_context_remaining = max(0, safe_context_remaining - 1)
            continue
        lowered = text.lower()
        if any(marker in lowered for marker in SAFE_POLICY_MARKERS):
            safe_context_remaining = 8
            continue
        if safe_context_remaining > 0:
            safe_context_remaining -= 1
            continue
        findings.update(critical_operation_findings(text))
    return sorted(findings)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def existing_pipeline_status(runtime: Path, max_age_seconds: int | None = None) -> dict[str, Any]:
    paths = runtime_paths(runtime)
    payload = read_json(paths["pipeline"], {})
    status = str(payload.get("status") or "").upper()
    ok = bool(payload.get("ok")) if "ok" in payload else None

    checked_at = parse_time(payload.get("checked_at") or payload.get("updated_at"))
    stale = False
    if max_age_seconds and checked_at:
        age = (datetime.now(timezone.utc) - checked_at).total_seconds()
        stale = age > max_age_seconds

    if status == "PASS" and ok is not False and not stale:
        normalized = "PASS"
    elif status == "FAIL" or ok is False:
        normalized = "FAIL"
    elif stale:
        normalized = "STALE"
    else:
        normalized = "UNKNOWN"

    return {
        "status": normalized,
        "source": "existing_state",
        "attempted": False,
        "checked_at": payload.get("checked_at") or payload.get("updated_at"),
        "failed": payload.get("failed", []),
    }


def run_pipeline(runtime: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["CODEX_DEV_CENTER_HOME"] = str(runtime)
    cmd = [sys.executable, "supervisor/production_readiness_suite.py", "--json"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(runtime),
            env=env,
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
    except Exception as exc:
        return {
            "status": "FAIL",
            "source": "production_readiness_suite",
            "attempted": True,
            "returncode": 1,
            "error": redact_sensitive_text(str(exc))[:500],
        }

    payload: dict[str, Any] = {}
    try:
        payload = json.loads((proc.stdout or "{}").lstrip("\ufeff"))
    except Exception:
        payload = {}

    status = str(payload.get("status") or ("PASS" if proc.returncode == 0 else "FAIL")).upper()
    ok = proc.returncode == 0 and status == "PASS" and bool(payload.get("ok", True))
    return {
        "status": "PASS" if ok else "FAIL",
        "source": "production_readiness_suite",
        "attempted": True,
        "returncode": proc.returncode,
        "checked_at": payload.get("checked_at"),
        "failed": payload.get("failed", []),
    }


def pipeline_gate(runtime: Path, run: bool, max_age_seconds: int | None) -> dict[str, Any]:
    if run:
        return run_pipeline(runtime)
    return existing_pipeline_status(runtime, max_age_seconds=max_age_seconds)


def candidate_statuses(include_proposal_done: bool) -> set[str]:
    statuses = {TASK_STATUS_READY_FOR_VALIDATION}
    if include_proposal_done:
        statuses.add(TASK_STATUS_PROPOSAL_DONE)
    return statuses


def is_validation_candidate(
    task: dict[str, Any],
    statuses: set[str],
    *,
    recheck_engine_approval: bool,
) -> bool:
    status = normalize_status(task.get("status"))
    if status in statuses:
        return True
    if not recheck_engine_approval or status != TASK_STATUS_APPROVAL_REQUIRED:
        return False
    return (
        task.get("result") in {"critical_operation_requires_user_approval", "critical_operation_validation_failed"}
        and task.get("validation_status") == "APPROVAL_REQUIRED"
    )


def evaluate_task(task: dict[str, Any], runtime: Path, pipeline: dict[str, Any]) -> dict[str, Any]:
    workspace = find_workspace(runtime, task)
    files = created_files(workspace)
    task_id = str(task.get("id") or "")

    if len(files) < MIN_EXPECTED_FILES:
        return {
            "task_id": task_id,
            "target_status": TASK_STATUS_VALIDATION_FAILED,
            "result": "worker_output_missing_required_validation_files",
            "validation_status": "FAIL",
            "pipeline_status": "NOT_RUN",
            "workspace": str(workspace) if workspace else "",
            "created_files": files,
            "critical_operation_findings": [],
        }

    findings = actionable_critical_findings(useful_lines_for_scan(task, workspace))
    if findings:
        return {
            "task_id": task_id,
            "target_status": TASK_STATUS_VALIDATION_FAILED,
            "result": "critical_operation_validation_failed",
            "validation_status": "FAIL",
            "pipeline_status": "NOT_RUN",
            "workspace": str(workspace) if workspace else "",
            "created_files": files,
            "critical_operation_findings": findings,
        }

    repo_applied = bool(
        task.get("repo_applied")
        or task.get("branch_merged")
        or str(task.get("delivery_level") or "").upper() in {"READY_FOR_DEPLOY", "MERGED", "DEPLOYED"}
    )

    if not repo_applied:
        return {
            "task_id": task_id,
            "target_status": TASK_STATUS_PROPOSAL_DONE,
            "result": "validated_worker_proposal_ready_for_apply",
            "validation_status": "PASS",
            "pipeline_status": "NOT_REQUIRED",
            "workspace": str(workspace) if workspace else "",
            "created_files": files,
            "critical_operation_findings": [],
        }

    if pipeline.get("status") != "PASS":
        target_status = None
        result = "pipeline_gate_not_passed"
        if pipeline.get("attempted") or pipeline.get("status") == "FAIL":
            target_status = TASK_STATUS_PIPELINE_FAILED
            result = "production_readiness_pipeline_failed"
        return {
            "task_id": task_id,
            "target_status": target_status,
            "result": result,
            "validation_status": "PASS",
            "pipeline_status": pipeline.get("status") or "UNKNOWN",
            "workspace": str(workspace) if workspace else "",
            "created_files": files,
            "critical_operation_findings": [],
        }

    return {
        "task_id": task_id,
        "target_status": TASK_STATUS_DONE,
        "result": "validated_repo_change_pipeline_passed",
        "validation_status": "PASS",
        "pipeline_status": "PASS",
        "workspace": str(workspace) if workspace else "",
        "created_files": files,
        "critical_operation_findings": [],
    }


def apply_validation_result(task: dict[str, Any], result: dict[str, Any]) -> bool:
    target_status = result.get("target_status")
    if not target_status:
        return False

    before_findings = sorted(task.get("critical_operation_findings") or [])
    after_findings = sorted(result.get("critical_operation_findings") or [])
    if (
        normalize_status(task.get("status")) == target_status
        and task.get("result") == result.get("result")
        and task.get("validation_status") == result.get("validation_status")
        and task.get("pipeline_status") == result.get("pipeline_status")
        and before_findings == after_findings
    ):
        return False

    task["status"] = target_status
    task["result"] = result.get("result")
    task["delivery_level"] = target_status
    task["validation_status"] = result.get("validation_status")
    task["pipeline_status"] = result.get("pipeline_status")
    task["validated_at"] = utc_now()
    task["updated_at"] = utc_now()
    if target_status in {TASK_STATUS_DONE, TASK_STATUS_PROPOSAL_DONE, TASK_STATUS_VALIDATION_FAILED, TASK_STATUS_PIPELINE_FAILED, TASK_STATUS_APPROVAL_REQUIRED}:
        task["finished_at"] = utc_now()
    if result.get("workspace"):
        task["workspace"] = result["workspace"]
    task["created_files"] = result.get("created_files", [])
    task["critical_operation_findings"] = result.get("critical_operation_findings", [])
    if target_status == TASK_STATUS_DONE:
        task["production_deployed"] = bool(task.get("production_deployed", False))
        task["repo_applied"] = bool(task.get("repo_applied", False))
        task["deployment_status"] = "READY_FOR_DEPLOY" if task["repo_applied"] else "REPO_APPLIED_FALSE"
    elif target_status == TASK_STATUS_PROPOSAL_DONE:
        task["production_deployed"] = False
        task["repo_applied"] = False
        task["deployment_status"] = "APPLY_REQUIRED"
    return True


def write_report(runtime: Path, payload: dict[str, Any]) -> None:
    paths = runtime_paths(runtime)
    paths["report"].parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Task Validation Engine Last Report",
        "",
        f"Generated at: {payload['checked_at']}",
        f"Status: {payload['status']}",
        f"Pipeline gate: {payload['pipeline'].get('status')} ({payload['pipeline'].get('source')})",
        f"Candidates checked: {payload['checked']}",
        f"Tasks changed: {payload['changed']}",
        "",
        "## Results",
    ]
    if not payload["results"]:
        lines.append("- No validation candidates processed.")
    for item in payload["results"]:
        lines.append(
            "- "
            + str(item.get("task_id"))
            + ": "
            + str(item.get("target_status") or "UNCHANGED")
            + " ("
            + str(item.get("result"))
            + ", files="
            + str(len(item.get("created_files") or []))
            + "/6)"
        )
        findings = item.get("critical_operation_findings") or []
        if findings:
            lines.append("  Critical findings: " + ", ".join(findings))
    paths["report"].write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_ready_tasks(
    runtime: Path = APP_DIR,
    *,
    limit: int = DEFAULT_LIMIT,
    run_pipeline_gate: bool = False,
    include_proposal_done: bool = False,
    recheck_engine_approval: bool = True,
    pipeline_max_age_seconds: int | None = None,
    write: bool = True,
) -> dict[str, Any]:
    paths = runtime_paths(runtime)
    pipeline = pipeline_gate(runtime, run_pipeline_gate, pipeline_max_age_seconds)
    statuses = candidate_statuses(include_proposal_done)

    results: list[dict[str, Any]] = []
    changed = 0
    checked = 0

    with state_file_lock(paths["queue"]):
        queue = read_json(paths["queue"], {"tasks": []})
        queue, _changes = normalize_queue_payload(queue)

        for task in queue.get("tasks", []):
            if checked >= max(0, limit):
                break
            if not is_validation_candidate(task, statuses, recheck_engine_approval=recheck_engine_approval):
                continue
            checked += 1
            result = evaluate_task(task, runtime, pipeline)
            if write and apply_validation_result(task, result):
                changed += 1
            results.append(result)

        if write and changed:
            atomic_write_json(paths["queue"], queue)

    payload = {
        "ok": True,
        "status": "PASS" if not any(item.get("target_status") in {TASK_STATUS_VALIDATION_FAILED, TASK_STATUS_PIPELINE_FAILED, TASK_STATUS_APPROVAL_REQUIRED} for item in results) else "ATTENTION",
        "checked_at": utc_now(),
        "checked": checked,
        "changed": changed,
        "pipeline": pipeline,
        "results": results,
    }

    if write:
        atomic_write_json(paths["status"], payload)
        write_report(runtime, payload)
        append_log(paths["log"], {
            "event": "task_validation_engine",
            "status": payload["status"],
            "checked": checked,
            "changed": changed,
            "pipeline_status": pipeline.get("status"),
        })

    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", default=str(APP_DIR))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--run-pipeline", action="store_true")
    parser.add_argument("--include-proposal-done", action="store_true")
    parser.add_argument("--no-recheck-engine-approval", action="store_true")
    parser.add_argument("--pipeline-max-age-seconds", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    max_age = args.pipeline_max_age_seconds or None
    payload = validate_ready_tasks(
        Path(args.runtime),
        limit=args.limit,
        run_pipeline_gate=args.run_pipeline,
        include_proposal_done=args.include_proposal_done,
        recheck_engine_approval=not args.no_recheck_engine_approval,
        pipeline_max_age_seconds=max_age,
        write=True,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "TASK_VALIDATION status={status} checked={checked} changed={changed} pipeline={pipeline}".format(
                status=payload["status"],
                checked=payload["checked"],
                changed=payload["changed"],
                pipeline=payload["pipeline"].get("status"),
            )
        )


if __name__ == "__main__":
    main()
