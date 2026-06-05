#!/usr/bin/env python3
import json
import os
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone

try:
    from .memory_os_context import (
        bind_existing_scope_in_queue,
        bind_task_to_scope,
        conversation_key as memory_os_conversation_key,
        find_latest_scope_in_queue,
        is_memory_os_followup_text,
        is_memory_os_request,
        record_scope,
        scope_has_worker_apply_tasks,
    )
    from .task_status_constants import TASK_STATUS_PENDING, normalize_queue_payload
except ImportError:
    from memory_os_context import (
        bind_existing_scope_in_queue,
        bind_task_to_scope,
        conversation_key as memory_os_conversation_key,
        find_latest_scope_in_queue,
        is_memory_os_followup_text,
        is_memory_os_request,
        record_scope,
        scope_has_worker_apply_tasks,
    )
    from task_status_constants import TASK_STATUS_PENDING, normalize_queue_payload

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
REPORTS = APP / "reports"
LOGS = APP / "logs"

def now():
    return datetime.now(timezone.utc).isoformat()

def read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    tmp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)

def safe_task_id(text):
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in text.upper())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:80]

IMPLEMENTATION_SIGNALS = [
    "başla",
    "basla",
    "başlayalım",
    "baslayalim",
    "geliştirme yap",
    "gelistirme yap",
    "geliştirmeye başlayalım",
    "gelistirmeye baslayalim",
    "uygula",
    "düzelt",
    "duzelt",
    "hazırla",
    "hazirla",
    "tamamla",
    "kaldır",
    "kaldir",
    "ekle",
    "yap",
    "canlıya al",
    "canliya al",
]

PLAN_ONLY_SIGNALS = [
    "sadece plan",
    "plan üret",
    "plan uret",
    "öneri üret",
    "oneri uret",
    "analiz et",
    "incele",
    "değerlendir",
    "degerlendir",
]


def wants_implementation_mode(text):
    lowered = (text or "").lower()
    implementation = any(signal in lowered for signal in IMPLEMENTATION_SIGNALS)
    plan_only = any(signal in lowered for signal in PLAN_ONLY_SIGNALS)
    override = any(
        signal in lowered
        for signal in [
            "uygula",
            "düzelt",
            "duzelt",
            "hazırla",
            "hazirla",
            "tamamla",
            "yap",
            "canlıya al",
            "canliya al",
        ]
    )
    return implementation and not (plan_only and not override)


def normalize_turkish(value):
    return (
        str(value or "").lower()
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )


def wants_memory_os(text):
    return is_memory_os_request(text)


def is_pure_deploy_command(text):
    normalized = normalize_turkish(text)
    deploy_terms = ["canliya al", "production'a al", "productiona al", "deploy et"]
    feature_terms = [
        "gelistir",
        "duzelt",
        "hazirla",
        "tamamla",
        "modul",
        "ekle",
        "kur",
        "memory os",
        "dashboard",
        "telegram",
        "worker",
        "pipeline flow",
    ]
    return any(term in normalized for term in deploy_terms) and not any(term in normalized for term in feature_terms)


def make_task(run_id, seq, slug, title, description, worker, risk="medium", implementation=False, memory_scope=None):
    if implementation:
        task_description = (
            description.strip()
            + " Beklenen çıktı: plan/proposal ile durma; izole repo clone ve branch üzerinde "
              "gerekli en küçük kod/doküman/test değişikliğini uygula, lokal gate/testleri çalıştır, "
              "diff ve rollback notunu üret. Production deploy yapma; deploy için pipeline/finalizer bekle."
        )
        delivery_level = "REPO_APPLY_QUEUED"
    else:
        task_description = (
            description.strip()
            + " Beklenen çıktılar: PLAN.md, CHANGE_PROPOSAL.md, TEST_PLAN.md, "
              "RISK_REVIEW.md, LIVING_DOCS_CHECKLIST.md, WORKER_SUMMARY.md. "
              "Ana repo dosyalarını değiştirme. Production yapma."
        )
        delivery_level = "BACKLOG"

    task = {
        "id": f"CTO-ACTION-{run_id}-{seq:02d}-{safe_task_id(slug)}",
        "title": title,
        "description": task_description,
        "source": "cto",
        "trigger": "direct_cto_action_mode",
        "status": TASK_STATUS_PENDING,
        "risk": risk,
        "assigned_worker": worker,
        "created_at": now(),
        "updated_at": now(),
        "repo_applied": False,
        "staging_deployed": False,
        "production_deployed": False,
        "delivery_level": delivery_level,
    }
    if implementation:
        task.update(
            {
                "worker_eligible": True,
                "repo_apply_allowed": True,
                "execution_mode": "repo_apply",
                "dispatcher_mode": "apply",
                "requires_pipeline_before_deploy": True,
                "plan_only": False,
            }
        )
    if memory_scope:
        bind_task_to_scope(task, memory_scope)
    return task


def apply_memory_os_scope(tasks, memory_scope):
    if not tasks:
        return tasks
    scope = memory_scope if memory_scope is not None else {}
    root_task_id = str(scope.get("root_task_id") or tasks[0]["id"])
    scope.setdefault("scope_id", f"memory-os:{root_task_id}")
    scope["root_task_id"] = root_task_id
    scope.setdefault("title", "Memory OS Modülü")
    scope.setdefault("active", True)
    scope["has_worker_apply_tasks"] = True
    for task in tasks:
        bind_task_to_scope(task, scope, root_task_id=root_task_id)
    return tasks

def wants_observed_issue_backlog(text):
    lowered = (text or "").lower()
    creation = any(x in lowered for x in [
        "görev olarak aç", "gorev olarak ac", "görevleri aç", "gorevleri ac",
        "görev aç", "gorev ac", "kendine görev", "kendine gorev",
    ])
    issue_terms = any(x in lowered for x in [
        "hata", "eksik", "sorun", "aksaklık", "aksaklik", "logları incele", "loglari incele",
    ])
    count_requested = "10" in lowered or "on " in lowered or "on adet" in lowered
    return creation and issue_terms and count_requested

def observed_issue_backlog(run_id, implementation=False):
    items = [
        (
            "read-only-dry-run-test-mode",
            "Read-only / Dry-run Test Mode",
            "Read-only Codex/CTO analizlerinde readiness, drift ve smoke kontrollerinin state/report yazmadan güvenli çalışmasını standartlaştıran öneriyi üret. Salt okunur ortamda crash yerine write-skipped kanıtı dönmeli.",
            "worker-1",
        ),
        (
            "safe-test-scratch-standard",
            "Safe Test Scratch Standard",
            "Unit/integration testleri için runtime state ve repo dosyalarını kirletmeyen güvenli temp/scratch alanı standardını çıkar. Testler read-only veya izole temp dizininde deterministik çalışmalı.",
            "worker-2",
        ),
        (
            "dashboard-quality-gate-status-contract",
            "Dashboard Quality Gate Status Contract",
            "Eski quality_gate_status alanı ile yeni readiness/health kaynakları arasındaki dashboard tutarsızlığını incele ve tek kaynaklı görünüm sözleşmesi öner.",
            "worker-3",
        ),
        (
            "drift-module-settings-registry",
            "Drift Module Settings Registry",
            "Drift uyarılarında eksik görünen module settings ve registry kayıtlarını belirle; false-positive üretmeden living docs/state template senkron planı çıkar.",
            "worker-4",
        ),
        (
            "repo-apply-no-change-terminal-state",
            "Repo Apply No-change Terminal State",
            "Repo apply aşamasında değişiklik yoksa retry/backlog döngüsüne girmeden terminal NO_CHANGE/DONE sınıflandırmasına gidecek akışı doğrula ve eksik kalan kontratı öner.",
            "worker-1",
        ),
        (
            "pipeline-failed-root-cause-reporting",
            "Pipeline Failed Root Cause Reporting",
            "PIPELINE_FAILED durumlarında kullanıcıya yeni kök görev açmak yerine kök neden, son hata, retry edilebilirlik ve önerilen düzeltmeyi ayrıştıran rapor akışını tasarla.",
            "worker-2",
        ),
        (
            "production-readiness-misroute-fix",
            "Production Readiness Misroute Fix",
            "Production readiness analizi gibi kontrol işlerinin yanlışlıkla feature delivery/root task gibi sınıflandırılmasını önleyecek router ve pipeline görünürlük kuralını öner.",
            "worker-3",
        ),
        (
            "worker-workspace-codex-bootstrap",
            "Worker Workspace Codex Bootstrap",
            "Worker workspace içinde .codex/config veya gerekli bootstrap eksik olduğunda işi sessizce kaybetmeden erken teşhis eden kontrol ve fallback davranışını planla.",
            "worker-4",
        ),
        (
            "timeout-usage-limit-retry-backoff",
            "Timeout / Usage-limit Retry Backoff",
            "Worker, Direct CTO ve async watchdog timeout/usage-limit durumlarında görev çoğaltmadan kontrollü retry/backoff ve terminal raporlama politikasını çıkar.",
            "worker-1",
        ),
        (
            "atomic-json-tmp-state-audit",
            "Atomic JSON Tmp And State Audit",
            "Atomic JSON yazımları sonrası tmp kalıntıları, state lock kullanımı ve audit kayıtlarını denetle; bozuk/yarım state yazımına karşı temizlik ve gözlemleme planı üret.",
            "worker-2",
        ),
    ]
    return [
        make_task(run_id, idx, slug, title, description, worker, implementation=implementation)
        for idx, (slug, title, description, worker) in enumerate(items, 1)
    ]

def build_backlog(raw_text, run_id, memory_scope=None):
    text = (raw_text or "").lower()
    tasks = []
    implementation = wants_implementation_mode(raw_text)

    if wants_observed_issue_backlog(raw_text):
        return observed_issue_backlog(run_id, implementation=implementation)

    if wants_memory_os(raw_text):
        tasks = [
            make_task(
                run_id, 1,
                "memory-os-intent-contract",
                "Memory OS Intent Contract",
                "Memory OS isteklerini Production Readiness veya genel görev dağıtımına düşürmeden domain intent olarak sınıflandır. Önceki CTO-MEMORY-OS referansını, devam/başlat/onay takip mesajlarını ve canlıya alma hedefini aynı root task zincirinde koru.",
                "worker-1",
                implementation=implementation,
            ),
            make_task(
                run_id, 2,
                "memory-os-runtime-module",
                "Memory OS Runtime Module",
                "Memory OS için güvenli runtime state, kayıt formatı, özetleme/geri çağırma sözleşmesi ve modül registry entegrasyonunu hazırla. Secret/env/token/private key değerlerini kaydetme veya gösterme.",
                "worker-3",
                implementation=implementation,
            ),
            make_task(
                run_id, 3,
                "cto-memory-os-integration",
                "CTO Memory OS Integration",
                "Direct CTO, async job, action mode ve worker dispatch akışlarında Memory OS bağlamını kullan. Aynı konuşmadaki devam/onay mesajları son Memory OS kapsamına bağlansın; yeni kök görev çoğaltılmasın.",
                "worker-2",
                implementation=implementation,
                memory_scope=memory_scope,
            ),
            make_task(
                run_id, 4,
                "memory-os-dashboard-tests",
                "Memory OS Dashboard And Tests",
                "Dashboardda salt okunur Memory OS health/last context görünürlüğü, unit testler, simulator vakaları, production readiness, smoke ve living-docs güncellemelerini tamamla.",
                "worker-4",
                implementation=implementation,
                memory_scope=memory_scope,
            ),
        ]
        return apply_memory_os_scope(tasks, memory_scope or {})

    telegram_asset_requested = "telegram" in text and any(x in text for x in [
        "asset", "dosya", "resim", "fotoğraf", "fotograf", "doküman", "dokuman",
        "görsel", "gorsel", "media", "medya"
    ])
    dashboard_pipeline_expand_requested = (
        "dashboard" in text
        and "pipeline" in text
        and any(x in text for x in ["alt görev", "alt gorev", "ana görev", "ana gorev"])
        and any(x in text for x in ["aç", "ac", "kapan", "kapat", "görünüm", "gorunum", "tıkla", "tikla"])
    )

    if telegram_asset_requested:
        tasks = [
            make_task(
                run_id, 1,
                "telegram-asset-intake-backend",
                "Telegram Asset Intake Backend",
                "Telegram CTO hattinda fotoğraf, doküman ve caption gibi metin dışı mesajları güvenli şekilde algılayacak backend planını üret. Secret/token/env değeri okuma veya gösterme.",
                "worker-1",
                implementation=implementation,
            ),
            make_task(
                run_id, 2,
                "telegram-asset-storage-manifest",
                "Telegram Asset Storage And Manifest",
                "Telegram getFile indirme akışı, boyut limiti, mime/hash kaydı, runtime asset inbox dizini ve manifest sözleşmesi için güvenli plan üret. Repo içine ham dosya koyma.",
                "worker-3",
                implementation=implementation,
            ),
            make_task(
                run_id, 3,
                "dashboard-telegram-asset-inbox",
                "Dashboard Telegram Asset Inbox",
                "Dashboardda salt okunur Telegram Asset Inbox görünümü, asset metadata listesi, caption ve güvenli referans gösterimi için UI/API planı üret.",
                "worker-2",
                implementation=implementation,
            ),
            make_task(
                run_id, 4,
                "telegram-asset-safety-tests",
                "Telegram Asset Safety Tests",
                "Asset kabul, limit, manifest, secret redaction, Telegram simulator, dashboard smoke ve hata durumları için test planı ve risk raporu üret.",
                "worker-4",
                implementation=implementation,
            ),
        ]
        return tasks

    if dashboard_pipeline_expand_requested:
        tasks = [
            make_task(
                run_id, 1,
                "dashboard-pipeline-expand-state-root-cause",
                "Dashboard Pipeline Expand State Root Cause",
                "Pipeline Flow ana görev/alt görev expand-collapse durumunun live polling sonrası kendi kendine açılıp kapanmasının kök nedenini incele. UI state key, selected stage, polling refresh ve DOM render etkisini ayıran değişiklik önerisi üret.",
                "worker-2",
                implementation=implementation,
            ),
            make_task(
                run_id, 2,
                "dashboard-pipeline-expand-state-tests",
                "Dashboard Pipeline Expand State Tests",
                "Ana görev tıklanınca alt görevlerin kullanıcı tercihini koruması, aktif ana görevde kapanınca tekrar açılmaması ve kapalı stage kayıtlarında birkaç saniye sonra kapanma/açılma olmaması için test planı üret.",
                "worker-4",
                implementation=implementation,
            ),
            make_task(
                run_id, 3,
                "dashboard-pipeline-live-polling-contract",
                "Dashboard Pipeline Live Polling Contract",
                "Pipeline Flow API/live polling sözleşmesinde kullanıcı UI state'inin server refresh ile ezilmemesi için küçük güvenli backend/frontend kontrat önerisi üret.",
                "worker-1",
                implementation=implementation,
            ),
        ]
        return tasks

    stabilization_requested = any(x in text for x in [
        "queue/status", "normalizer", "stale running", "race fix",
        "deterministic proposal", "proposal artifact", "quality gate",
        "dashboard", "living-docs", "living docs", "stabilizasyon"
    ])

    if stabilization_requested:
        tasks = [
            make_task(
                run_id, 1,
                "queue-status-normalizer",
                "Queue / Status Normalizer",
                "Queue ve status alanlarını normalize et. RUNNING ama worker IDLE olan işleri tespit et. DONE, PROPOSAL_DONE, FAILED_NO_PROPOSAL ayrımını netleştir. queued/QUEUED, risk/risk_level, approval_requests/approvals alanlarını standartlaştırma planı üret.",
                "worker-1",
                implementation=implementation,
            ),
            make_task(
                run_id, 2,
                "action-watcher-race-fix",
                "Action Watcher Race Fix",
                "Action watcher ve worker kapanışları arasındaki race condition için çözüm planı üret. Worker logu FAILED iken queue RUNNING kalmasın. Stale RUNNING cleaner ve reconcile akışını planla.",
                "worker-3",
                implementation=implementation,
            ),
            make_task(
                run_id, 3,
                "deterministic-proposal-artifacts",
                "Deterministic Proposal Artifacts",
                "Her proposal görevinde PLAN, CHANGE_PROPOSAL, TEST_PLAN, RISK_REVIEW, LIVING_DOCS_CHECKLIST ve WORKER_SUMMARY dosyalarının deterministik üretilmesini sağlayacak planı çıkar. Timeout/retry davranışını iyileştir.",
                "worker-4",
                implementation=implementation,
            ),
            make_task(
                run_id, 4,
                "quality-dashboard-living-docs-sync",
                "Quality Gate / Dashboard / Living Docs Sync",
                "Quality gate kayıtlarını, dashboard delivery level görünürlüğünü ve living docs/module settings eksiklerini senkronize edecek plan üret.",
                "worker-2",
                implementation=implementation,
            ),
        ]
        return tasks

    # Genel pipeline kurulumu istendiğinde varsayılan güvenli paketler.
    tasks = [
        make_task(
            run_id, 1,
            "controlled-apply-pipeline",
            "Controlled Apply Pipeline v1",
            "Proposal seviyesinden gerçek repo değişikliğine kontrollü geçiş için pipeline planı üret. Patch planı, test, diff, report ve rollback notu aşamalarını netleştir.",
            "worker-1",
            implementation=implementation,
        ),
        make_task(
            run_id, 2,
            "quality-gate-test-simulation",
            "Quality Gate / Test / Simulation",
            "Quality gate, smoke test, simülasyon, kod kalite kontrolü ve diff kontrolü için plan üret.",
            "worker-4",
            implementation=implementation,
        ),
        make_task(
            run_id, 3,
            "worker-dispatch-v2",
            "Worker Dispatch v2",
            "Worker rol eşleme, görev dağıtımı, retry, hata denetimi ve takip mantığı için plan üret.",
            "worker-2",
            implementation=implementation,
        ),
        make_task(
            run_id, 4,
            "dashboard-pipeline-tracking",
            "Dashboard Pipeline Tracking",
            "Dashboardda pipeline, worker, delivery level, quality gate, staging, approval ve production readiness alanları için plan üret.",
            "worker-2",
            implementation=implementation,
        ),
        make_task(
            run_id, 5,
            "staging-rollback-readiness",
            "Staging / Rollback / Production Readiness",
            "Staging health, smoke test, rollback planı, production readiness ve Telegram sonuç raporu akışı için plan üret.",
            "worker-3",
            implementation=implementation,
        ),
    ]
    return tasks

def run_action_mode(raw_text, conversation_id="", router_task_id=None):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    if is_pure_deploy_command(raw_text):
        return (
            "Production aşaması için önce readiness kapıları tamamlanmalı.\n"
            "Quality gate, staging health, smoke test ve rollback planı PASS olursa ayrıca onay istemeden GitHub Actions deploy başlatılabilir."
        )

    queue_path = STATE / "task_queue.json"
    queue = read_json(queue_path, {"tasks": []})
    tasks = queue.setdefault("tasks", [])

    memory_intent = wants_memory_os(raw_text)
    memory_followup = is_memory_os_followup_text(raw_text)
    memory_scope = {}
    memory_bound_existing = False
    memory_conversation_id = memory_os_conversation_key(
        source="direct_cto_action",
        conversation_id=conversation_id,
    )
    if memory_intent or memory_followup:
        memory_scope = find_latest_scope_in_queue(queue, conversation_id=memory_conversation_id)
        if router_task_id and (not memory_scope or memory_scope.get("root_task_id") != router_task_id):
            memory_scope = {
                "schema_version": 1,
                "scope_id": f"memory-os:{router_task_id}",
                "root_task_id": router_task_id,
                "conversation_id": memory_conversation_id,
                "title": "Memory OS Modülü",
                "last_user_text": raw_text,
                "active": True,
                "has_worker_apply_tasks": scope_has_worker_apply_tasks(queue, router_task_id),
            }
        if memory_scope and scope_has_worker_apply_tasks(queue, str(memory_scope.get("root_task_id") or "")):
            bound = bind_existing_scope_in_queue(
                queue,
                memory_scope,
                raw_text,
                event_type="action_followup_or_approval" if memory_followup else "action_explicit_request",
                source="direct_cto_action_mode",
            )
            memory_bound_existing = bool(bound)

    if memory_bound_existing or (memory_followup and not memory_scope and not memory_intent):
        backlog = []
    else:
        backlog = build_backlog(raw_text, run_id, memory_scope=memory_scope)
    if memory_intent and not memory_scope and backlog:
        root_task_id = str(backlog[0].get("root_task_id") or backlog[0].get("id") or "")
        memory_scope = {
            "schema_version": 1,
            "scope_id": f"memory-os:{root_task_id}",
            "root_task_id": root_task_id,
            "conversation_id": memory_conversation_id,
            "title": "Memory OS Modülü",
            "last_user_text": raw_text,
            "active": True,
            "has_worker_apply_tasks": True,
        }

    for task in backlog:
        tasks.append(task)

    queue, _changes = normalize_queue_payload(queue)
    write_json(queue_path, queue)

    if memory_intent or memory_bound_existing:
        record_scope(
            APP,
            memory_scope,
            user_text=raw_text,
            task_ids=None if memory_bound_existing else [str(task.get("id") or "") for task in backlog],
            event_type="action_bound_existing_scope" if memory_bound_existing else "action_scope_tasks_queued",
        )

    state_path = STATE / "system_state.json"
    state = read_json(state_path, {})
    state.update({
        "phase": "step_22c_prompt_driven_action_tasks_queued",
        "direct_cto_action_mode_active": True,
        "direct_cto_action_mode_prompt_driven": True,
        "last_direct_cto_action_run_id": run_id,
        "last_direct_cto_action_task_count": len(backlog),
        "last_memory_os_scope_root_task_id": memory_scope.get("root_task_id", ""),
        "last_memory_os_bound_to_existing_scope": memory_bound_existing,
        "production_deployed": False,
        "repo_changes_applied": False,
        "staging_deployed": False,
        "production_deploy_requires_explicit_approval": False,
        "production_deploy_allowed_when_all_gates_pass": True,
        "updated_at": now()
    })
    write_json(state_path, state)

    REPORTS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    report = REPORTS / f"DIRECT_CTO_PROMPT_DRIVEN_ACTION_{run_id}.md"
    report.write_text(
        "DIRECT CTO PROMPT DRIVEN ACTION REPORT\n\n"
        f"Run: {run_id}\n"
        f"Queued tasks: {len(backlog)}\n"
        f"Memory OS scope root: {memory_scope.get('root_task_id', '-')}\n"
        f"Bound existing Memory OS scope: {str(memory_bound_existing).lower()}\n"
        "Production deployed: false\n"
        "Repo applied: false\n"
        "Staging deployed: false\n\n"
        + "\n".join(f"- {t['title']} -> {t['assigned_worker']}" for t in backlog)
        + "\n",
        encoding="utf-8"
    )

    with (LOGS / "system.log").open("a", encoding="utf-8") as f:
        f.write(now() + f" STEP_22C prompt driven action queued run={run_id} tasks={len(backlog)} memory_os_bound_existing={memory_bound_existing}\n")

    if backlog:
        try:
            subprocess.run(["python3", "supervisor/supervisor_cli.py", "dispatch"], cwd=str(APP), timeout=30, text=True, capture_output=True)
        except Exception:
            pass

        try:
            subprocess.run(["python3", "supervisor/lifecycle_manager.py", "wake-now"], cwd=str(APP), timeout=30, text=True, capture_output=True)
        except Exception:
            pass

    if memory_bound_existing:
        lines = [
            "Başlattım.",
            "",
            "Son Memory OS kapsamına bağladım; yeni kök görev açmadım.",
        ]
    else:
        lines = [
            "Başlattım.",
            "",
            "Paketler:"
        ]
        for t in backlog:
            lines.append(f"- {t['title']}")

    lines += [
        "",
        "Production başlatılmadı.",
        (
            "İşler implementation/apply akışına verildi; plan-only kapanış kabul edilmeyecek."
            if wants_implementation_mode(raw_text)
            else "İşler proposal/plan aşamasında, güvenli worker akışına verildi."
        )
    ]

    return "\n".join(lines)

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Queue Direct CTO action tasks.")
    parser.add_argument("text", nargs="*", help="Action text. If omitted, stdin is used when available.")
    args = parser.parse_args()
    raw = " ".join(args.text).strip()
    if not raw and not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
    if not raw:
        parser.print_help()
        raise SystemExit(0)
    print(run_action_mode(raw))
