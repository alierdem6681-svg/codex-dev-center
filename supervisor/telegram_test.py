#!/usr/bin/env python3
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ID = "eterna-498108"
APP = Path("/opt/codex-dev-center")

def metadata_token():
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())["access_token"]

def secret_value(secret_name):
    token = metadata_token()
    url = f"https://secretmanager.googleapis.com/v1/projects/{PROJECT_ID}/secrets/{secret_name}/versions/latest:access"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    import base64
    return base64.b64decode(data["payload"]["data"]).decode().strip()

def send_message(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def main():
    bot_token = secret_value("codex-telegram-bot-token")
    chat_id = secret_value("codex-telegram-chat-id")

    text = (
        "Codex Dev Center Telegram test mesajı OK.\n"
        f"Tarih: {datetime.now(timezone.utc).isoformat()}\n"
        "Not: Token gizli tutuldu."
    )

    result = send_message(bot_token, chat_id, text)

    state = APP / "state/telegram_config.json"
    try:
        cfg = json.loads(state.read_text()) if state.exists() else {}
    except Exception:
        cfg = {}

    cfg.update({
        "enabled": False,
        "test_message_sent": bool(result.get("ok")),
        "last_test_at": datetime.now(timezone.utc).isoformat(),
        "bot_token_configured": True,
        "chat_id_configured": True
    })
    state.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")

    (APP / "reports/STEP_18B_REPORT.md").write_text(
        "# STEP 18B REPORT\n\nTelegram secret erişimi ve test mesajı denendi.\n\n"
        f"Telegram API ok: {result.get('ok')}\n"
    )

    with open(APP / "logs/system.log", "a", encoding="utf-8") as f:
        f.write(datetime.now(timezone.utc).isoformat() + " STEP_18B telegram test completed\n")

    print("TELEGRAM_TEST=" + ("OK" if result.get("ok") else "FAIL"))
    print("TELEGRAM_ENABLED=False")
    print("SECRET_ACCESS=OK")

if __name__ == "__main__":
    main()
