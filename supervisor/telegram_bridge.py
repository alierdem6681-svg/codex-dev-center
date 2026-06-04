#!/usr/bin/env python3
import base64
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ID = "eterna-498108"
APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"

OFFSET_FILE = STATE / "telegram_update_offset.txt"


def truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}

def now():
    return datetime.now(timezone.utc).isoformat()

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

def api_url(token, method):
    return f"https://api.telegram.org/bot{token}/{method}"

def telegram_call(token, method, params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(api_url(token, method), data=data, method="POST")
    with urllib.request.urlopen(req, timeout=35) as r:
        return json.loads(r.read().decode())

def send_message(token, chat_id, text):
    return telegram_call(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text[:3500],
        "disable_web_page_preview": "true",
    })

def get_updates(token, offset):
    params = {
        "timeout": 25,
        "allowed_updates": json.dumps(["message"]),
    }
    if offset:
        params["offset"] = offset
    return telegram_call(token, "getUpdates", params)

def read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


def bridge_polling_enabled(config=None, module_settings=None, env=None):
    env = os.environ if env is None else env
    override = str(env.get("CODEX_TELEGRAM_BRIDGE_POLLING_ENABLED", "")).strip()
    if override:
        return truthy(override)

    if config is None:
        config = read_json(STATE / "telegram_config.json", {})
    if module_settings is None:
        module_settings = read_json(
            STATE / "module_settings.json",
            read_json(APP / "state_templates/module_settings.json", {}),
        )

    telegram_settings = {}
    if isinstance(module_settings, dict):
        telegram_settings = module_settings.get("telegram", {}) or {}

    if config.get("old_bridge_disabled") is True or telegram_settings.get("old_bridge_disabled") is True:
        return False
    if config.get("direct_cto_mode") is True or telegram_settings.get("direct_cto_mode") is True:
        return False
    return True


def idle_when_direct_cto_owns_polling():
    with (LOGS / "telegram_bridge.log").open("a", encoding="utf-8") as f:
        f.write(f"{now()} telegram bridge polling disabled; direct_cto_owns_polling=true\n")
    while True:
        time.sleep(60)

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

def add_task_from_telegram(text, from_user, chat_id):
    queue_path = STATE / "task_queue.json"
    queue = read_json(queue_path, {"tasks": []})
    tasks = queue.setdefault("tasks", [])

    task_id = "TG-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    task = {
        "id": task_id,
        "title": text[:120] if text else "Telegram message",
        "description": text,
        "source": "telegram",
        "from_user": from_user,
        "chat_id": str(chat_id),
        "status": "PENDING",
        "risk": "low",
        "assigned_worker": None,
        "created_at": now(),
        "updated_at": now()
    }

    tasks.append(task)
    write_json(queue_path, queue)
    return task_id

def log_inbox(payload):
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "telegram_inbox.ndjson").open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")

def status_text():
    services = ["codex-panel", "codex-watchdog", "codex-lifecycle", "codex-telegram-bridge"]
    lines = ["Codex Dev Center status:"]
    import subprocess
    for svc in services:
        p = subprocess.run(["systemctl", "is-active", svc], text=True, capture_output=True)
        lines.append(f"- {svc}: {(p.stdout or p.stderr).strip()}")
    try:
        phase = read_json(STATE / "system_state.json", {}).get("phase", "unknown")
        lines.append(f"Phase: {phase}")
    except Exception:
        pass
    return "\n".join(lines)

def handle_message(token, expected_chat_id, msg):
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = msg.get("text", "")
    from_user = msg.get("from", {}).get("username") or msg.get("from", {}).get("first_name") or "unknown"

    payload = {
        "received_at": now(),
        "chat_id": chat_id,
        "from_user": from_user,
        "text": text,
        "raw": msg
    }
    log_inbox(payload)

    if chat_id != str(expected_chat_id):
        send_message(token, chat_id, "Bu bot sadece yetkili chat id ile çalışır.")
        return

    if text.strip() in ["/start", "/help"]:
        send_message(token, chat_id,
            "Codex Dev Center Telegram Bridge aktif.\n\n"
            "Komutlar:\n"
            "/status - servis durumunu göster\n"
            "/help - yardım\n\n"
            "Bunun dışındaki mesajlar CTO görev kuyruğuna aynen alınır."
        )
        return

    if text.strip() == "/status":
        send_message(token, chat_id, status_text())
        return

    task_id = add_task_from_telegram(text, from_user, chat_id)
    clean_title = " ".join((text or "Yeni görev").strip().split())[:80]
    send_message(token, chat_id,
        "Mesaj alındı: " + clean_title + "\n"
        "Durum: CTO değerlendiriyor."
    )

def main():
    STATE.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    if not bridge_polling_enabled():
        idle_when_direct_cto_owns_polling()

    token = secret_value("codex-telegram-bot-token")
    chat_id = secret_value("codex-telegram-chat-id")

    offset = OFFSET_FILE.read_text().strip() if OFFSET_FILE.exists() else ""

    with (LOGS / "telegram_bridge.log").open("a", encoding="utf-8") as f:
        f.write(f"{now()} telegram bridge started\n")

    while True:
        try:
            data = get_updates(token, offset)
            for item in data.get("result", []):
                offset = str(item["update_id"] + 1)
                OFFSET_FILE.write_text(offset)
                if "message" in item:
                    handle_message(token, chat_id, item["message"])
        except Exception as e:
            with (LOGS / "telegram_bridge.log").open("a", encoding="utf-8") as f:
                f.write(f"{now()} error={e}\n")
            time.sleep(5)

if __name__ == "__main__":
    main()
