#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .progress_aware_runner import run_progress_aware
    from .state_file_lock import state_file_lock
    from .task_status_constants import (
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_RUNNING,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_status,
        redact_sensitive_text,
    )
except ImportError:
    from progress_aware_runner import run_progress_aware
    from state_file_lock import state_file_lock
    from task_status_constants import (
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_RUNNING,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_status,
        redact_sensitive_text,
    )

APP_DIR = Path("/opt/codex-dev-center")
STATE_DIR = APP_DIR / "state"
LOG_DIR = APP_DIR / "logs"
REPORT_DIR = APP_DIR / "reports"
WORKERS_DIR = APP_DIR / "workers"

QUEUE_PATH = STATE_DIR / "task_queue.json"
WORKERS_PATH = STATE_DIR / "workers.json"
SYSTEM_STATE_PATH = STATE_DIR / "system_state.json"

POLL_SECONDS = 3
WORKER_STALL_SECONDS = int(os.environ.get("CODEX_WORKER_STALL_SECONDS", "420"))
WORKER_GRACE_SECONDS = int(os.environ.get("CODEX_WORKER_GRACE_SECONDS", "180"))
WORKER_MAX_WALL_SECONDS = int(os.environ.get("CODEX_WORKER_MAX_WALL_SECONDS", "14400"))

EXPECTED_WORKER_FILES = [
    "PLAN.md",
    "CHANGE_PROPOSAL.md",
    "TEST_PLAN.md",
    "RISK_REVIEW.md",
    "LIVING_DOCS_CHECKLIST.md",
    "WORKER_SUMMARY.md",
]

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text())
    except Exception:
        return default

def write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    tmp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)

def append_log(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")

def safe_excerpt(value: Any, limit: int = 800) -> str:
    return redact_sensitive_text(str(value or "")).strip()[:limit] or "-"

def tail_file(path: Path, limit: int = 4000) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except Exception:
        return ""
    return ""

def classify_worker_result(
    returncode: int,
    created_files: list[str],
    raw_output: str,
    fallback_used: bool,
) -> tuple[str, str]:
    has_output = bool(str(raw_output or "").strip())
    has_expected_set = len(created_files) >= 4
    has_partial_proposal = bool(created_files) or fallback_used

    if has_expected_set:
        return TASK_STATUS_READY_FOR_VALIDATION, "worker_output_ready_for_validation"
    if has_partial_proposal:
        return TASK_STATUS_PROPOSAL_READY, "worker_proposal_ready_for_cto_review"
    if returncode == 124 and not has_output:
        return TASK_STATUS_FAILED_TIMEOUT, "worker_timeout_without_output"
    if returncode == 124:
        return TASK_STATUS_FAILED_RETRYABLE, "worker_timeout_without_proposal_files"
    if returncode != 0:
        return TASK_STATUS_FAILED_RETRYABLE, "worker_failed_without_proposal_files"
    return TASK_STATUS_FAILED_NO_PROPOSAL, "worker_completed_without_proposal_files"

def write_fallback_proposal_files(workspace: Path, task: dict[str, Any], worker_id: str, reason: str) -> list[str]:
    task_id = safe_excerpt(task.get("id"), 160)
    title = safe_excerpt(task.get("title"), 240)
    desc = safe_excerpt(task.get("description") or task.get("raw_message") or title, 1200)
    risk = safe_excerpt(task.get("risk") or task.get("risk_level") or "medium", 60)
    templates = {
        "PLAN.md": f"""# Plan

Task: {task_id}
Worker: {worker_id}
Risk: {risk}

Fallback nedeni: {reason}

1. Parent/task baglamini guvenli proposal seviyesinde ele al.
2. Ana repo dosyalarina dogrudan dokunma.
3. Kritik altyapi, secret, IAM, billing, DNS, firewall, destructive database ve credential rotation islerini APPROVAL_REQUIRED kabul et.
4. Kucuk, test edilebilir repo/app iyilestirmesi icin CTO review bekleyen oneriyi hazirla.

Ozet:
{desc}
""",
        "CHANGE_PROPOSAL.md": f"""# Change Proposal

Baslik: {title}

Oneri:
- Bu task icin once mevcut rapor/workspace kanitlari CTO tarafindan incelenmeli.
- Uygulanacak degisiklik kucuk tutulmali ve ayri branch/PR uzerinden ilerlemeli.
- Production deploy sadece pipeline gate PASS, PR merge ve health check sonrasi yapilmali.

Kapsam disi:
- Secret/env/token/private key degeri okuma veya degistirme.
- IAM, billing, DNS, firewall, destructive database, credential rotation.
""",
        "TEST_PLAN.md": """# Test Plan

1. Python compile ve JSON/YAML validasyonlarini calistir.
2. Production readiness suite sonucunu PASS olarak dogrula.
3. Ilgili dashboard/API/worker akisina ait smoke check ekle veya mevcut smoke check'i calistir.
4. Deploy sonrasi health check ve VM smoke check PASS olmadan task'i production tamamlandi sayma.
""",
        "RISK_REVIEW.md": f"""# Risk Review

Risk: {risk}

Degerlendirme:
- Fallback proposal ana repo veya production mutasyonu yapmadi.
- Kritik altyapi kapsamina giren isler otomatik yapilmayacak.
- Bu ciktinin amaci CTO review icin guvenli is tanimini tamamlamaktir.

Approval:
- Normal app/repo/pipeline fix: gate PASS ise otomatik ilerleyebilir.
- Kritik altyapi/credential/veri kaybi riski: APPROVAL_REQUIRED.
""",
        "LIVING_DOCS_CHECKLIST.md": """# Living Docs Checklist

- [ ] Degisiklik uygulandiginda ilgili runbook veya policy dokumani guncellendi.
- [ ] Dashboard/worker/pipeline davranisi raporda ozetlendi.
- [ ] Test ve deploy kanitlari final rapora eklendi.
- [ ] Critical operation istisnalari korunuyor.
""",
        "WORKER_SUMMARY.md": f"""# Worker Summary

Worker: {worker_id}
Task: {task_id}
Durum: Fallback proposal tamamlandi.

Kisa ozet:
- Codex alt sureci sure sinirina veya eksik cikti durumuna takildi.
- Worker runner guvenli fallback proposal dosyalarini izole workspace icinde uretti.
- Ana repo dosyasi, production deploy veya kritik altyapi islemi yapilmadi.

Sonraki adim:
CTO bu proposal'i inceleyip uygun gorurse ayri branch/PR/pipeline akisi baslatmali.
""",
    }
    for name, content in templates.items():
        path = workspace / name
        if not path.exists():
            path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return [name for name in templates if (workspace / name).exists()]

def update_worker(worker_id: str, status: str, current_task: str | None = None, note: str | None = None) -> None:
    with state_file_lock(WORKERS_PATH):
        data = read_json(WORKERS_PATH, {"workers": []})
        found = False

        for worker in data.get("workers", []):
            if worker.get("id") == worker_id:
                worker["status"] = status
                worker["current_task"] = current_task
                worker["last_seen"] = now()
                if note:
                    worker["note"] = note
                found = True
                break

        if not found:
            data.setdefault("workers", []).append({
                "id": worker_id,
                "role": "Auto worker",
                "status": status,
                "current_task": current_task,
                "last_seen": now(),
                "note": note or ""
            })

        data["updated_at"] = now()
        write_json(WORKERS_PATH, data)

def reconcile_stale_running_tasks_for_worker(worker_id: str) -> list[str]:
    with state_file_lock(QUEUE_PATH):
        queue = read_json(QUEUE_PATH, {"tasks": []})
        queue, _changes = normalize_queue_payload(queue)
        recovered: list[str] = []

        for task in queue.get("tasks", []):
            if task.get("assigned_worker") != worker_id:
                continue
            if normalize_status(task.get("status")) != TASK_STATUS_RUNNING:
                continue
            task["status"] = TASK_STATUS_FAILED_RETRYABLE
            task["result"] = "worker_service_restarted_before_completion"
            task["delivery_level"] = TASK_STATUS_FAILED_RETRYABLE
            task["production_deployed"] = False
            task["repo_applied"] = False
            task["recovered_by_worker_restart"] = True
            task["finished_at"] = now()
            task["updated_at"] = now()
            recovered.append(str(task.get("id") or ""))

        if recovered:
            queue["updated_at"] = now()
            write_json(QUEUE_PATH, queue)

        return recovered

def claim_task(worker_id: str) -> dict[str, Any] | None:
    with state_file_lock(QUEUE_PATH):
        queue = read_json(QUEUE_PATH, {"tasks": []})
        queue, _changes = normalize_queue_payload(queue)
        tasks = queue.get("tasks", [])

        for task in tasks:
            if not is_worker_eligible_task(task):
                continue
            if task.get("assigned_worker") == worker_id and normalize_status(task.get("status")) == TASK_STATUS_RUNNING:
                return None

        claimed = None

        # Telegram ana görevleri sadece CTO tarafından işlenir.
        # Workerlar ancak router'ın ürettiği source=cto alt görevleri alır.
        for task in tasks:
            if not is_worker_eligible_task(task):
                continue
            if task.get("assigned_worker") == worker_id and normalize_status(task.get("status")) in ("ASSIGNED", "QUEUED", "PENDING"):
                task["status"] = TASK_STATUS_RUNNING
                task["started_at"] = now()
                task["updated_at"] = now()
                claimed = task
                break

        if claimed is None:
            for task in tasks:
                if not is_worker_eligible_task(task):
                    continue
                if task.get("assigned_worker") in (None, "", worker_id) and normalize_status(task.get("status")) in ("PENDING", "QUEUED"):
                    task["assigned_worker"] = worker_id
                    task["status"] = TASK_STATUS_RUNNING
                    task["started_at"] = now()
                    task["updated_at"] = now()
                    claimed = task
                    break

        if claimed is not None:
            queue["updated_at"] = now()
            write_json(QUEUE_PATH, queue)

        return dict(claimed) if claimed is not None else None

def finish_task(
    task_id: str,
    worker_id: str,
    status: str,
    result: str,
    report_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    with state_file_lock(QUEUE_PATH):
        queue = read_json(QUEUE_PATH, {"tasks": []})
        for task in queue.get("tasks", []):
            if task.get("id") == task_id:
                task["status"] = status
                task["result"] = result
                task["finished_at"] = now()
                task["updated_at"] = now()
                if report_path:
                    task["report_path"] = report_path
                if metadata:
                    task.update(metadata)
                break

        queue["updated_at"] = now()
        write_json(QUEUE_PATH, queue)

    with state_file_lock(WORKERS_PATH):
        workers = read_json(WORKERS_PATH, {"workers": []})
        found_executor = False
        for worker in workers.get("workers", []):
            if worker.get("id") == worker_id:
                found_executor = True
            if worker.get("id") == worker_id or worker.get("current_task") == task_id:
                worker["status"] = "IDLE"
                worker["current_task"] = None
                worker["last_seen"] = now()
                worker["note"] = f"Last task {task_id}: {status}"
        write_json(WORKERS_PATH, workers)
    if not found_executor:
        update_worker(worker_id, "IDLE", None, f"Last task {task_id}: {status}")

def update_task_progress(task_id: str, worker_id: str, progress: dict[str, Any]) -> None:
    with state_file_lock(QUEUE_PATH):
        queue = read_json(QUEUE_PATH, {"tasks": []})
        changed = False
        for task in queue.get("tasks", []):
            if task.get("id") != task_id:
                continue
            if task.get("assigned_worker") not in (None, "", worker_id):
                break
            if normalize_status(task.get("status")) != TASK_STATUS_RUNNING:
                break
            task["progress_watchdog"] = {
                "status": progress.get("status"),
                "updated_at": progress.get("updated_at"),
                "elapsed_seconds": progress.get("elapsed_seconds"),
                "last_meaningful_progress_seconds_ago": progress.get("last_meaningful_progress_seconds_ago"),
                "last_output_activity_seconds_ago": progress.get("last_output_activity_seconds_ago"),
                "meaningful_event_count": progress.get("meaningful_event_count"),
            }
            task["updated_at"] = now()
            changed = True
            break
        if changed:
            write_json(QUEUE_PATH, queue)
    if changed:
        update_worker(worker_id, "RUNNING", task_id, "progress_watchdog_running")

def execute_safe_task(worker_id: str, task: dict) -> tuple[str, str, str, dict[str, Any]]:
    import subprocess
    from pathlib import Path

    task_id = task.get("id", "unknown-task")
    title = task.get("title", "Yeni görev")
    desc = task.get("description", title)
    risk = task.get("risk", "medium")

    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_id)[:120]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    workspace = Path("/opt/codex-dev-center/workspaces") / f"worker_{worker_id}_{safe_id}_{run_id}"
    workspace.mkdir(parents=True, exist_ok=True)

    task_log = Path("/opt/codex-dev-center/logs") / f"{task_id}_{worker_id}.log"
    report_path = Path("/opt/codex-dev-center/reports") / f"{task_id}_{worker_id}_REPORT.md"

    prompt = f"""
Sen Codex Dev Center worker'ısın.

Worker:
{worker_id}

Görev:
{title}

Açıklama:
{desc}

Risk:
{risk}

Kurallar:
- Ana repo dosyalarını değiştirme.
- Sadece bu izole workspace içinde dosya oluştur.
- Production deploy yapma.
- IAM, secret, database, DNS, firewall, GCloud mutate işlemi yapma.
- Teknik çıktıyı Telegram'a gönderme.
- Kısa, net, Türkçe yaz.

Bu workspace içinde şu dosyaları oluştur:
1. PLAN.md
2. CHANGE_PROPOSAL.md
3. TEST_PLAN.md
4. RISK_REVIEW.md
5. LIVING_DOCS_CHECKLIST.md
6. WORKER_SUMMARY.md
""".strip()

    prompt_file = workspace / "PROMPT.txt"
    out_file = workspace / "codex.out"
    err_file = workspace / "codex.err"
    prompt_file.write_text(prompt, encoding="utf-8")

    append_log(task_log, f"{now()} WORKER={worker_id} TASK={task_id} CONTROLLED_CODEX_START workspace={workspace}")

    cmd = [
        "codex", "exec",
        "--sandbox", "workspace-write",
        "--skip-git-repo-check",
        "--cd", str(workspace),
        prompt
    ]

    returncode = 1
    progress_state = workspace / "progress_watchdog.json"
    progress_result = run_progress_aware(
        cmd,
        cwd=APP_DIR,
        stdout_path=out_file,
        stderr_path=err_file,
        progress_paths=[workspace],
        git_roots=[APP_DIR],
        progress_state_path=progress_state,
        stall_seconds=WORKER_STALL_SECONDS,
        grace_seconds=WORKER_GRACE_SECONDS,
        max_wall_seconds=WORKER_MAX_WALL_SECONDS,
        on_progress=lambda payload: update_task_progress(task_id, worker_id, payload),
    )
    returncode = int(progress_result.get("returncode") if progress_result.get("returncode") is not None else 1)
    progress_stalled = progress_result.get("status") == "STALLED"

    created = [name for name in EXPECTED_WORKER_FILES if (workspace / name).exists()]
    raw_output = tail_file(out_file) + "\n" + tail_file(err_file)
    fallback_used = False
    if not progress_stalled and len(created) < 4 and (raw_output.strip() or returncode == 0):
        fallback_reason = "codex_timeout_or_incomplete_output" if returncode != 0 else "incomplete_worker_output"
        created = write_fallback_proposal_files(workspace, task, worker_id, fallback_reason)
        fallback_used = True

    if progress_stalled and len(created) < 4:
        status, result = TASK_STATUS_FAILED_RETRYABLE, "progress_watchdog_stalled_without_meaningful_progress"
    else:
        status, result = classify_worker_result(returncode, created, raw_output, fallback_used)
    validation_status = "PENDING" if status == TASK_STATUS_READY_FOR_VALIDATION else "NOT_READY"
    pipeline_status = "NOT_RUN"

    report = f"""# WORKER CONTROLLED EXECUTION REPORT

Tarih: {now()}

Worker: {worker_id}
Task: {task_id}
Başlık: {title}
Risk: {risk}

Sonuç: {status}
Result: {result}
Codex return code: {returncode}
Progress watchdog status: {progress_result.get("status")}
Progress watchdog reason: {progress_result.get("stall_reason", "-")}
Progress watchdog meaningful events: {progress_result.get("meaningful_event_count", 0)}
Fallback used: {str(fallback_used).lower()}
Workspace: {workspace}
Validation status: {validation_status}
Pipeline status: {pipeline_status}

Oluşan dosyalar:
{chr(10).join("- " + x for x in created) if created else "- Yok"}

Not:
Bu adım ana repo dosyalarını değiştirmedi.
DONE değildir; validation ve pipeline PASS olmadan production tamamlandı sayılmaz.
Sadece izole workspace içinde proposal/test/risk/living-docs çıktısı üretti.

Log:
{task_log}
"""
    report_path.write_text(report, encoding="utf-8")
    append_log(
        task_log,
        f"{now()} WORKER={worker_id} TASK={task_id} CONTROLLED_CODEX_DONE status={status} rc={returncode} progress={progress_result.get('status')} created={len(created)} fallback={fallback_used}",
    )

    metadata = {
        "workspace": str(workspace),
        "created_files": created,
        "codex_return_code": returncode,
        "fallback_used": fallback_used,
        "progress_watchdog": progress_result,
        "validation_status": validation_status,
        "pipeline_status": pipeline_status,
        "delivery_level": status,
        "production_deployed": False,
        "repo_applied": False,
    }
    return status, result, str(report_path), metadata

def run_worker(worker_id: str) -> None:
    log_file = LOG_DIR / f"{worker_id}.service.log"
    append_log(log_file, f"{now()} {worker_id} service started pid={os.getpid()}")
    recovered = reconcile_stale_running_tasks_for_worker(worker_id)
    if recovered:
        append_log(log_file, f"{now()} {worker_id} recovered stale RUNNING tasks on restart: {','.join(recovered)}")
    note = "service_started"
    if recovered:
        note = f"service_started_recovered_stale_running={len(recovered)}"
    update_worker(worker_id, "IDLE", None, note)

    while True:
        try:
            update_worker(worker_id, "IDLE", None, "polling")
            task = claim_task(worker_id)

            if not task:
                time.sleep(POLL_SECONDS)
                continue

            task_id = task.get("id", "unknown-task")
            update_worker(worker_id, "RUNNING", task_id, "processing")
            append_log(log_file, f"{now()} {worker_id} claimed {task_id}")

            status, result, report_path, metadata = execute_safe_task(worker_id, task)
            finish_task(task_id, worker_id, status, result, report_path, metadata)
            append_log(log_file, f"{now()} {worker_id} finished {task_id} status={status}")

        except KeyboardInterrupt:
            update_worker(worker_id, "STOPPED", None, "keyboard_interrupt")
            append_log(log_file, f"{now()} {worker_id} stopped")
            raise
        except Exception as exc:
            append_log(log_file, f"{now()} ERROR {exc}")
            append_log(log_file, traceback.format_exc())
            update_worker(worker_id, "ERROR", None, str(exc)[:200])
            time.sleep(POLL_SECONDS)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", required=True)
    args = parser.parse_args()
    run_worker(args.worker_id)

if __name__ == "__main__":
    main()
