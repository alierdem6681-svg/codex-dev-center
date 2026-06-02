#!/usr/bin/env python3
import json
import os
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone

try:
    from .task_status_constants import TASK_STATUS_PENDING, normalize_queue_payload
except ImportError:
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

def make_task(run_id, seq, slug, title, description, worker, risk="medium"):
    return {
        "id": f"CTO-ACTION-{run_id}-{seq:02d}-{safe_task_id(slug)}",
        "title": title,
        "description": (
            description.strip()
            + " Beklenen çıktılar: PLAN.md, CHANGE_PROPOSAL.md, TEST_PLAN.md, "
              "RISK_REVIEW.md, LIVING_DOCS_CHECKLIST.md, WORKER_SUMMARY.md. "
              "Ana repo dosyalarını değiştirme. Production yapma."
        ),
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
        "delivery_level": "BACKLOG"
    }

def build_backlog(raw_text, run_id):
    text = (raw_text or "").lower()
    tasks = []

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
                "worker-1"
            ),
            make_task(
                run_id, 2,
                "action-watcher-race-fix",
                "Action Watcher Race Fix",
                "Action watcher ve worker kapanışları arasındaki race condition için çözüm planı üret. Worker logu FAILED iken queue RUNNING kalmasın. Stale RUNNING cleaner ve reconcile akışını planla.",
                "worker-3"
            ),
            make_task(
                run_id, 3,
                "deterministic-proposal-artifacts",
                "Deterministic Proposal Artifacts",
                "Her proposal görevinde PLAN, CHANGE_PROPOSAL, TEST_PLAN, RISK_REVIEW, LIVING_DOCS_CHECKLIST ve WORKER_SUMMARY dosyalarının deterministik üretilmesini sağlayacak planı çıkar. Timeout/retry davranışını iyileştir.",
                "worker-4"
            ),
            make_task(
                run_id, 4,
                "quality-dashboard-living-docs-sync",
                "Quality Gate / Dashboard / Living Docs Sync",
                "Quality gate kayıtlarını, dashboard delivery level görünürlüğünü ve living docs/module settings eksiklerini senkronize edecek plan üret.",
                "worker-2"
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
            "worker-1"
        ),
        make_task(
            run_id, 2,
            "quality-gate-test-simulation",
            "Quality Gate / Test / Simulation",
            "Quality gate, smoke test, simülasyon, kod kalite kontrolü ve diff kontrolü için plan üret.",
            "worker-4"
        ),
        make_task(
            run_id, 3,
            "worker-dispatch-v2",
            "Worker Dispatch v2",
            "Worker rol eşleme, görev dağıtımı, retry, hata denetimi ve takip mantığı için plan üret.",
            "worker-2"
        ),
        make_task(
            run_id, 4,
            "dashboard-pipeline-tracking",
            "Dashboard Pipeline Tracking",
            "Dashboardda pipeline, worker, delivery level, quality gate, staging, approval ve production readiness alanları için plan üret.",
            "worker-2"
        ),
        make_task(
            run_id, 5,
            "staging-rollback-readiness",
            "Staging / Rollback / Production Readiness",
            "Staging health, smoke test, rollback planı, production readiness ve Telegram sonuç raporu akışı için plan üret.",
            "worker-3"
        ),
    ]
    return tasks

def run_action_mode(raw_text):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    lower = (raw_text or "").lower()

    if any(x in lower for x in ["production'a al", "productiona al", "canlıya al", "canliya al", "deploy et"]):
        return (
            "Production aşaması için önce readiness kapıları tamamlanmalı.\n"
            "Quality gate, staging health, smoke test ve rollback planı PASS olursa ayrıca onay istemeden GitHub Actions deploy başlatılabilir."
        )

    queue_path = STATE / "task_queue.json"
    queue = read_json(queue_path, {"tasks": []})
    tasks = queue.setdefault("tasks", [])

    backlog = build_backlog(raw_text, run_id)

    for task in backlog:
        tasks.append(task)

    queue, _changes = normalize_queue_payload(queue)
    write_json(queue_path, queue)

    state_path = STATE / "system_state.json"
    state = read_json(state_path, {})
    state.update({
        "phase": "step_22c_prompt_driven_action_tasks_queued",
        "direct_cto_action_mode_active": True,
        "direct_cto_action_mode_prompt_driven": True,
        "last_direct_cto_action_run_id": run_id,
        "last_direct_cto_action_task_count": len(backlog),
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
        "Production deployed: false\n"
        "Repo applied: false\n"
        "Staging deployed: false\n\n"
        + "\n".join(f"- {t['title']} -> {t['assigned_worker']}" for t in backlog)
        + "\n",
        encoding="utf-8"
    )

    with (LOGS / "system.log").open("a", encoding="utf-8") as f:
        f.write(now() + f" STEP_22C prompt driven action queued run={run_id} tasks={len(backlog)}\n")

    try:
        subprocess.run(["python3", "supervisor/supervisor_cli.py", "dispatch"], cwd=str(APP), timeout=30, text=True, capture_output=True)
    except Exception:
        pass

    try:
        subprocess.run(["python3", "supervisor/lifecycle_manager.py", "wake-now"], cwd=str(APP), timeout=30, text=True, capture_output=True)
    except Exception:
        pass

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
        "İşler proposal/plan aşamasında, güvenli worker akışına verildi."
    ]

    return "\n".join(lines)

if __name__ == "__main__":
    print(run_action_mode("manual"))
