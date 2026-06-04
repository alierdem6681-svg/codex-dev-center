#!/usr/bin/env python3
from __future__ import annotations

import errno
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


EXECUTION_MODE_READ_ONLY = "read_only"
EXECUTION_MODE_DRY_RUN = "dry_run"
EXECUTION_MODE_WRITE_ENABLED = "write_enabled"
EXECUTION_MODES = {
    EXECUTION_MODE_READ_ONLY,
    EXECUTION_MODE_DRY_RUN,
    EXECUTION_MODE_WRITE_ENABLED,
}
READ_ONLY_ERRNOS = {errno.EROFS, errno.EACCES, errno.EPERM}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def current_execution_mode(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    for key in ("CHECK_MODE", "CODEX_CHECK_MODE", "CODEX_EXECUTION_MODE"):
        raw = str(source.get(key) or "").strip().lower().replace("-", "_")
        if not raw:
            continue
        if raw in {"readonly", "read_only"}:
            return EXECUTION_MODE_READ_ONLY
        if raw in {"dryrun", "dry_run"}:
            return EXECUTION_MODE_DRY_RUN
        if raw in {"write", "write_enabled", "enabled"}:
            return EXECUTION_MODE_WRITE_ENABLED
    return EXECUTION_MODE_WRITE_ENABLED


def read_only_write_error(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and getattr(exc, "errno", None) in READ_ONLY_ERRNOS


def target_for(path: Path, root: Path | None = None) -> str:
    try:
        if root is not None:
            return str(path.resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        pass
    return str(path)


def _skip_reason_for_mode(mode: str) -> str | None:
    if mode == EXECUTION_MODE_READ_ONLY:
        return "read_only_workspace"
    if mode == EXECUTION_MODE_DRY_RUN:
        return "dry_run_mode"
    return None


def _result(
    path: Path,
    *,
    root: Path | None,
    operation: str,
    mode: str,
    ok: bool,
    write_status: str,
    skip_reason: str | None = None,
    error: BaseException | None = None,
) -> dict[str, Any]:
    errno_value = getattr(error, "errno", None) if error is not None else None
    read_only = mode == EXECUTION_MODE_READ_ONLY or (
        error is not None and read_only_write_error(error)
    )
    result: dict[str, Any] = {
        "ok": ok,
        "path": str(path),
        "target": target_for(path, root),
        "operation": operation,
        "mode": mode,
        "write_attempted": True,
        "write_status": write_status,
        "skip_reason": skip_reason,
        "read_only": read_only,
        "dry_run": mode == EXECUTION_MODE_DRY_RUN,
    }
    if write_status == "skipped":
        result["event"] = "write-skipped"
    if error is not None:
        result["error"] = type(error).__name__
        result["errno"] = errno_value
    return result


def write_text_best_effort(
    path: Path,
    text: str,
    encoding: str = "utf-8",
    *,
    root: Path | None = None,
    operation: str = "write_text",
) -> dict[str, Any]:
    mode = current_execution_mode()
    if mode != EXECUTION_MODE_WRITE_ENABLED:
        return _result(
            path,
            root=root,
            operation=operation,
            mode=mode,
            ok=False,
            write_status="skipped",
            skip_reason=_skip_reason_for_mode(mode),
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=encoding)
        return _result(
            path,
            root=root,
            operation=operation,
            mode=mode,
            ok=True,
            write_status="written",
        )
    except OSError as exc:
        if read_only_write_error(exc):
            reason = "read_only_workspace" if getattr(exc, "errno", None) == errno.EROFS else "permission_denied"
            return _result(
                path,
                root=root,
                operation=operation,
                mode=mode,
                ok=False,
                write_status="skipped",
                skip_reason=reason,
                error=exc,
            )
        return _result(
            path,
            root=root,
            operation=operation,
            mode=mode,
            ok=False,
            write_status="failed",
            error=exc,
        )


def write_json_best_effort(
    path: Path,
    data: dict[str, Any],
    *,
    root: Path | None = None,
    operation: str = "write_json",
    add_updated_at: bool = True,
) -> dict[str, Any]:
    if add_updated_at:
        data["updated_at"] = now()
    return write_text_best_effort(
        path,
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        root=root,
        operation=operation,
    )


def atomic_write_json_best_effort(
    path: Path,
    data: dict[str, Any],
    *,
    root: Path | None = None,
    operation: str = "atomic_write_json",
) -> dict[str, Any]:
    data["updated_at"] = now()
    mode = current_execution_mode()
    if mode != EXECUTION_MODE_WRITE_ENABLED:
        return _result(
            path,
            root=root,
            operation=operation,
            mode=mode,
            ok=False,
            write_status="skipped",
            skip_reason=_skip_reason_for_mode(mode),
        )

    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return _result(
            path,
            root=root,
            operation=operation,
            mode=mode,
            ok=True,
            write_status="written",
        )
    except OSError as exc:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        if read_only_write_error(exc):
            reason = "read_only_workspace" if getattr(exc, "errno", None) == errno.EROFS else "permission_denied"
            return _result(
                path,
                root=root,
                operation=operation,
                mode=mode,
                ok=False,
                write_status="skipped",
                skip_reason=reason,
                error=exc,
            )
        return _result(
            path,
            root=root,
            operation=operation,
            mode=mode,
            ok=False,
            write_status="failed",
            error=exc,
        )


def write_evidence_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and "write_status" in value and "target" in value:
        return [value]
    if isinstance(value, dict):
        items: list[dict[str, Any]] = []
        for nested in value.values():
            items.extend(write_evidence_items(nested))
        return items
    if isinstance(value, list):
        items = []
        for nested in value:
            items.extend(write_evidence_items(nested))
        return items
    return []


def summarize_write_status(evidence: list[dict[str, Any]]) -> str:
    statuses = {item.get("write_status") for item in evidence}
    if "failed" in statuses:
        return "write_failed"
    if "skipped" in statuses:
        return "completed_with_write_skipped"
    if "written" in statuses:
        return "written"
    return "not_applicable"
