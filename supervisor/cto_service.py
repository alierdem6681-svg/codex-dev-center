#!/usr/bin/env python3
import base64
import json
import os
import time
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from .task_status_constants import atomic_write_json, read_json as read_state_json
except ImportError:
    from task_status_constants import atomic_write_json, read_json as read_state_json

PROJECT_ID = "eterna-498108"
APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
QUEUE = STATE / "task_queue.json"

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

def send_message(chat_id, text):
    bot_token = secret_value("codex-telegram-bot-token")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text[:3500],
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def read_json(path, default):
    return read_state_json(Path(path), default)

def write_json(path, data):
    atomic_write_json(Path(path), data)

def service_status(name):
    p = subprocess.run(["systemctl", "is-active", name], text=True, capture_output=True, timeout=10)
    return (p.stdout or p.stderr).strip() or "unknown"

def normalize_task_name(text):
    text = " ".join((text or "Yeni görev").strip().split())
    if not text:
        return "Yeni Görev"

    cleaned = text
    prefixes = [
        "CTO, ",
        "CTO ",
        "Lütfen ",
        "lütfen ",
    ]

    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]

    cleaned = cleaned.replace("workera", "worker'a")
    cleaned = cleaned.replace("Workera", "Worker'a")

    return cleaned[:90].strip().title() or "Yeni Görev"

def cto_status_reply(task):
    state = read_json(STATE / "system_state.json", {})
    workers = read_json(STATE / "workers.json", {"workers": []})
    queue = read_json(QUEUE, {"tasks": []})

    services = [
        "codex-panel",
        "codex-watchdog",
        "codex-lifecycle",
        "codex-telegram-bridge",
        "codex-cto",
        "codex-worker-1",
        "codex-worker-2",
        "codex-worker-3",
        "codex-worker-4",
    ]

    active_tasks = [
        t for t in queue.get("tasks", [])
        if t.get("status") in ("PENDING", "QUEUED", "ASSIGNED", "RUNNING")
    ]

    lines = [
        "CTO sistem durum özeti",
        "",
        f"Phase: {state.get('phase', 'unknown')}",
        f"Aktif/bekleyen görev: {len(active_tasks)}",
        "",
        "Servisler:",
    ]

    for s in services:
        lines.append(f"- {s}: {service_status(s)}")

    lines.append("")
    lines.append("Workerlar:")
    for w in workers.get("workers", []):
        lines.append(f"- {w.get('id')}: {w.get('status')}")

    lines.append("")
    lines.append("Not: Bu CTO v1 cevap servisidir. Gerçek Codex CLI yürütme bir sonraki güvenli entegrasyon adımında bağlanacak.")
    return "\n".join(lines)

def generic_reply(task):
    title = task.get("title", "")
    return (
        "CTO mesajınızı aldı ve görev kuyruğuna işledi.\n\n"
        f"Task ID: {task.get('id')}\n"
        f"Mesaj: {title[:180]}\n\n"
        "Şu an CTO v1 aktif: mesaj alıyor, durum okuyabiliyor ve cevap verebiliyor.\n"
        "Sonraki adımda gerçek Codex CLI entegrasyonu bağlanacak.\n\n"
        "Normal uygulama deploy'u tüm gate'ler PASS ise ayrıca onay istemeden yapılabilir. "
        "Secret/token/private key/env, IAM, billing, DNS/firewall veya destructive database işlemleri onaysız yapılmayacak."
    )

def codex_readonly_plan(user_text):
    import subprocess
    from pathlib import Path
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    prompt_path = LOGS / f"cto_plan_prompt_{run_id}.txt"
    out_path = LOGS / f"cto_plan_out_{run_id}.txt"
    err_path = LOGS / f"cto_plan_err_{run_id}.txt"

    prompt = (
        "Sen Codex Dev Center CTO planlama yardımcısısın.\n"
        "Dosya değiştirme. Sadece oku ve kısa Türkçe yönetici planı ver.\n"
        "AGENTS.md, docs/AGENT_ONBOARDING_MAP.md, docs/HANDOVER.md, docs/ROADMAP.md, "
        "docs/LIVING_DOCUMENTATION_POLICY.md, memory/project_memory.md ve state/system_state.json bağlamını dikkate al.\n"        "Eğer kullanıcı proposal veya P0R3 çıktılarından bahsediyorsa, workspaces/worker_*CTO-P0R3* ve reports/CTO-P0R3* dosyalarını da oku.\n\n"
        "Kullanıcı isteği:\n"
        + user_text
        + "\n\nCevap formatı:\n"
        "1. Kısa değerlendirme\n"
        "2. Önerilen uygulama planı\n"
        "3. Worker dağılımı\n"
        "4. Risk / onay durumu\n"
        "5. Başlamak için kullanıcıdan beklenen net ifade\n"
    )

    prompt_path.write_text(prompt, encoding="utf-8")

    cmd = [
        "timeout", "120",
        "codex", "exec",
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--cd", str(APP),
        prompt
    ]

    with out_path.open("wb") as out, err_path.open("wb") as err:
        proc = subprocess.run(
            cmd,
            cwd=str(APP),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            timeout=140
        )

    out_text = out_path.read_text(errors="replace").strip()
    if proc.returncode == 0 and out_text:
        return out_text[:3000]

    return (
        "Planlama motoru şu anda kısa plan üretemedi.\n"
        "Durum: CTO isteği aldı ancak Codex read-only planlama başarısız oldu.\n"
        "Öneri: Tekrar deneyin veya görevi daha kısa yazın."
    )

def terminal_inspector_reply(user_text):
    import subprocess, json
    from pathlib import Path

    text = (user_text or "").lower()
    commands = []

    if any(w in text for w in ["servis", "service", "çalışıyor", "aktif"]):
        commands.append(("Servisler", ["bash", "-lc", "systemctl is-active codex-panel codex-cto codex-telegram-bridge codex-watchdog codex-lifecycle codex-worker-1 codex-worker-2 codex-worker-3 codex-worker-4 2>/dev/null || true"]))

    if any(w in text for w in ["disk", "alan", "storage"]):
        commands.append(("Disk", ["bash", "-lc", "df -h / /opt 2>/dev/null || df -h"]))

    if any(w in text for w in ["ram", "memory", "bellek"]):
        commands.append(("Bellek", ["bash", "-lc", "free -m"]))

    if any(w in text for w in ["yük", "uptime", "cpu"]):
        commands.append(("Yük", ["bash", "-lc", "uptime"]))

    if any(w in text for w in ["queue", "kuyruk", "görev"]):
        commands.append(("Kuyruk", ["bash", "-lc", "python3 - <<'PY2'\nimport json\nfrom pathlib import Path\np=Path('state/task_queue.json')\nd=json.loads(p.read_text()) if p.exists() else {'tasks':[]}\nts=d.get('tasks',[])\nprint('total=',len(ts))\nfor st in ['PENDING','RUNNING','DONE','FAILED','ARCHIVED_STALE']:\n print(st, len([t for t in ts if t.get('status')==st]))\nPY2"]))

    if any(w in text for w in ["hata", "error", "log"]):
        commands.append(("Son Hatalar", ["bash", "-lc", "tail -n 20 logs/system.log 2>/dev/null; tail -n 20 logs/cto_service.log 2>/dev/null"]))

    if not commands:
        commands.append(("Genel Durum", ["bash", "-lc", "echo PHASE=$(python3 -c 'import json; print(json.load(open(\"state/system_state.json\")).get(\"phase\",\"unknown\"))'); systemctl is-active codex-panel codex-cto codex-telegram-bridge codex-watchdog codex-lifecycle 2>/dev/null || true; uptime; df -h / | tail -1"]))

    lines = ["CTO terminal kontrol özeti:"]
    for title, cmd in commands[:4]:
        try:
            p = subprocess.run(cmd, cwd=str(APP), text=True, capture_output=True, timeout=20)
            out = (p.stdout or p.stderr or "").strip()
            lines.append("")
            lines.append(title + ":")
            lines.append(out[:900] if out else "çıktı yok")
        except Exception as e:
            lines.append("")
            lines.append(title + ": hata: " + str(e))

    return "\n".join(lines)[:3200]

def route_task(task):
    text = task.get("description") or task.get("title") or ""
    lowered = text.lower()
    task_id = task.get("id")
    task_name = normalize_task_name(text)

    proposal_plan_words = [
        "p0r3",
        "proposal çıktı",
        "proposal cikti",
        "proposal çıktıları",
        "proposal ciktilari",
        "çıktılarını oku",
        "ciktilarini oku",
        "gerçek uygulama plan",
        "gercek uygulama plan",
        "uygulama planı çıkar",
        "uygulama plani cikar"
    ]

    if any(w in lowered for w in proposal_plan_words):
        return codex_readonly_plan(text)


    high_risk_phrases = [
        "iam yetkisi ver", "owner yetkisi ver",
        "editor yetkisi ver", "secret oku", "secret göster",
        "token değiştir", "token degistir", "private key",
        "veritabanı sil", "database sil", "migration çalıştır",
        "dns değiştir", "firewall aç", "google ads api mutate",
        "billing değiştir", "ödeme değiştir"
    ]

    policy_words = [
        "kural", "kuralı", "politika", "bundan sonra",
        "onay almadan", "onay aldıktan sonra"
    ]

    planning_words = [
        "plan", "planla", "plan çıkar", "planı hazırla",
        "tartış", "konuş", "değerlendir", "fikir", "öner",
        "yol haritası", "strateji", "proposal", "çıktılarını oku", "ciktilarini oku", "uygulama planı", "uygulama plani", "gerçek uygulama planı", "gercek uygulama plani"
    ]

    explicit_work_words = [
        "uygula", "apply", "başla", "basla", "start",
        "tamamla", "complete", "zorunlu hale getir",
        "workerlarla ilerlet", "workerlarla ilerle",
        "workerlara dağıt", "workerlara dagit",
        "workera dağıt", "workera dagit",
        "dispatch", "görevleri oluştur", "gorevleri olustur",
        "görev oluştur", "gorev olustur", "yeni gorev",
        "paketleri oluştur", "paketleri olustur"
    ]

    status_words = [
        "servis", "service", "disk", "ram", "memory", "bellek",
        "queue", "kuyruk", "hata", "error", "log", "uptime",
        "çalışıyor mu", "kontrol et"
    ]

    if any(w in lowered for w in status_words):
        return terminal_inspector_reply(text)

    if any(w in lowered for w in policy_words) and any(
        w in lowered
        for w in ["production", "canlı", "canli", "deploy", "yayına al", "yayina al", "onay isteme", "onay istemeden"]
    ):
        try:
            state_path = STATE / "system_state.json"
            state = read_json(state_path, {})
            state.update({
                "production_deploy_requires_explicit_approval": False,
                "production_deploy_allowed_when_all_gates_pass": True,
                "production_deploy_requires_quality_gate": True,
                "production_deploy_requires_staging": True,
                "production_deploy_requires_rollback_plan": True,
                "critical_infrastructure_requires_approval": False,
                "updated_at": now()
            })
            write_json(state_path, state)
        except Exception:
            pass
        return (
            "Production deploy kuralı kaydedildi.\n"
            "Normal uygulama canlıya alma tüm gate'ler PASS ise ayrıca onay istemeden yapılacak.\n"
            "Secret/token/private key/env/IAM/billing/DNS/firewall/destructive database işleri de onay bekletmeyecek; gate/pipeline sonucuna göre ilerleyecek."
        )

    if any(p in lowered for p in high_risk_phrases):
        if any(w in lowered for w in policy_words):
            try:
                state_path = STATE / "system_state.json"
                state = read_json(state_path, {})
                state.update({
                    "production_deploy_requires_explicit_approval": False,
                    "production_deploy_requires_quality_gate": True,
                    "production_deploy_requires_staging": True,
                    "production_deploy_requires_rollback_plan": True,
                    "production_deploy_requires_telegram_result_report": True,
                    "critical_infrastructure_requires_approval": False,
                    "updated_at": now()
                })
                write_json(state_path, state)
            except Exception:
                pass

            return (
                "Production deploy kuralı kaydedildi.\n"
                "Normal uygulama canlıya alma tüm gate'ler PASS ise ayrıca onay istemeden yapılacak.\n"
                "Öncesinde test, diff, quality gate, staging kontrolü ve rollback planı zorunlu olacak.\n"
                "Secret/token/private key/env/IAM/billing/DNS/firewall/destructive database işleri onay bekletmeyecek; gate/pipeline sonucu belirleyici olacak.\n"
                "Canlıya alma sonrası sonuç, health durumu ve rollback bilgisi Telegram’dan bildirilecek."
            )

        try:
            proc = subprocess.run(
                [
                    "python3", "supervisor/approval_gate.py", "create",
                    "--title", "CTO high risk request",
                    "--description", text[:500],
                    "--risk", "high",
                    "--action", "cto_high_risk_request"
                ],
                cwd=str(APP),
                text=True,
                capture_output=True,
                timeout=30,
            )
            data = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
            approval = data.get("approval", {})
            approval_id = approval.get("id", "unknown")
            words = " ".join(approval.get("required_words", []))
            return (
                "Onay gerekiyor: " + task_name + "\n"
                "Bu işlem yüksek riskli kabul edildi.\n"
                "Devam etmek istiyorsanız şu 3 kelimeyi aynen yazın:\n"
                + words + "\n"
                "Onay kodu: " + approval_id
            )
        except Exception:
            return (
                "Onay gerekiyor: " + task_name + "\n"
                "Bu işlem yüksek riskli kabul edildi."
            )

    if any(w in lowered for w in planning_words) and not any(w in lowered for w in explicit_work_words):
        return codex_readonly_plan(text)

    if any(w in lowered for w in explicit_work_words):
        queue = read_json(QUEUE, {"tasks": []})
        child_id = "CTO-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")

        child = {
            "id": child_id,
            "title": task_name,
            "description": text,
            "source": "cto",
            "parent_task": task_id,
            "status": "PENDING",
            "risk": "medium",
            "assigned_worker": None,
            "created_at": now(),
            "updated_at": now()
        }

        queue.setdefault("tasks", []).append(child)
        write_json(QUEUE, queue)

        try:
            subprocess.run(
                ["python3", "supervisor/supervisor_cli.py", "dispatch"],
                cwd=str(APP),
                text=True,
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass

        return (
            "Görev oluşturuldu: " + task_name + "\n"
            "Durum: Uygun worker kuyruğuna aktarıldı."
        )

    return generic_reply(task)

def process_one():
    queue = read_json(QUEUE, {"tasks": []})
    changed = False

    for task in reversed(queue.get("tasks", [])):
        if task.get("source") == "telegram" and task.get("status") in ("PENDING", "QUEUED", "ASSIGNED", "RUNNING"):
            task["status"] = "RUNNING"
            task["started_at"] = now()
            write_json(QUEUE, queue)

            text = task.get("description") or task.get("title") or ""
            chat_id = task.get("chat_id")

            if "durum" in text.lower() or "status" in text.lower() or "özet" in text.lower():
                reply = cto_status_reply(task)
            else:
                reply = route_task(task)

            send_message(chat_id, reply)

            latest_queue = read_json(QUEUE, {"tasks": []})
            for latest_task in latest_queue.get("tasks", []):
                if latest_task.get("id") == task.get("id"):
                    latest_task["status"] = "READY_FOR_VALIDATION"
                    latest_task["finished_at"] = now()
                    latest_task["result"] = "telegram_cto_v1_replied_validation_required"
                    latest_task["validation_status"] = latest_task.get("validation_status") or "PENDING"
                    latest_task["pipeline_status"] = latest_task.get("pipeline_status") or "NOT_RUN"
                    break
            write_json(QUEUE, latest_queue)
            changed = False

            LOGS.mkdir(parents=True, exist_ok=True)
            with (LOGS / "cto_service.log").open("a", encoding="utf-8") as f:
                f.write(f"{now()} replied task={task.get('id')}\n")

            break

    if changed:
        write_json(QUEUE, queue)

def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "cto_service.log").open("a", encoding="utf-8") as f:
        f.write(f"{now()} CTO service started\n")

    while True:
        try:
            process_one()
        except Exception as e:
            with (LOGS / "cto_service.log").open("a", encoding="utf-8") as f:
                f.write(f"{now()} error={e}\n")
        time.sleep(3)

if __name__ == "__main__":
    main()
