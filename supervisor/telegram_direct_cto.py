#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from .critical_operation_policy import critical_operation_findings
    from .cto_task_router import submit_task, trigger_lifecycle
    from .task_status_constants import read_json as read_state_json, redact_sensitive_text
except ImportError:
    try:
        from critical_operation_policy import critical_operation_findings
        from cto_task_router import submit_task, trigger_lifecycle
        from task_status_constants import read_json as read_state_json, redact_sensitive_text
    except ImportError:
        def critical_operation_findings(value):
            return []
        submit_task = None
        trigger_lifecycle = None
        def read_state_json(path, default):
            try:
                if Path(path).exists():
                    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
            except Exception:
                return default
            return default
        def redact_sensitive_text(value):
            return str(value or "")

PROJECT_ID = "eterna-498108"
APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
OFFSET_FILE = STATE / "telegram_direct_cto_offset.txt"
PASSTHROUGH_AUDIT = LOGS / "direct_cto_passthrough.ndjson"
FAILURE_LOG = LOGS / "direct_cto_failures.log"
CONTINUATION_STATE = STATE / "direct_cto_continuations.json"
ARCHIVE_REVIEW_JOB_ID = "CTO-ARCHIVE-REVIEW-20260604-0753"
ARCHIVE_REVIEW_CONTINUATION_KEY = "archive_review_20260604_0753"
ARCHIVE_REVIEW_TASKS = [
    {
        "title": "Dashboard Pipeline Flow UI Tabs",
        "message": (
            "Arşiv özeti devamı: Pipeline Flow backend canlı görünüyor. Güncel main üzerinden "
            "dashboard pipeline flow yatay tab UI, canlı polling, responsive görünüm, güvenli panel "
            "testleri ve living-docs etkisini tek root task olarak uygula. Aynı işi çoğaltma; hata "
            "olursa kök nedeni aynı task üzerinde çöz."
        ),
    },
    {
        "title": "Dashboard Profile / Account Menu",
        "message": (
            "Arşiv özeti devamı: Eski profile/account menu PR branch'i main'e girmemiş görünüyor. "
            "Güncel main üzerinden küçük kapsamlı profile/account menu task'ı aç, test/risk/dashboard "
            "etkisini doğrula ve aynı işi çoğaltmadan ilerle."
        ),
    },
    {
        "title": "Worker Dispatch v2",
        "message": (
            "Arşiv özeti devamı: Eski Worker Dispatch v2 branch'i conflict'te kalmış ve roadmap'te açık. "
            "Güncel main üzerinden dispatcher/worker root cause yaklaşımıyla tek root task olarak ele al; "
            "hata olursa yeni root task açmadan aynı task üzerinde kök nedeni düzelt."
        ),
    },
]

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

def sha256_text(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()

def compact_text(value, limit=1400):
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

def audit_passthrough(chat_id, from_user, raw_text, cto_input_text, route):
    LOGS.mkdir(parents=True, exist_ok=True)
    record = {
        "created_at": now(),
        "chat_id_hash": sha256_text(chat_id)[:16],
        "from_user_hash": sha256_text(from_user)[:16],
        "raw_message_sha256": sha256_text(raw_text),
        "cto_input_sha256": sha256_text(cto_input_text),
        "raw_length": len(raw_text or ""),
        "cto_input_length": len(cto_input_text or ""),
        "unchanged": raw_text == cto_input_text,
        "redaction_applied": raw_text != cto_input_text,
        "route": route,
        "content_logged": False,
    }
    with PASSTHROUGH_AUDIT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record

def log_failure(run_id, returncode, raw_err, raw_out=""):
    LOGS.mkdir(parents=True, exist_ok=True)
    record = {
        "created_at": now(),
        "run_id": run_id,
        "returncode": returncode,
        "stderr_summary": compact_text(raw_err),
        "stdout_bytes": len(raw_out or ""),
        "stderr_bytes": len(raw_err or ""),
        "prompt_or_message_content_logged": False,
    }
    with FAILURE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

def service_status(name):
    try:
        p = subprocess.run(["systemctl", "is-active", name], text=True, capture_output=True, timeout=8)
        return (p.stdout or p.stderr or "unknown").strip() or "unknown"
    except Exception:
        return "unknown"

def read_json(path, default):
    return read_state_json(Path(path), default)

def queue_counts():
    queue = read_json(STATE / "task_queue.json", {"tasks": []})
    counts = {}
    for task in queue.get("tasks", []):
        status = str(task.get("status", "")).upper() or "UNKNOWN"
        counts[status] = counts.get(status, 0) + 1
    return len(queue.get("tasks", [])), counts

def local_natural_reply(text):
    lowered = (text or "").lower()
    compact = " ".join(lowered.split())
    critical = critical_operation_findings(text)
    if critical:
        return (
            "Bu istek kritik altyapı kapsamına giriyor ve otomatik yapılmayacak.\n"
            "Durum: APPROVAL_REQUIRED.\n"
            "Kısa özet: secret, token/private key/env, IAM, billing, DNS/firewall veya destructive database türü işler için açık onay gerekir."
        )

    if compact in {"cto", "hey cto", "ctom"} or any(x in lowered for x in ["merhaba", "selam", "sistem durumu", "status", "çalışıyor", "calisiyor"]):
        total, counts = queue_counts()
        core = {
            "panel": service_status("codex-panel"),
            "direct_cto": service_status("codex-direct-cto"),
            "lifecycle": service_status("codex-lifecycle"),
            "watchdog": service_status("codex-watchdog"),
        }
        return (
            "Merhaba, CTO aktif.\n"
            f"Panel: {core['panel']}, Telegram CTO: {core['direct_cto']}, lifecycle: {core['lifecycle']}, watchdog: {core['watchdog']}.\n"
            f"Kuyrukta toplam {total} kayıt var. Aktif worker işi şu an otomatik tekli modda yönetilecek.\n"
            "Secret ve teknik logları Telegram'a dökmüyorum; sadece güvenli özet paylaşacağım."
        )

    if any(x in lowered for x in ["kuyruk", "queue", "proposal_done", "failed_no_proposal", "bekleyen görev", "bekleyen gorev"]):
        total, counts = queue_counts()
        return (
            "Kuyruk özeti:\n"
            f"- Toplam: {total}\n"
            f"- READY_FOR_VALIDATION: {counts.get('READY_FOR_VALIDATION', 0)}\n"
            f"- PROPOSAL_READY: {counts.get('PROPOSAL_READY', 0)}\n"
            f"- PROPOSAL_DONE: {counts.get('PROPOSAL_DONE', 0)}\n"
            f"- FAILED_NO_PROPOSAL: {counts.get('FAILED_NO_PROPOSAL', 0)}\n"
            f"- FAILED_TIMEOUT: {counts.get('FAILED_TIMEOUT', 0)}\n"
            f"- FAILED_RETRYABLE: {counts.get('FAILED_RETRYABLE', 0)}\n"
            f"- FAILED: {counts.get('FAILED', 0)}\n"
            f"- QUEUED: {counts.get('QUEUED', 0)}\n"
            "Tekli modda en düşük riskli uygun işi seçip worker'a verecek şekilde ilerliyorum."
        )

    if any(x in lowered for x in ["dashboard health", "health kontrol", "health check", "panel sağlık", "panel saglik"]):
        return (
            "Dashboard health kısa özeti:\n"
            f"- codex-panel: {service_status('codex-panel')}\n"
            f"- codex-lifecycle: {service_status('codex-lifecycle')}\n"
            f"- codex-watchdog: {service_status('codex-watchdog')}\n"
            "Ayrıntılı teknik çıktıyı Telegram'a dökmüyorum; gerekiyorsa güvenli rapor olarak işleyebilirim."
        )

    if any(x in lowered for x in ["pipeline gate", "gate sonuç", "gate sonuc", "readiness"]):
        readiness = read_json(STATE / "production_readiness_status.json", {})
        failed = readiness.get("failed", [])
        status = readiness.get("status", "UNKNOWN")
        score = readiness.get("score_percent", "-")
        return (
            "Pipeline gate özeti:\n"
            f"- Production readiness: {status}\n"
            f"- Skor: {score}\n"
            f"- Fail gate: {', '.join(failed) if failed else 'yok'}\n"
            "Gate PASS ise normal app deploy için ayrıca onay istemeden production akışı çalışabilir."
        )

    if any(x in lowered for x in ["tüm gate", "tum gate", "deploy et", "production'a al", "productiona al", "canlıya al", "canliya al"]):
        readiness = read_json(STATE / "production_readiness_status.json", {})
        if readiness.get("status") == "PASS":
            return (
                "Gate durumu PASS görünüyor. Normal app deploy için ayrıca onay istemem.\n"
                "Yine de task'ın worker çıktısı ve branch/PR/merge marker'ı yoksa deploy adayı saymam; önce bu zinciri tamamlarım."
            )
        return (
            "Production deploy şu an başlatılmayacak; gate PASS değil veya son gate sonucu eksik.\n"
            "Önce fail olan adımı düzelttirip pipeline'ı tekrar çalıştıracağım."
        )

    if any(x in lowered for x in ["teknik log", "traceback", "stack trace", "terminal çıktısı", "terminal ciktisi"]):
        return (
            "Teknik çıktı Telegram'a gönderilmeyecek.\n"
            "Kısa özet: Log/traceback gerekiyorsa ben onu güvenli şekilde inceleyip sana doğal dilde kök neden ve düzeltme özetini vereceğim."
        )

    return None

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

    return cleaned or "CTO teknik çıktı üretti; Telegram'a dökmedim. Kısa özet: Yanıt güvenli doğal dil özetine dönüştürülecek."

def classify_job_metadata(text):
    lowered = (text or "").lower()
    length = len(text or "")

    if any(x in lowered for x in ["production", "canlı", "canli", "deploy", "staging", "rollback"]):
        name = "Production Readiness Analizi"
        eta = "10-20 dakika"
        first_update = "yaklaşık 2 dakika içinde"
        interval = 600
        risk = "orta/yüksek; normal app deploy gate PASS ise otomatik, kritik altyapı işlemi varsa onay gerekli"
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


def wants_summary_before_new_tasks(text):
    lowered = (text or "").lower()
    task_creation_phrases = [
        "yeni görev açmadan önce",
        "yeni gorev acmadan once",
        "görev açmadan önce",
        "gorev acmadan once",
        "yeni task açmadan önce",
        "yeni task acmadan once",
    ]
    summary_words = ["özet", "ozet", "rapor", "incele", "ayır", "ayir", "sınıflandır", "siniflandir"]
    return any(phrase in lowered for phrase in task_creation_phrases) and any(
        word in lowered for word in summary_words
    )


def is_continue_command(text):
    compact = " ".join((text or "").lower().split())
    if compact in {
        "devam",
        "tamam devam",
        "onaylıyorum devam",
        "onayliyorum devam",
        "başla",
        "basla",
        "başlat",
        "baslat",
    }:
        return True
    return "devam" in compact and ("job id" in compact or ARCHIVE_REVIEW_JOB_ID.lower() in compact)


def latest_archive_review_summary_available(log_dir=None):
    log_dir = Path(log_dir) if log_dir is not None else LOGS
    try:
        candidates = sorted(log_dir.glob("async_cto_out_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return False
    for path in candidates[:12]:
        try:
            text = path.read_text(errors="replace")
        except Exception:
            continue
        if ARCHIVE_REVIEW_JOB_ID in text and all(item["title"] in text for item in ARCHIVE_REVIEW_TASKS):
            return True
    return False


def write_state_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    tmp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def queue_archive_review_continuation(requested_by):
    if submit_task is None:
        return {"ok": False, "error": "router_unavailable", "created": []}

    state = read_json(CONTINUATION_STATE, {})
    existing = state.get(ARCHIVE_REVIEW_CONTINUATION_KEY, {})
    if existing.get("status") == "QUEUED":
        return {
            "ok": True,
            "already_queued": True,
            "created": existing.get("task_ids", []),
            "task_titles": existing.get("task_titles", []),
        }

    created = []
    task_titles = []
    for item in ARCHIVE_REVIEW_TASKS:
        routed = submit_task(
            APP,
            source="cto",
            title=item["title"],
            message=item["message"],
            priority="high",
            risk="medium",
            requested_by=requested_by,
            split=False,
            worker_eligible=True,
        )
        task = routed.get("task", {})
        created.append(task.get("id"))
        task_titles.append(item["title"])

    lifecycle = trigger_lifecycle(APP) if trigger_lifecycle is not None else {"ok": False, "error": "lifecycle_unavailable"}
    state[ARCHIVE_REVIEW_CONTINUATION_KEY] = {
        "status": "QUEUED",
        "source_job_id": ARCHIVE_REVIEW_JOB_ID,
        "task_ids": created,
        "task_titles": task_titles,
        "requested_by": requested_by,
        "lifecycle": lifecycle,
        "created_at": now(),
    }
    write_state_json(CONTINUATION_STATE, state)
    return {"ok": True, "already_queued": False, "created": created, "task_titles": task_titles, "lifecycle": lifecycle}


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

def start_async_job(chat_id, raw_text, router_task_id=None, action_command=False):
    import subprocess
    JOBS = STATE / "direct_cto_jobs"
    JOBS.mkdir(parents=True, exist_ok=True)
    job_id = datetime.now(timezone.utc).strftime("JOB-%Y%m%d-%H%M%S-%f")
    job_file = JOBS / (job_id + ".json")
    safe_text = redact_sensitive_text(raw_text)
    meta = classify_job_metadata(safe_text)
    job = {
        "id": job_id,
        "status": "QUEUED",
        "chat_id": str(chat_id),
        "text": safe_text,
        "router_task_id": router_task_id,
        "action_command": bool(action_command),
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
        "Normal app production deploy icin tum gate'ler PASS ise ayrica onay isteme. IAM, secret, token/private key/env, database destructive, DNS, firewall, billing, GCloud mutate veya destructive işlem gerekiyorsa uygulama yapma; APPROVAL_REQUIRED olarak isaretle.",
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
        "--skip-git-repo-check",
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
            "Teknik hata oluştu, düzeltiyorum.\n"
            "Kısa özet: CTO yanıtı süre sınırına takıldı. Teknik çıktıyı Telegram'a göndermedim; işi arka plan/görev akışında ele alacağım."
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
    log_failure(run_id, proc.returncode, raw_err, raw_out)

    if proc.returncode == 124:
        return (
            "Teknik hata oluştu, düzeltiyorum.\n"
            "Kısa özet: CTO yanıtı süre sınırına takıldı. Teknik çıktıyı Telegram'a göndermedim; görevi parçalara ayırıp sürdüreceğim."
        )

    return (
        "Teknik hata oluştu, düzeltiyorum.\n"
        "Kısa özet: CTO çalışma komutu başarısız oldu; teknik çıktı gizlendi ve güvenli hata özeti kaydedildi."
    )

def log_inbox(payload):
    LOGS.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    if "text" in payload:
        payload["text"] = redact_sensitive_text(payload["text"])
    payload.pop("raw", None)
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

    safe_text = redact_sensitive_text(text)
    audit_passthrough(chat_id, from_user, text, safe_text, "intake")

    critical_reply = local_natural_reply(safe_text) if critical_operation_findings(safe_text) else None
    if critical_reply:
        audit_passthrough(chat_id, from_user, text, safe_text, "approval_required")
        send_message(token, chat_id, critical_reply)
        return

    if wants_summary_before_new_tasks(safe_text):
        audit_passthrough(chat_id, from_user, text, safe_text, "summary_before_task_creation")
        job_id = start_async_job(chat_id, safe_text)
        send_message(
            token,
            chat_id,
            f"Önce kısa özeti hazırlıyorum; yeni görev açmayacağım. Job: {job_id}.",
        )
        return

    if is_continue_command(safe_text) and latest_archive_review_summary_available():
        result = queue_archive_review_continuation(from_user)
        audit_passthrough(chat_id, from_user, text, safe_text, "archive_review_continuation")
        if result.get("ok"):
            prefix = "Devamı zaten başlatılmış; task çoğaltmadım." if result.get("already_queued") else "Devamı başlattım."
            send_message(
                token,
                chat_id,
                prefix + "\nTemiz root tasklar:\n- " + "\n- ".join(result.get("task_titles", [])),
            )
        else:
            send_message(token, chat_id, "Devam komutunu aldım ama router şu an hazır değil; teknik hata olarak ele alıyorum.")
        return

    # Açık uygulama/başlatma komutları da Telegram handler'ı bloklamaz.
    # Action mode arka plan job içinde kuyruk/workerlara aktarılır.
    if is_action_command(text):
        router_task_id = None
        if submit_task is not None:
            routed = submit_task(
                APP,
                source="telegram",
                title="Telegram action command",
                message=safe_text,
                priority="high",
                requested_by=from_user,
                split=False,
                worker_eligible=False,
            )
            router_task_id = routed.get("task", {}).get("id")
        job_id = start_async_job(chat_id, safe_text, router_task_id=router_task_id, action_command=True)
        send_message(token, chat_id, f"Başladım. İşi kuyruğa aldım ve arkada sürdürüyorum. Job: {job_id}. İlk ilerleme birazdan gelecek.")
        return

    # Uzun görevlerde Telegram yanıtını bloklama; CTO işi arka planda sürdürür.
    if is_long_task_message(text):
        router_task_id = None
        if submit_task is not None:
            routed = submit_task(
                APP,
                source="telegram",
                title=classify_job_metadata(safe_text)["name"],
                message=safe_text,
                priority="high",
                requested_by=from_user,
                split=True,
                worker_eligible=False,
            )
            router_task_id = routed.get("task", {}).get("id")
            if trigger_lifecycle is not None and routed.get("subtasks"):
                trigger_lifecycle(APP)
        job_id = start_async_job(chat_id, safe_text, router_task_id=router_task_id)
        send_message(token, chat_id, f"Başladım. Kısa bir ilk kontrol yapıp arkada sürdürüyorum. Job: {job_id}.")
        return

    local_reply = local_natural_reply(safe_text)
    if local_reply:
        audit_passthrough(chat_id, from_user, text, safe_text, "local_natural_reply")
        send_message(token, chat_id, local_reply)
        return

    # Lokal/deterministik cevap gerektirmeyen her CTO/Codex işi async yürür.
    job_id = start_async_job(chat_id, safe_text)
    send_message(token, chat_id, f"Aldım. CTO işi arkada çalışıyor; hazır olunca güvenli özet göndereceğim. Job: {job_id}.")

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
