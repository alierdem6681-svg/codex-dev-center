#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
    from .cto_task_router import normalize_queue
    from .task_status_constants import (
        ACTIVE_TASK_STATUSES,
        append_audit,
        atomic_write_json,
        is_worker_eligible_task,
        normalize_status,
        read_json,
        utc_now,
        worker_block_reason,
    )
except ImportError:
    from cto_task_router import normalize_queue
    from task_status_constants import (
        ACTIVE_TASK_STATUSES,
        append_audit,
        atomic_write_json,
        is_worker_eligible_task,
        normalize_status,
        read_json,
        utc_now,
        worker_block_reason,
    )

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
CORE_SERVICES = ["codex-panel", "codex-lifecycle", "codex-watchdog", "codex-direct-cto"]
WORKER_SERVICES = ["codex-worker-1", "codex-worker-2", "codex-worker-3", "codex-worker-4"]


def service_status(name: str) -> str:
    if shutil.which("systemctl") is None:
        return "systemctl_unavailable"
    proc = subprocess.run(["systemctl", "is-active", name], text=True, capture_output=True, timeout=10, check=False)
    return (proc.stdout or proc.stderr or "unknown").strip() or "unknown"


def queue_summary(root: Path) -> dict[str, Any]:
    queue = read_json(root / "state" / "task_queue.json", {"tasks": []})
    counts: dict[str, int] = {}
    worker_eligible = 0
    excluded = []
    lowercase_statuses = []
    for task in queue.get("tasks", []):
        raw_status = task.get("status")
        status = normalize_status(raw_status)
        counts[status] = counts.get(status, 0) + 1
        if isinstance(raw_status, str) and raw_status != raw_status.upper():
            lowercase_statuses.append({"id": task.get("id"), "status": raw_status})
        if status in ACTIVE_TASK_STATUSES:
            if is_worker_eligible_task(task):
                worker_eligible += 1
            else:
                excluded.append({"id": task.get("id"), "source": task.get("source"), "reason": worker_block_reason(task)})
    return {
        "task_count": len(queue.get("tasks", [])),
        "status_counts": counts,
        "worker_eligible_active_count": worker_eligible,
        "excluded_active_tasks": excluded[:20],
        "lowercase_statuses": lowercase_statuses[:20],
    }


def evaluate(root: Path, fix: bool = False) -> dict[str, Any]:
    normalize_result = normalize_queue(root, fix=fix)
    summary = queue_summary(root)
    services = {name: service_status(name) for name in [*CORE_SERVICES, *WORKER_SERVICES]}
    router_state = read_json(root / "state" / "cto_router_state.json", {})
    telegram_config = read_json(root / "state" / "telegram_config.json", {})
    has_git_metadata = (root / ".git").exists()
    errors = []
    warnings = []

    for service in CORE_SERVICES:
        if services.get(service) not in {"active", "unknown"}:
            errors.append(f"{service}={services.get(service)}")
    if has_git_metadata:
        warnings.append("runtime_has_git_metadata")
    if summary["lowercase_statuses"]:
        warnings.append("queue_has_lowercase_statuses")
    if telegram_config.get("enabled") is False and telegram_config.get("direct_cto_mode") is True:
        warnings.append("telegram_enabled_false_but_direct_cto_mode_true")

    result = {
        "ok": not errors,
        "checked_at": utc_now(),
        "runtime": str(root),
        "fix": fix,
        "normalize_result": normalize_result,
        "queue": summary,
        "services": services,
        "router_state": router_state,
        "runtime_git_metadata_present": has_git_metadata,
        "errors": errors,
        "warnings": warnings,
    }

    if fix:
        state_path = root / "state" / "cto_doctor_status.json"
        atomic_write_json(state_path, result)
        reports = root / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        report = reports / "CTO_DOCTOR_REPORT.md"
        report.write_text(
            "# CTO DOCTOR REPORT\n\n"
            f"Checked at: {result['checked_at']}\n"
            f"OK: {result['ok']}\n"
            f"Queue tasks: {summary['task_count']}\n"
            f"Worker eligible active: {summary['worker_eligible_active_count']}\n"
            f"Normalization changes: {len(normalize_result.get('changes', []))}\n"
            f"Runtime git metadata present: {has_git_metadata}\n"
            f"Warnings: {', '.join(warnings) if warnings else '-'}\n"
            f"Errors: {', '.join(errors) if errors else '-'}\n",
            encoding="utf-8",
        )
        append_audit(root, "cto_doctor", {"ok": result["ok"], "fix": fix, "warnings": warnings, "errors": errors})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="CTO runtime doctor")
    parser.add_argument("--runtime", default=str(DEFAULT_ROOT))
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = evaluate(Path(args.runtime).resolve(), fix=args.fix)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"cto_doctor_ok={result['ok']}")
        print(f"runtime={result['runtime']}")
        print(f"queue_tasks={result['queue']['task_count']}")
        print(f"worker_eligible_active={result['queue']['worker_eligible_active_count']}")
        print(f"normalization_changes={len(result['normalize_result'].get('changes', []))}")
        for warning in result["warnings"]:
            print(f"warning={warning}")
        for error in result["errors"]:
            print(f"error={error}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
