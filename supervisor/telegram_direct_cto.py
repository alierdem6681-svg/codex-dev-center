#!/usr/bin/env python3
import base64
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ID = "eterna-498108"
APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
OFFSET_FILE = STATE / "telegram_direct_cto_offset.txt"

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

def get_updates(token, offset):
    params = {
        "timeout": 25,
        "allowed_updates": json.dumps(["message"]),
    }
    if offset:
        params["offset"] = offset
    return tg_call(token, "getUpdates", params)

def send_message(token, chat_id, text):
    text = text.strip()
    if not text:
        text = "CTO yanıt üretemedi."
    for part in split_message(text, 3400):
        tg_call(token, "sendMessage", {
            "chat_id": chat_id,
            "text": part,
            "disable_web_page_preview": "true",
        })

def split_message(text, limit):
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < 500:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts

def output_guard(raw):
    text = raw or ""

    blocked_markers = [
        "Task ID:",
        "Worker ID:",
        "queue",
        "task queue",
        "Bu job’da ana repo dosyası değiştirmedim",
        "Bu job'da ana repo dosyası değiştirmedim",
        "Telegram onayı olmadan uygulama yapılmayacak",
        "Log dosyası",
        "Rapor dosyası",
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
        "Sen Codex Dev Center sisteminin CTO",
        "Kullanıcının Telegram mesajı",
    ]

    filtered_lines = []
    for ln in text.splitlines():
        if any(m in ln for m in blocked_markers):
            continue
        filtered_lines.append(ln)
    text = "\n".join(filtered_lines)

    # Kod bloklarını, diff/patch ve uzun teknik dump parçalarını Telegram'a dökme.
    text = re.sub(r"```.*?```", "[Teknik kod bloğu gizlendi.]", text, flags=re.S)
    text = re.sub(r"(?im)^diff --git .*$", "[Diff çıktısı gizlendi.]", text)
    text = re.sub(r"(?im)^Traceback \(most recent call last\):.*", "[Stack trace gizlendi.]", text)
    text = re.sub(r"(?im)^File \".*\", line \d+.*$", "[Dosya/stack detayı gizlendi.]", text)

    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) > 240 and any(x in stripped for x in ["{", "}", ";", "def ", "class ", "import ", "PATH=", "/opt/", "logs/"]):
            continue
        if stripped.startswith(("+++", "---", "@@", "Index:", "commit ")):
            continue
        lines.append(line)

    cleaned = "\n".join(lines).strip()

    if len(cleaned) > 3500:
        cleaned = cleaned[:3400].rstrip() + "\n\n[Yanıt kısaltıldı; teknik ayrıntılar loglara yazıldı.]"

    return cleaned or "CTO teknik çıktı üretti; Telegram'a dökmedim. Daha kısa ve açıklama odaklı yanıt isteyebilirsiniz."

def classify_job_metadata(text):
    lowered = (text or "").lower()
    length = len(text or "")

    if any(x in lowered for x in ["production", "canlı", "canli", "deploy", "staging", "rollback"]):
        name = "Production Readiness Analizi"
        eta = "10-20 dakika"
        first_update = "yaklaşık 2 dakika içinde"
        interval = 600
        risk = "yüksek olabilir; production aşamasında açık onay gerekecek"
    elif any(x in lowered for x in ["pipeline", "quality gate", "test", "simülasyon", "simulasyon"]):
        name = "Pipeline Eksik Analizi"
        eta = "3-8 dakika"
        first_update = "yaklaşık 1 dakika içinde"
        interval = 180
        risk = "düşük/orta"
    elif any(x in lowered for x in ["worker", "görev", "gorev", "modül", "modul"]):
        name = "Görev Dağıtım Planı"
        eta = "2-5 dakika"
        first_update = "yaklaşık 1 dakika içinde"
        interval = 180
        risk = "düşük/orta"
    elif length > 1200:
        name = "Kapsamlı Değerlendirme"
        eta = "5-10 dakika"
        first_update = "yaklaşık 1 dakika içinde"
        interval = 180
        risk = "düşük/orta"
    else:
        name = "Kısa Analiz"
        eta = "1-3 dakika"
        first_update = "yaklaşık 30 saniye içinde"
        interval = 60
        risk = "düşük"

    return {
        "name": name,
        "eta": eta,
        "first_update": first_update,
        "progress_interval_seconds": interval,
        "risk": risk
    }

def is_action_command(text):
    lowered = (text or "").lower()
    action_words = [
        "başlat", "baslat", "uygula", "workerlara dağıt", "workerlara dagit",
        "pipeline kur", "pipeline'ı kur", "pipeline’i kur", "pipeline başlat",
        "görevleri başlat", "gorevleri baslat", "tüm görevleri", "tum gorevleri"
    ]
    return any(w in lowered for w in action_words)

def run_direct_action(text):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "direct_cto_action_mode",
        APP / "supervisor/direct_cto_action_mode.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run_action_mode(text)


def is_long_task_message(text):
    lowered = (text or "").lower()

    # Açıkça arka plan istenirse async.
    explicit_async_phrases = [
        "arka planda çalış",
        "arka planda calis",
        "arkada çalış",
        "arkada calis",
        "hazır olunca bildir",
        "hazir olunca bildir",
        "bitince bildir",
        "uzun görev",
        "uzun gorev",
        "çalışmayı sürdür",
        "calismayi surdur",
        "takip et ve bildir",
        "devam ettikçe bildir",
        "devam ettikce bildir"
    ]

    if any(p in lowered for p in explicit_async_phrases):
        return True

    # Gerçek iş başlatma / pipeline / çok adımlı talimatlar async olmalı.
    work_async_phrases = [
        "pipeline kur",
        "pipeline'ı kur",
        "pipeline’i kur",
        "pipelineı kur",
        "pipeline başlat",
        "pipeline baslat",
        "uçtan uca",
        "uctan uca",
        "workerları yönet",
        "workerleri yönet",
        "tüm görevleri tamamla",
        "tum gorevleri tamamla",
        "görevleri başlat",
        "gorevleri baslat",
        "modülleri tamamla",
        "modulleri tamamla",
        "testlerden geçir",
        "testlerden gecir",
        "canlıya al",
        "canliya al",
        "production"
    ]

    if any(p in lowered for p in work_async_phrases):
        return True

    # Uzun ve çok maddeli metinler async.
    if len(text or "") > 700 and sum(1 for x in ["\n-", "\n1.", "\n2.", "\n3.", "\n4.", "\n5."] if x in (text or "")) >= 2:
        return True

    return False

def start_async_job(chat_id, raw_text):
    import subprocess
    JOBS = STATE / "direct_cto_jobs"
    JOBS.mkdir(parents=True, exist_ok=True)
    job_id = datetime.now(timezone.utc).strftime("JOB-%Y%m%d-%H%M%S-%f")
    job_file = JOBS / (job_id + ".json")
    meta = classify_job_metadata(raw_text)
    job = {
        "id": job_id,
        "status": "QUEUED",
        "chat_id": str(chat_id),
        "text": raw_text,
        "generic_task_name": meta["name"],
        "estimated_duration": meta["eta"],
        "first_update": meta["first_update"],
        "progress_interval_seconds": meta["progress_interval_seconds"],
        "risk_summary": meta["risk"],
        "created_at": now(),
        "updated_at": now()
    }
    job_file.write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n")

    subprocess.Popen(
        ["/usr/bin/python3", str(APP / "supervisor/direct_cto_async_job.py"), job_id],
        cwd=str(APP),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

    subprocess.Popen(
        ["/usr/bin/python3", str(APP / "supervisor/direct_cto_progress_watcher.py"), job_id],
        cwd=str(APP),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

    return job_id

def build_prompt(raw_user_message):
    policy = "\n".join([
        "Sen Codex Dev Center sisteminin CTO'susun.",
        "Kullanıcının Telegram mesajı RAW_USER_MESSAGE alanında birebir verilecek.",
        "Kullanıcı mesajını değiştirme, özetleme veya başka bir ara katmana yönlendirme.",
        "Doğrudan kullanıcıya cevap ver.",
        "Türkçe, doğal, kısa ve yönetici seviyesinde cevap ver.",
        "Normal konuşma ve planlama sorularında gereksiz repo taraması yapma.",
        "Kullanıcı açıkça sistem durumu, dosya, log, kod veya VM kontrolü istemedikçe dosya okuma.",
        "Cevabı mümkünse 8-12 satırda bitir.",
        "Task ID, worker id, kuyruk, iç süreç, log yolu gibi teknik iç bilgileri kullanıcıya gösterme.",
        "Normal cevaplarda şu tür savunma/iç süreç cümleleri yazma: Telegram onayı olmadan uygulama yapılmayacak, bu job’da ana repo dosyası değiştirmedim, task queue’ya aldım, loglara yazdım.",
        "Bu tür kısıtları sadece kullanıcı özellikle sorarsa veya gerçekten risk/onay aşaması geldiyse kısa şekilde belirt.",
        "Kullanıcıya iç süreç değil karar, risk, ilerleme ve sonraki adımı söyle.",
        "Kod, diff, dosya dump, terminal dump ve stack trace dökme.",
        "Gerekiyorsa kısa plan ver; sonra kullanıcıdan net onay bekle.",
        "Production, IAM, secret, database, DNS, firewall, billing, GCloud mutate veya destructive işlem gerekiyorsa uygulama yapma; açık onay iste.",
        "Düşük/orta riskli repo işleri için önce plan/test/diff/report/living-docs akışı öner.",
        "Model politikası: gpt-5.5, reasoning xhigh.",
        "",
        "RAW_USER_MESSAGE_START",
        raw_user_message,
        "RAW_USER_MESSAGE_END",
    ])
    return policy

def run_codex(raw_user_message):
    LOGS.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    prompt = build_prompt(raw_user_message)

    prompt_file = LOGS / ("direct_cto_prompt_" + run_id + ".txt")
    out_file = LOGS / ("direct_cto_out_" + run_id + ".txt")
    err_file = LOGS / ("direct_cto_err_" + run_id + ".txt")

    prompt_file.write_text(prompt, encoding="utf-8")

    cmd = [
        "timeout", "150",
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
                timeout=170
            )
    except subprocess.TimeoutExpired:
        return (
            "Bu yanıt için süre doldu. Teknik çıktıyı Telegram’a göndermedim. "
            "Daha kısa bir mesajla tekrar yazarsanız daha hızlı yanıtlayacağım."
        )
    except Exception:
        return (
            "CTO şu an yanıt üretirken bir çalışma hatası aldı. "
            "Teknik ayrıntıları Telegram’a dökmüyorum; sistem loglarına kaydedildi."
        )

    raw_out = out_file.read_text(errors="replace")
    raw_err = err_file.read_text(errors="replace")

    if proc.returncode == 0 and raw_out.strip():
        return output_guard(raw_out)

    # Hata/timeout durumunda stderr/prompt/session dump asla Telegram'a gönderilmez.
    with (LOGS / "direct_cto_failures.log").open("a", encoding="utf-8") as f:
        f.write(now() + " run_id=" + run_id + " rc=" + str(proc.returncode) + "\n")
        f.write(raw_err[:2000] + "\n")

    if proc.returncode == 124:
        return (
            "Bu yanıt için süre doldu. Teknik çıktıyı Telegram’a göndermedim. "
            "Daha kısa bir mesajla tekrar deneyin veya işi küçük parçalara bölelim."
        )

    return (
        "CTO bu mesaj için sağlıklı yanıt üretemedi. "
        "Teknik çıktı gizlendi; isterseniz mesajı daha kısa göndererek tekrar deneyin."
    )

def log_inbox(payload):
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "direct_cto_inbox.ndjson").open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")

def handle_message(token, expected_chat_id, msg):
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = msg.get("text", "")
    from_user = msg.get("from", {}).get("username") or msg.get("from", {}).get("first_name") or "unknown"

    log_inbox({
        "received_at": now(),
        "chat_id": chat_id,
        "from_user": from_user,
        "text": text,
        "raw": msg,
    })

    if chat_id != str(expected_chat_id):
        send_message(token, chat_id, "Bu bot sadece yetkili kullanıcı için çalışır.")
        return

    if not text.strip():
        send_message(token, chat_id, "Metin mesajı gönderin.")
        return

    # Açık uygulama/başlatma komutlarında CTO Action Mode devreye girer.
    if is_action_command(text):
        reply = run_direct_action(text)
        send_message(token, chat_id, reply)
        return

    # Uzun görevlerde Telegram yanıtını bloklama; CTO işi arka planda sürdürür.
    if is_long_task_message(text):
        start_async_job(chat_id, text)
        send_message(token, chat_id, "Başladım. Kısa bir ilk kontrol yapıp birazdan ilerleme paylaşacağım.")
        return

    # Normal kısa mesajda ACK yok. Mesaj doğrudan Codex CTO'ya gider.
    reply = run_codex(text)
    send_message(token, chat_id, reply)

def main():
    STATE.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    token = secret_value("codex-telegram-bot-token")
    chat_id = secret_value("codex-telegram-chat-id")

    # Eski bridge offset'ini devam ettir; eski mesajları tekrar okumayalım.
    if OFFSET_FILE.exists():
        offset = OFFSET_FILE.read_text().strip()
    else:
        old_offset = STATE / "telegram_update_offset.txt"
        offset = old_offset.read_text().strip() if old_offset.exists() else ""

    with (LOGS / "direct_cto.log").open("a", encoding="utf-8") as f:
        f.write(now() + " direct CTO service started\n")

    while True:
        try:
            data = get_updates(token, offset)
            for item in data.get("result", []):
                offset = str(item["update_id"] + 1)
                OFFSET_FILE.write_text(offset)
                if "message" in item:
                    handle_message(token, chat_id, item["message"])
        except Exception as exc:
            with (LOGS / "direct_cto.log").open("a", encoding="utf-8") as f:
                f.write(now() + " error=" + str(exc)[:500] + "\n")
            time.sleep(5)

if __name__ == "__main__":
    main()
