#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


MEANINGFUL_OUTPUT_MARKERS = (
    "created",
    "updated",
    "wrote",
    "generated",
    "test",
    "pass",
    "fail",
    "pipeline",
    "workflow",
    "deploy",
    "health",
    "rollback",
    "branch",
    "commit",
    "pull request",
    "pr ",
    "state",
    "report",
    "PLAN.md",
    "CHANGE_PROPOSAL.md",
    "TEST_PLAN.md",
    "RISK_REVIEW.md",
    "LIVING_DOCS_CHECKLIST.md",
    "WORKER_SUMMARY.md",
)

IGNORED_PROGRESS_NAMES = {
    "PROMPT.txt",
    "codex.out",
    "codex.err",
}


ProgressCallback = Callable[[dict[str, Any]], None]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.exists() else 0
    except Exception:
        return 0


def tail_text(path: Path, limit: int = 4000) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except Exception:
        return ""
    return ""


def snapshot_paths(paths: list[Path], ignore_names: set[str] | None = None) -> dict[str, tuple[int, int]]:
    ignore = ignore_names or set()
    snapshot: dict[str, tuple[int, int]] = {}
    for root in paths:
        if not root.exists():
            continue
        candidates = root.rglob("*") if root.is_dir() else [root]
        for path in candidates:
            if not path.is_file() or path.name in ignore:
                continue
            try:
                stat = path.stat()
                snapshot[str(path)] = (stat.st_size, stat.st_mtime_ns)
            except Exception:
                continue
    return snapshot


def changed_paths(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    changed = []
    for path, value in after.items():
        if before.get(path) != value:
            changed.append(path)
    return sorted(changed)


def output_has_meaningful_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in MEANINGFUL_OUTPUT_MARKERS)


def snapshot_git_roots(roots: list[Path] | None) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for root in roots or []:
        if not (root / ".git").exists():
            continue
        try:
            status = subprocess.run(
                ["git", "status", "--short"],
                cwd=str(root),
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            diff = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=str(root),
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            snapshot[str(root)] = (status.stdout or "") + "\n" + (diff.stdout or "")
        except Exception:
            continue
    return snapshot


def changed_git_roots(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changed = []
    for root, value in after.items():
        if before.get(root) != value:
            changed.append(root)
    return sorted(changed)


def terminate_process(proc: subprocess.Popen[Any], grace_seconds: int = 8) -> None:
    if proc.poll() is not None:
        return
    try:
        if proc.pid:
            os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.25)
    try:
        if proc.pid:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def write_progress(path: Path | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_progress_aware(
    cmd: list[str],
    *,
    cwd: Path,
    stdin_path: Path | None = None,
    stdout_path: Path,
    stderr_path: Path,
    progress_paths: list[Path] | None = None,
    git_roots: list[Path] | None = None,
    progress_state_path: Path | None = None,
    stall_seconds: int = 900,
    grace_seconds: int = 180,
    poll_seconds: float = 2.0,
    max_wall_seconds: int = 14400,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    progress_paths = progress_paths or []
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.time()
    last_meaningful = started
    last_output_activity = started
    last_stdout_size = file_size(stdout_path)
    last_stderr_size = file_size(stderr_path)
    ignored_names = set(IGNORED_PROGRESS_NAMES)
    if progress_state_path:
        ignored_names.add(progress_state_path.name)
    path_snapshot = snapshot_paths(progress_paths, ignored_names)
    git_snapshot = snapshot_git_roots(git_roots)
    meaningful_events: list[dict[str, Any]] = []
    output_activity_count = 0

    stdin_handle = stdin_path.open("rb") if stdin_path else subprocess.DEVNULL
    try:
        with stdout_path.open("ab") as out, stderr_path.open("ab") as err:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdin=stdin_handle,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )

            while True:
                returncode = proc.poll()
                now_ts = time.time()
                stdout_size = file_size(stdout_path)
                stderr_size = file_size(stderr_path)
                output_changed = stdout_size != last_stdout_size or stderr_size != last_stderr_size
                if output_changed:
                    output_activity_count += 1
                    last_output_activity = now_ts

                after_snapshot = snapshot_paths(progress_paths, ignored_names)
                changed = changed_paths(path_snapshot, after_snapshot)
                after_git_snapshot = snapshot_git_roots(git_roots)
                git_changed = changed_git_roots(git_snapshot, after_git_snapshot)
                tail = tail_text(stdout_path) + "\n" + tail_text(stderr_path)
                meaningful_output = output_changed and output_has_meaningful_marker(tail)
                meaningful = bool(changed) or bool(git_changed) or meaningful_output
                if meaningful:
                    last_meaningful = now_ts
                    event = {
                        "at": utc_now(),
                        "changed_paths": changed[:20],
                        "git_changed_roots": git_changed[:8],
                        "meaningful_output": meaningful_output,
                    }
                    meaningful_events.append(event)
                    meaningful_events = meaningful_events[-20:]
                    path_snapshot = after_snapshot
                    git_snapshot = after_git_snapshot

                payload = {
                    "status": "RUNNING" if returncode is None else "EXITED",
                    "pid": proc.pid,
                    "returncode": returncode,
                    "updated_at": utc_now(),
                    "started_at_epoch": started,
                    "elapsed_seconds": int(now_ts - started),
                    "last_meaningful_progress_seconds_ago": int(now_ts - last_meaningful),
                    "last_output_activity_seconds_ago": int(now_ts - last_output_activity),
                    "output_activity_count": output_activity_count,
                    "meaningful_event_count": len(meaningful_events),
                    "last_meaningful_events": meaningful_events[-5:],
                }
                write_progress(progress_state_path, payload)
                if on_progress:
                    on_progress(payload)

                if returncode is not None:
                    payload["status"] = "COMPLETED" if returncode == 0 else "EXITED_NONZERO"
                    payload["finished_at"] = utc_now()
                    write_progress(progress_state_path, payload)
                    return payload

                if now_ts - started > max_wall_seconds:
                    terminate_process(proc)
                    payload["status"] = "STALLED"
                    payload["returncode"] = 124
                    payload["finished_at"] = utc_now()
                    payload["stall_reason"] = "max_wall_seconds_exceeded"
                    write_progress(progress_state_path, payload)
                    return payload

                if now_ts - started >= grace_seconds and now_ts - last_meaningful >= stall_seconds:
                    terminate_process(proc)
                    payload["status"] = "STALLED"
                    payload["returncode"] = 124
                    payload["finished_at"] = utc_now()
                    payload["stall_reason"] = "no_meaningful_progress"
                    write_progress(progress_state_path, payload)
                    return payload

                last_stdout_size = stdout_size
                last_stderr_size = stderr_size
                time.sleep(poll_seconds)
    finally:
        if hasattr(stdin_handle, "close"):
            try:
                stdin_handle.close()
            except Exception:
                pass
