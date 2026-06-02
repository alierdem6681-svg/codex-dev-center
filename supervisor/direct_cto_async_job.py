#!/usr/bin/env python3
import base64
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from cto_task_router import mark_task_status
    from task_status_constants import (
        TASK_STATUS_DONE,
        TASK_STATUS_ERROR,
        TASK_STATUS_FAILED,
        TASK_STATUS_RUNNING,
        TASK_STATUS_TIMEOUT,
        redact_sensitive_text,
    )
except ImportError:
    mark_task_status = None
    TASK_STATUS_DONE = "DONE"
    TASK_STATUS_ERROR = "ERROR"
    TASK_STATUS_FAILED = "FAILED"
    TASK_STATUS_RUNNING = "RUNNING"
    TASK_STATUS_TIMEOUT = "TIMEOUT"
    def redact_sensitive_text(value):
        return str(value or "")

PROJECT_ID = "eterna-498108"
APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
JOBS = STATE / "direct_cto_jobs"

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
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    return base64.b64decode(data["payload"]["data"]).decode().strip()

def tg_call(token, method, params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/" + method,
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=35) as r:
        return json.loads(r.read().decode())

def send_message(chat_id, text):
    token = secret_value("codex-telegram-bot-token")
    text = (text or "").strip() or "CTO yanıt üretemedi."
    while len(text) > 3400:
        part = text[:3400]
        tg_call(token, "sendMessage", {"chat_id": chat_id, "text": part, "disable_web_page_preview": "true"})
        text = text[3400:].lstrip()
    tg_call(token, "sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"})

def output_guard(raw):
    text = raw or ""

    blocked_markers = [
        "OpenAI Codex v",
        "Reading additional input from stdin",
        "workdir:",
        "model:",
        "provider:",
        "approval:",
        "sandbox:",
        "reasoning effort:",
        "reasoning summaries:",
        "session id:",
        "RAW_USER_MESSAGE_START",
        "RAW_USER_MESSAGE_END",
        "Traceback",
    ]

    lines = []
    for ln in text.splitlines():
        if any(m in ln for m in blocked_markers):
            continue
        stripped = ln.strip()
        if stripped.startswith(("diff --git", "+++", "---", "@@", "commit ")):
            continue
        if len(stripped) > 240 and any(x in stripped for x in ["/opt/", "logs/", "state/", "{", "}", "def ", "class "]):
            continue
        lines.append(ln)

    cleaned = "\n".join(lines).strip()
    if len(cleaned) > 3500:
        cleaned = cleaned[:3300].rstrip() + "\n\n[Yanıt kısaltıldı; teknik ayrıntılar loglara yazıldı.]"
    return cleaned or "CTO teknik çıktı üretti; Telegram’a dökmedim."

def build_prompt(raw_user_message):
    return "\n".join([
        "Sen Codex Dev Center sisteminin CTO'susun.",
        "Bu bir arka plan CTO job çalışmasıdır.",
        "Kullanıcının mesajı aşağıda birebir verilmiştir.",
        "Kullanıcı mesajını değiştirme veya yeniden yorumlama; doğrudan iş olarak değerlendir.",
        "Türkçe, kısa, doğal ve yönetici seviyesinde sonuç üret.",
        "Kod, diff, terminal dump, dosya dump, stack trace gönderme.",
        "Production, IAM, secret, database, DNS, firewall, billing, GCloud mutate veya destructive işlem gerekiyorsa uygulama yapma; açık onay gerektiğini belirt.",
        "Düşük/orta riskli işlerde plan, test, risk, dashboard ve living-docs akışını öner.",
        "Eğer görev uzun geliştirme/pipeline işiyse uygulanacak adımları sırala; ana repo dosyalarını bu job içinde değiştirme.",
        "Mevcut çalışma kökü: /opt/codex-dev-center.",
        "Model politikası: gpt-5.5, reasoning xhigh.",
        "",
        "RAW_USER_MESSAGE_START",
        raw_user_message,
        "RAW_USER_MESSAGE_END",
    ])

def run_job(job_id):
    job_file = JOBS / (job_id + ".json")
    job = json.loads(job_file.read_text())
    chat_id = job["chat_id"]
    raw_text = job["text"]
    router_task_id = job.get("router_task_id")

    job["status"] = "RUNNING"
    job["started_at"] = now()
    job_file.write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n")
    if router_task_id and mark_task_status is not None:
        mark_task_status(APP, router_task_id, TASK_STATUS_RUNNING, "async_cto_job_started")

    LOGS.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    prompt = build_prompt(raw_text)
    prompt_file = LOGS / ("async_cto_prompt_" + run_id + ".txt")
    out_file = LOGS / ("async_cto_out_" + run_id + ".txt")
    err_file = LOGS / ("async_cto_err_" + run_id + ".txt")
    prompt_file.write_text(prompt, encoding="utf-8")

    cmd = [
        "timeout", "1800",
        "codex", "exec",
        "--sandbox", "read-only",
        "--cd", str(APP),
        "-"
    ]

    try:
        with prompt_file.open("rb") as stdin, out_file.open("wb") as out, err_file.open("wb") as err:
            proc = subprocess.run(
                cmd,
                cwd=str(APP),
                stdin=stdin,
                stdout=out,
                stderr=err,
                timeout=1900
            )

        raw_out = out_file.read_text(errors="replace")
        raw_err = err_file.read_text(errors="replace")

        if proc.returncode == 0 and raw_out.strip():
            msg = output_guard(raw_out)
            send_message(chat_id, msg)
            job["status"] = TASK_STATUS_DONE
            job["result"] = "telegram_notified"
            if router_task_id and mark_task_status is not None:
                mark_task_status(APP, router_task_id, TASK_STATUS_DONE, "async_cto_job_done")
        else:
            with (LOGS / "async_cto_failures.log").open("a", encoding="utf-8") as f:
                f.write(now() + " job=" + job_id + " rc=" + str(proc.returncode) + "\n")
                f.write(raw_err[:2500] + "\n")
            send_message(chat_id, "CTO bu arka plan işi tamamlayamadı. Teknik çıktı Telegram’a gönderilmedi; loglara kaydedildi.")
            job["status"] = TASK_STATUS_FAILED
            job["result"] = "codex_failed"
            if router_task_id and mark_task_status is not None:
                mark_task_status(APP, router_task_id, TASK_STATUS_FAILED, "async_cto_job_failed")

    except subprocess.TimeoutExpired:
        send_message(chat_id, "CTO arka plan işi süre sınırına takıldı. Teknik çıktı gönderilmedi. İşi daha küçük parçalara bölelim.")
        job["status"] = TASK_STATUS_TIMEOUT
        job["result"] = "timeout"
        if router_task_id and mark_task_status is not None:
            mark_task_status(APP, router_task_id, TASK_STATUS_TIMEOUT, "async_cto_job_timeout")
    except Exception as exc:
        send_message(chat_id, "CTO arka plan işi sırasında hata aldı. Teknik çıktı Telegram’a gönderilmedi.")
        job["status"] = TASK_STATUS_ERROR
        job["result"] = redact_sensitive_text(str(exc))[:300]
        if router_task_id and mark_task_status is not None:
            mark_task_status(APP, router_task_id, TASK_STATUS_ERROR, "async_cto_job_error")

    job["finished_at"] = now()
    job_file.write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    run_job(sys.argv[1])
