#!/usr/bin/env python3
import base64
import json
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ID = "eterna-498108"
APP = Path("/opt/codex-dev-center")

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
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    return base64.b64decode(data["payload"]["data"]).decode().strip()

def sh(cmd):
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=15)
    return (p.stdout.strip() or p.stderr.strip() or "unknown")

def send(text):
    bot_token = secret_value("codex-telegram-bot-token")
    chat_id = secret_value("codex-telegram-chat-id")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def health_report(reason="manual"):
    lines = [
        "Codex Dev Center Health Report",
        f"Reason: {reason}",
        f"Time: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Services:",
    ]

    for svc in SERVICES:
        active = sh(["systemctl", "is-active", svc])
        enabled = sh(["systemctl", "is-enabled", svc])
        lines.append(f"- {svc}: {active} / {enabled}")

    try:
        state = json.loads((APP / "state/system_state.json").read_text())
        lines.append("")
        lines.append(f"Phase: {state.get('phase', 'unknown')}")
    except Exception:
        lines.append("")
        lines.append("Phase: unknown")

    return "\n".join(lines)

def main():
    text = health_report("manual-test")
    result = send(text)

    (APP / "reports/STEP_18D1_TELEGRAM_HEALTH_REPORT.md").write_text(
        "# STEP 18D-1 REPORT\n\nTelegram health reporter kuruldu ve test mesajı gönderildi.\n"
    )

    with open(APP / "logs/system.log", "a", encoding="utf-8") as f:
        f.write(datetime.now(timezone.utc).isoformat() + " STEP_18D1 telegram health reporter ok\n")

    print("TELEGRAM_HEALTH_REPORT=" + ("OK" if result.get("ok") else "FAIL"))
    print("REPORT_FILE=YES")

if __name__ == "__main__":
    main()
