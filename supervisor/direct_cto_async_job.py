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
    from progress_aware_runner import run_progress_aware
    from cto_task_router import mark_task_status
    from task_status_constants import (
        TASK_STATUS_ERROR,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_RUNNING,
        TASK_STATUS_STALLED,
        TASK_STATUS_TIMEOUT,
        redact_sensitive_text,
    )
except ImportError:
    from .progress_aware_runner import run_progress_aware
    from .cto_task_router import mark_task_status
    from .task_status_constants import (
        TASK_STATUS_ERROR,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_RUNNING,
        TASK_STATUS_STALLED,
        TASK_STATUS_TIMEOUT,
        redact_sensitive_text,
    )
except Exception:
    run_progress_aware = None
    mark_task_status = None
    TASK_STATUS_ERROR = "ERROR"
    TASK_STATUS_FAILED_RETRYABLE = "FAILED_RETRYABLE"
    TASK_STATUS_PROPOSAL_READY = "PROPOSAL_READY"
    TASK_STATUS_RUNNING = "RUNNING"
    TASK_STATUS_STALLED = "STALLED"
    TASK_STATUS_TIMEOUT = "TIMEOUT"
    def redact_sensitive_text(value):
        return str(value or "")

PROJECT_ID = "eterna-498108"
APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
REPORTS = APP / "reports"
JOBS = STATE / "direct_cto_jobs"
ASYNC_STALL_SECONDS = int(os.environ.get("CODEX_DIRECT_CTO_STALL_SECONDS", "900"))
ASYNC_GRACE_SECONDS = int(os.environ.get("CODEX_DIRECT_CTO_GRACE_SECONDS", "180"))
ASYNC_MAX_WALL_SECONDS = int(os.environ.get("CODEX_DIRECT_CTO_MAX_WALL_SECONDS", "14400"))

def compact_text(value, limit=1600):
    text = redact_sensitive_text(value or "")
    text = re.sub(r"RAW_USER_MESSAGE_START.*?RAW_USER_MESSAGE_END", "[RAW_USER_MESSAGE_REDACTED]", text, flags=re.S)
    text = re.sub(r"(?is)user\nSen Codex Dev Center.*", "[PROMPT_CONTEXT_REDACTED]", text)
    text = re.sub(r"(?im)^OpenAI Codex v.*$", "[CODEX_HEADER_REDACTED]", text)
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(marker in stripped.lower() for marker in ["session id:", "workdir:", "provider:", "model:", "sandbox:", "reasoning"]):
            continue
        lines.append(stripped)
    return "\n".join(lines)[-limit:]

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

def save_job(job_file, job):
    current = {}
    try:
        if job_file.exists():
            loaded = json.loads(job_file.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                current = loaded
    except Exception:
        current = {}
    current.update(job)
    current["updated_at"] = now()
    job_file.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n")
    job.clear()
    job.update(current)

def update_job_progress(job_file, job, progress):
    job["status"] = "RUNNING"
    job["progress_watchdog"] = {
        "status": progress.get("status"),
        "updated_at": progress.get("updated_at"),
        "elapsed_seconds": progress.get("elapsed_seconds"),
        "last_meaningful_progress_seconds_ago": progress.get("last_meaningful_progress_seconds_ago"),
        "last_output_activity_seconds_ago": progress.get("last_output_activity_seconds_ago"),
        "meaningful_event_count": progress.get("meaningful_event_count"),
    }
    save_job(job_file, job)

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
        "Normal app production deploy icin tum gate'ler PASS ise ayrica onay isteme. IAM, secret, token/private key/env, database destructive, DNS, firewall, billing, GCloud mutate veya destructive işlem gerekiyorsa uygulama yapma; APPROVAL_REQUIRED olarak belirt.",
        "Düşük/orta riskli işlerde plan, test, risk, dashboard ve living-docs akışını öner.",
        "Eğer görev uzun geliştirme/pipeline işiyse uygulanacak adımları sırala; ana repo dosyalarını bu job içinde değiştirme.",
        "Mevcut çalışma kökü: /opt/codex-dev-center.",
        "Model politikası: gpt-5.5, reasoning xhigh.",
        "",
        "RAW_USER_MESSAGE_START",
        raw_user_message,
        "RAW_USER_MESSAGE_END",
    ])

def classify_codex_failure(raw_out, raw_err, progress):
    combined = "\n".join([raw_out or "", raw_err or "", json.dumps(progress or {}, ensure_ascii=False)])
    lowered = combined.lower()

    if any(marker in lowered for marker in [
        "usage limit",
        "purchase more credits",
        "try again at",
        "rate limit",
        "too many requests",
    ]):
        return {
            "status": TASK_STATUS_FAILED_RETRYABLE,
            "result": "codex_usage_limit_retryable",
            "router_reason": "async_cto_codex_usage_limit_retryable",
            "telegram_message": (
                "CTO arka plan işi geçici Codex kullanım limitine takıldı. "
                "Billing veya kritik altyapı işlemi yapmadım; limit açıldığında güvenli şekilde retry edilebilir."
            ),
        }

    return {
        "status": TASK_STATUS_FAILED_RETRYABLE,
        "result": "codex_failed_retryable",
        "router_reason": "async_cto_codex_failed_retryable",
        "telegram_message": (
            "CTO arka plan işi tamamlanamadı. Teknik çıktı Telegram'a gönderilmedi; "
            "iş retry edilebilir hata durumuna alındı."
        ),
    }

def run_job(job_id):
    job_file = JOBS / (job_id + ".json")
    job = json.loads(job_file.read_text())
    chat_id = job["chat_id"]
    raw_text = job["text"]
    router_task_id = job.get("router_task_id")

    job["status"] = "RUNNING"
    job["started_at"] = now()
    save_job(job_file, job)
    if router_task_id and mark_task_status is not None:
        mark_task_status(APP, router_task_id, TASK_STATUS_RUNNING, "async_cto_job_started")

    if job.get("action_command"):
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "direct_cto_action_mode",
                APP / "supervisor/direct_cto_action_mode.py",
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            reply = mod.run_action_mode(raw_text)
            send_message(chat_id, reply)
            job["status"] = "FINAL_REPORTED"
            job["result"] = "action_queued_and_reported"
            if router_task_id and mark_task_status is not None:
                mark_task_status(APP, router_task_id, TASK_STATUS_PROPOSAL_READY, "async_cto_action_queued")
        except Exception as exc:
            send_message(chat_id, "CTO action job hata aldı. Teknik çıktı Telegram'a gönderilmedi; işi retry kuyruğunda ele alacağım.")
            job["status"] = TASK_STATUS_ERROR
            job["result"] = redact_sensitive_text(str(exc))[:300]
            if router_task_id and mark_task_status is not None:
                mark_task_status(APP, router_task_id, TASK_STATUS_FAILED_RETRYABLE, "async_cto_action_error")
        job["finished_at"] = now()
        save_job(job_file, job)
        return

    LOGS.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    prompt = build_prompt(raw_text)
    prompt_file = LOGS / ("async_cto_prompt_" + run_id + ".txt")
    out_file = LOGS / ("async_cto_out_" + run_id + ".txt")
    err_file = LOGS / ("async_cto_err_" + run_id + ".txt")
    prompt_file.write_text(prompt, encoding="utf-8")

    cmd = [
        "codex", "exec",
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--cd", str(APP),
        "-"
    ]

    try:
        if run_progress_aware is None:
            raise RuntimeError("progress_aware_runner_unavailable")
        progress_state = JOBS / (job_id + ".progress.json")
        progress = run_progress_aware(
            cmd,
            cwd=APP,
            stdin_path=prompt_file,
            stdout_path=out_file,
            stderr_path=err_file,
            progress_paths=[
                REPORTS,
                STATE / "task_queue.json",
                STATE / "production_readiness_status.json",
                STATE / "production_deploy_status.json",
                STATE / "production_runtime_status.json",
                STATE / "github_actions_status.json",
            ],
            git_roots=[APP],
            progress_state_path=progress_state,
            stall_seconds=ASYNC_STALL_SECONDS,
            grace_seconds=ASYNC_GRACE_SECONDS,
            max_wall_seconds=ASYNC_MAX_WALL_SECONDS,
            on_progress=lambda payload: update_job_progress(job_file, job, payload),
        )

        raw_out = out_file.read_text(errors="replace")
        raw_err = err_file.read_text(errors="replace")

        if progress.get("status") == "STALLED":
            with (LOGS / "async_cto_failures.log").open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "created_at": now(),
                    "job": job_id,
                    "returncode": 124,
                    "stderr_summary": compact_text(raw_err),
                    "stdout_bytes": len(raw_out or ""),
                    "stderr_bytes": len(raw_err or ""),
                    "progress_status": progress.get("status"),
                    "stall_reason": progress.get("stall_reason"),
                    "prompt_or_message_content_logged": False,
                }, ensure_ascii=False, sort_keys=True) + "\n")
            send_message(chat_id, "CTO arka plan işi STALLED oldu: anlamlı ilerleme görülmedi. Teknik çıktı gönderilmedi; işi daha küçük parçalara bölüp retry edilebilir hale getirdim.")
            job["status"] = TASK_STATUS_STALLED
            job["result"] = "progress_watchdog_stalled"
            job["progress_watchdog"] = progress
            if router_task_id and mark_task_status is not None:
                mark_task_status(APP, router_task_id, TASK_STATUS_FAILED_RETRYABLE, "async_cto_job_stalled")
        elif progress.get("returncode") == 0 and raw_out.strip():
            msg = output_guard(raw_out)
            send_message(chat_id, msg)
            job["status"] = "FINAL_REPORTED"
            job["result"] = "telegram_notified"
            job["progress_watchdog"] = progress
            if router_task_id and mark_task_status is not None:
                mark_task_status(APP, router_task_id, TASK_STATUS_PROPOSAL_READY, "async_cto_job_final_reported")
        else:
            failure = classify_codex_failure(raw_out, raw_err, progress)
            with (LOGS / "async_cto_failures.log").open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "created_at": now(),
                    "job": job_id,
                    "returncode": progress.get("returncode"),
                    "stderr_summary": compact_text(raw_err),
                    "stdout_bytes": len(raw_out or ""),
                    "stderr_bytes": len(raw_err or ""),
                    "progress_status": progress.get("status"),
                    "failure_status": failure["status"],
                    "failure_result": failure["result"],
                    "prompt_or_message_content_logged": False,
                }, ensure_ascii=False, sort_keys=True) + "\n")
            send_message(chat_id, failure["telegram_message"])
            job["status"] = failure["status"]
            job["result"] = failure["result"]
            job["progress_watchdog"] = progress
            if router_task_id and mark_task_status is not None:
                mark_task_status(APP, router_task_id, TASK_STATUS_FAILED_RETRYABLE, failure["router_reason"])

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
    save_job(job_file, job)

if __name__ == "__main__":
    run_job(sys.argv[1])
