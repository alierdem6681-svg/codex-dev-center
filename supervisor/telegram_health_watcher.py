#!/usr/bin/env python3
import hashlib
import json
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

def send_health(reason):
    subprocess.run(
        ["python3", "supervisor/telegram_notify.py"],
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
        send_health(reason)
        print("TELEGRAM_HEALTH_WATCHER=SENT")
        print("REASON=" + reason)
    else:
        print("TELEGRAM_HEALTH_WATCHER=NO_CHANGE")

if __name__ == "__main__":
    main()
