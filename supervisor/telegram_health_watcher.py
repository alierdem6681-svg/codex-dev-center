#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"

SERVICES = [
    "codex-panel",
    "codex-watchdog",
    "codex-lifecycle",
    "codex-cto",
    "codex-worker-1",
    "codex-worker-2",
    "codex-worker-3",
    "codex-worker-4",
]

def sh(cmd):
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=15)
    return (p.stdout.strip() or p.stderr.strip() or "unknown")

def status_snapshot():
    rows = []
    for svc in SERVICES:
        active = sh(["systemctl", "is-active", svc])
        enabled = sh(["systemctl", "is-enabled", svc])
        rows.append({"service": svc, "active": active, "enabled": enabled})
    return rows

def snapshot_hash(rows):
    raw = json.dumps(rows, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()

def read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    return default

def truthy(value):
    return value is True or str(value or "").strip().lower() in {"1", "true", "yes", "on"}

def auto_report_enabled():
    if os.environ.get("CODEX_TELEGRAM_HEALTH_AUTO_REPORT", "").strip():
        return truthy(os.environ.get("CODEX_TELEGRAM_HEALTH_AUTO_REPORT"))
    runtime = read_json(STATE / "telegram_config.json", {})
    settings = read_json(APP / "state_templates/module_settings.json", {})
    telegram = settings.get("telegram", {}) if isinstance(settings, dict) else {}
    return bool(
        truthy(runtime.get("health_auto_report_enabled"))
        or truthy(runtime.get("auto_health_report_enabled"))
        or truthy(telegram.get("health_auto_report_enabled"))
        or truthy(telegram.get("auto_health_report_enabled"))
    )

def send_health(reason):
    subprocess.run(
        ["python3", "supervisor/telegram_notify.py", "--reason", reason],
        cwd=str(APP),
        text=True,
        capture_output=True,
        timeout=60,
    )
    with (LOGS / "telegram_health_watcher.log").open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} sent reason={reason}\n")

def main():
    STATE.mkdir(exist_ok=True)
    LOGS.mkdir(exist_ok=True)

    rows = status_snapshot()
    h = snapshot_hash(rows)

    last_file = STATE / "telegram_health_last_hash.txt"
    last_hash = last_file.read_text().strip() if last_file.exists() else ""

    reason = "boot-or-first-run" if not last_hash else "service-status-changed"

    if h != last_hash:
        last_file.write_text(h)
        (STATE / "telegram_health_last_snapshot.json").write_text(
            json.dumps({
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "services": rows,
                "reason": reason
            }, indent=2, ensure_ascii=False) + "\n"
        )
        if not auto_report_enabled():
            with (LOGS / "telegram_health_watcher.log").open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} suppressed reason={reason} auto_report_enabled=false\n")
            print("TELEGRAM_HEALTH_WATCHER=SUPPRESSED_AUTO_DISABLED")
            print("REASON=" + reason)
            return
        send_health(reason)
        print("TELEGRAM_HEALTH_WATCHER=SENT")
        print("REASON=" + reason)
    else:
        print("TELEGRAM_HEALTH_WATCHER=NO_CHANGE")

if __name__ == "__main__":
    main()
