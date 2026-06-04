from __future__ import annotations

from typing import Any


def classify_repo_apply_outcome(
    *,
    apply_status: str,
    changed_paths: list[str] | tuple[str, ...] | None = None,
    reason: str = "",
    already_satisfied: bool = False,
    transient_failure: bool = False,
) -> dict[str, Any]:
    paths = sorted(dict.fromkeys(str(path) for path in (changed_paths or []) if str(path).strip()))
    status = str(apply_status or "").strip().upper()
    normalized_reason = str(reason or "").strip()

    if status == "SUCCESS" and not paths:
        final_state = "DONE" if already_satisfied else "NO_CHANGE"
        return {
            "apply_status": "SUCCESS",
            "changed_paths": [],
            "changed_paths_count": 0,
            "terminal": True,
            "final_state": final_state,
            "reason": normalized_reason or ("ALREADY_SATISFIED" if already_satisfied else "NO_DIFF_AFTER_APPLY"),
            "enqueue_target": None,
        }

    if status == "SUCCESS":
        return {
            "apply_status": "SUCCESS",
            "changed_paths": paths,
            "changed_paths_count": len(paths),
            "terminal": True,
            "final_state": "DONE",
            "reason": normalized_reason or "CHANGES_APPLIED",
            "enqueue_target": None,
        }

    if status == "SKIPPED":
        return {
            "apply_status": "SKIPPED",
            "changed_paths": paths,
            "changed_paths_count": len(paths),
            "terminal": True,
            "final_state": "BLOCKED",
            "reason": normalized_reason or "APPLY_SKIPPED",
            "enqueue_target": None,
        }

    return {
        "apply_status": "FAILED",
        "changed_paths": paths,
        "changed_paths_count": len(paths),
        "terminal": not transient_failure,
        "final_state": "RETRY" if transient_failure else "BACKLOG",
        "reason": normalized_reason or ("TRANSIENT_FAILURE" if transient_failure else "APPLY_FAILED"),
        "enqueue_target": "retry" if transient_failure else "backlog",
    }
