#!/usr/bin/env python3
import base64
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ID = "eterna-498108"
APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
JOBS = STATE / "direct_cto_jobs"
ACTIVE_STATUSES = {"QUEUED", "RUNNING"}

def now():
    return datetime.now(timezone.utc).isoformat()

def parse_time(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)

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

def tg_send(chat_id, text):
    token = secret_value("codex-telegram-bot-token")
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode()).get("ok", False)

def codex_process_count():
    try:
        p = subprocess.run(
            ["bash", "-lc", "ps -eo cmd | grep '[c]odex exec' | wc -l"],
            text=True,
            capture_output=True,
            timeout=10,
        )
        return int((p.stdout or "0").strip())
    except Exception:
        return 0

def short_job_name(text):
    t = " ".join((text or "").split())
    t = t.replace("CTO,", "").strip()
    if len(t) > 90:
        t = t[:87] + "..."
    return t or "arka plan işi"

def latest_async_out_size(job_created_at):
    try:
        created = parse_time(job_created_at).timestamp()
        files = sorted(LOGS.glob("async_cto_out_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files:
            if p.stat().st_mtime >= created:
                return p.stat().st_size
    except Exception:
        pass
    return 0

def natural_message(job, count):
    text = job.get("text", "")
    generic_name = job.get("generic_task_name") or short_job_name(text)
    eta = job.get("estimated_duration") or "belirleniyor"
    status = job.get("status", "RUNNING")
    created_at = job.get("created_at") or now()
    started_at = job.get("started_at") or created_at
    elapsed = int((datetime.now(timezone.utc) - parse_time(started_at)).total_seconds())
    proc_count = codex_process_count()
    out_size = latest_async_out_size(created_at)
    name = short_job_name(text)

    if status == "QUEUED":
        return f"İlerleme: {generic_name} için hazırlık yapıyorum. Tahmini süre: {eta}."

    if count == 0:
        return f"İlerleme: “{name}” için analize başladım. Önce kapsamı ve eksik kapıları ayırıyorum."

    if out_size > 200:
        return f"İlerleme: “{name}” için bulgular oluşmaya başladı. Şimdi sonucu kısa yönetici özetine dönüştürüyorum."

    if elapsed < 90:
        return f"İlerleme: “{name}” üzerinde çalışıyorum. Şu an eksikleri sınıflandırıyorum; henüz nihai sonuç hazır değil."

    if elapsed < 240:
        return f"İlerleme: “{name}” beklenenden uzun sürdü. Analizi parçalayarak tamamlamaya çalışıyorum."

    return f"İlerleme: “{name}” uzun sürdü. Takılırsa sonucu daha küçük parçalara böleceğim."

def load_job(job_id):
    p = JOBS / (job_id + ".json")
    if not p.exists():
        return None, p
    return json.loads(p.read_text()), p

def is_active_job(job):
    return str((job or {}).get("status") or "").upper() in ACTIVE_STATUSES

def save_job(path, job):
    job["updated_at"] = now()
    path.write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n")

def dynamic_progress_interval(job):
    text = (job.get("text") or "").lower()

    # Eğer job metadata içinde interval geldiyse onu kullan.
    try:
        value = int(job.get("progress_interval_seconds") or 0)
        if value >= 30:
            return value
    except Exception:
        pass

    # Büyük production / staging / rollback işleri: seyrek bilgi.
    if any(x in text for x in ["production", "canlı", "canli", "deploy", "staging", "rollback", "uçtan uca", "uctan uca"]):
        return 600   # 10 dakika

    # Pipeline / test / worker / dashboard işleri: orta aralık.
    if any(x in text for x in ["pipeline", "quality gate", "worker", "dashboard", "test", "simülasyon", "simulasyon"]):
        return 180   # 3 dakika

    # Kısa async işler.
    return 60        # 1 dakika

def sleep_until_next_update_or_terminal(job_id, total_seconds, poll_seconds=5):
    deadline = time.time() + max(0, int(total_seconds or 0))
    while time.time() < deadline:
        job, _job_path = load_job(job_id)
        if not job or not is_active_job(job):
            return True
        time.sleep(min(float(poll_seconds), max(0, deadline - time.time())))
    return False

def main(job_id):
    time.sleep(5)

    max_updates = 40

    for count in range(max_updates):
        job, job_path = load_job(job_id)
        if not job:
            return 0

        if not is_active_job(job):
            return 0

        chat_id = job.get("chat_id")
        msg = natural_message(job, count)

        # Aynı mesajı birebir tekrar gönderme.
        if job.get("last_progress_message") != msg:
            try:
                tg_send(chat_id, msg)
                job["last_progress_message"] = msg
                job["last_progress_sent_at"] = now()
                job["progress_update_count"] = int(job.get("progress_update_count", 0)) + 1
                save_job(job_path, job)
            except Exception as e:
                LOGS.mkdir(parents=True, exist_ok=True)
                with (LOGS / "direct_cto_progress_watcher.log").open("a", encoding="utf-8") as f:
                    f.write(now() + " telegram_error=" + str(e)[:300] + "\n")

        if sleep_until_next_update_or_terminal(job_id, dynamic_progress_interval(job)):
            return 0

    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
