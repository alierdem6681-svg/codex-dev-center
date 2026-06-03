#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import signal
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .task_status_constants import TASK_STATUS_FAILED_RETRYABLE, atomic_write_json, redact_sensitive_text
except ImportError:
    from task_status_constants import TASK_STATUS_FAILED_RETRYABLE, atomic_write_json, redact_sensitive_text


PROJECT_ID = "eterna-498108"
APP = Path(os.environ.get("CODEX_DEV_CENTER_HOME", "/opt/codex-dev-center")).resolve()
STATE = APP / "state"
LOGS = APP / "logs"
ACTIVE_DIRECT_CTO_STATUSES = {"QUEUED", "RUNNING"}
DEFAULT_STALE_SECONDS = int(os.environ.get("CODEX_DIRECT_CTO_STALE_SECONDS", "300"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    return default


def pid_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except Exception:
        return False
    if value <= 1:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def metadata_token() -> str:
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())["access_token"]


def secret_value(name: str) -> str:
    token = metadata_token()
    url = f"https://secretmanager.googleapis.com/v1/projects/{PROJECT_ID}/secrets/{name}/versions/latest:access"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode())
    return base64.b64decode(data["payload"]["data"]).decode().strip()


def tg_send(chat_id: str, text: str) -> bool:
    token = secret_value("codex-telegram-bot-token")
    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text[:3900],
            "disable_web_page_preview": "true",
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return bool(json.loads(response.read().decode()).get("ok"))


def should_recover(job: dict[str, Any], progress: dict[str, Any], *, stale_seconds: int) -> tuple[bool, str]:
    status = str(job.get("status") or "").upper()
    if status not in ACTIVE_DIRECT_CTO_STATUSES:
        return False, "not_active"

    if pid_alive(progress.get("pid")):
        return False, "process_alive"

    timestamps = [
        parse_time(progress.get("updated_at")),
        parse_time(job.get("updated_at")),
        parse_time(job.get("started_at")),
        parse_time(job.get("created_at")),
    ]
    latest = max([item for item in timestamps if item is not None], default=None)
    if not latest:
        return True, "missing_timestamp_no_process"

    age = (datetime.now(timezone.utc) - latest).total_seconds()
    if age < stale_seconds:
        return False, "recent_without_process"
    return True, "stale_without_process"


def notify_job(job: dict[str, Any]) -> bool:
    chat_id = str(job.get("chat_id") or "").strip()
    if not chat_id or job.get("stale_recovery_notified_at"):
        return False
    message = (
        "CTO arka plan işi kesintiye uğradı ve retry edilebilir duruma alındı. "
        "Teknik çıktı Telegram'a gönderilmedi; işi daha küçük parçalar halinde sürdüreceğim."
    )
    return tg_send(chat_id, message)


def reconcile_stale_jobs(
    app: Path | str = APP,
    *,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
    notify: bool = True,
) -> dict[str, Any]:
    root = Path(app).resolve()
    jobs_dir = root / "state" / "direct_cto_jobs"
    log_dir = root / "logs"
    checked = 0
    changed = 0
    recovered: list[str] = []
    errors: list[str] = []

    if not jobs_dir.exists():
        return {"ok": True, "checked": 0, "changed": 0, "recovered": [], "errors": []}

    for job_path in sorted(jobs_dir.glob("JOB-*.json")):
        if job_path.name.endswith(".progress.json"):
            continue
        job = read_json(job_path, {})
        if not isinstance(job, dict):
            continue
        checked += 1
        job_id = str(job.get("id") or job_path.stem)
        progress_path = jobs_dir / f"{job_id}.progress.json"
        progress = read_json(progress_path, {})
        if not isinstance(progress, dict):
            progress = {}

        recover, reason = should_recover(job, progress, stale_seconds=stale_seconds)
        if not recover:
            continue

        job["status"] = TASK_STATUS_FAILED_RETRYABLE
        job["result"] = "direct_cto_process_lost_retryable"
        job["stale_recovery_reason"] = reason
        job["finished_at"] = job.get("finished_at") or now()
        job["progress_watchdog"] = {
            **(job.get("progress_watchdog") if isinstance(job.get("progress_watchdog"), dict) else {}),
            "status": TASK_STATUS_FAILED_RETRYABLE,
            "stale_recovery_reason": reason,
            "previous_progress_status": progress.get("status"),
            "previous_pid": progress.get("pid"),
        }

        if notify:
            try:
                if notify_job(job):
                    job["stale_recovery_notified_at"] = now()
            except Exception as exc:
                errors.append(f"{job_id}:notify:{redact_sensitive_text(str(exc))[:160]}")

        atomic_write_json(job_path, job)
        if progress_path.exists():
            progress.update(
                {
                    "status": TASK_STATUS_FAILED_RETRYABLE,
                    "stale_recovery_reason": reason,
                    "updated_at": now(),
                }
            )
            atomic_write_json(progress_path, progress)
        recovered.append(job_id)
        changed += 1

    if changed or errors:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "direct_cto_job_recovery.log").open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "created_at": now(),
                        "checked": checked,
                        "changed": changed,
                        "recovered": recovered,
                        "errors": errors,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

    return {"ok": not errors, "checked": checked, "changed": changed, "recovered": recovered, "errors": errors}


def main() -> int:
    payload = reconcile_stale_jobs(APP)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
