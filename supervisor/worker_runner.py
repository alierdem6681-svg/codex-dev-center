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

APP_DIR = Path("/opt/codex-dev-center")
STATE_DIR = APP_DIR / "state"
LOG_DIR = APP_DIR / "logs"
REPORT_DIR = APP_DIR / "reports"
WORKERS_DIR = APP_DIR / "workers"

QUEUE_PATH = STATE_DIR / "task_queue.json"
WORKERS_PATH = STATE_DIR / "workers.json"
SYSTEM_STATE_PATH = STATE_DIR / "system_state.json"

POLL_SECONDS = 3

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

def update_worker(worker_id: str, status: str, current_task: str | None = None, note: str | None = None) -> None:
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

def claim_task(worker_id: str) -> dict[str, Any] | None:
    queue = read_json(QUEUE_PATH, {"tasks": []})
    tasks = queue.get("tasks", [])

    claimed = None

    # Telegram görevleri sadece CTO tarafından işlenir.
    # Workerlar source=telegram olan hiçbir görevi alamaz.
    for task in tasks:
        if task.get("source") == "telegram":
            continue
        if task.get("assigned_worker") == worker_id and task.get("status") in ("ASSIGNED", "QUEUED", "PENDING"):
            task["status"] = "RUNNING"
            task["started_at"] = now()
            task["updated_at"] = now()
            claimed = task
            break

    if claimed is None:
        for task in tasks:
            if task.get("source") == "telegram":
                continue
            if task.get("assigned_worker") in (None, "", worker_id) and task.get("status") in ("PENDING", "QUEUED"):
                if task.get("risk", "low") in ("low", "medium"):
                    task["assigned_worker"] = worker_id
                    task["status"] = "RUNNING"
                    task["started_at"] = now()
                    task["updated_at"] = now()
                    claimed = task
                    break

    if claimed is not None:
        queue["updated_at"] = now()
        write_json(QUEUE_PATH, queue)

    return claimed

def finish_task(task_id: str, worker_id: str, status: str, result: str, report_path: str | None = None) -> None:
    queue = read_json(QUEUE_PATH, {"tasks": []})
    for task in queue.get("tasks", []):
        if task.get("id") == task_id:
            task["status"] = status
            task["result"] = result
            task["finished_at"] = now()
            task["updated_at"] = now()
            if report_path:
                task["report_path"] = report_path
            break

    queue["updated_at"] = now()
    write_json(QUEUE_PATH, queue)
    update_worker(worker_id, "IDLE", None, f"Last task {task_id}: {status}")

def execute_safe_task(worker_id: str, task: dict) -> tuple[str, str]:
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
        "timeout", "180",
        "codex", "exec",
        "--sandbox", "workspace-write",
        "--skip-git-repo-check",
        "--cd", str(workspace),
        prompt
    ]

    with out_file.open("wb") as out, err_file.open("wb") as err:
        proc = subprocess.run(
            cmd,
            cwd="/opt/codex-dev-center",
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            timeout=210
        )

    expected = [
        "PLAN.md",
        "CHANGE_PROPOSAL.md",
        "TEST_PLAN.md",
        "RISK_REVIEW.md",
        "LIVING_DOCS_CHECKLIST.md",
        "WORKER_SUMMARY.md",
    ]
    created = [name for name in expected if (workspace / name).exists()]

    status = "DONE" if proc.returncode == 0 and len(created) >= 4 else "FAILED"

    report = f"""# WORKER CONTROLLED EXECUTION REPORT

Tarih: {now()}

Worker: {worker_id}
Task: {task_id}
Başlık: {title}
Risk: {risk}

Sonuç: {status}
Codex return code: {proc.returncode}
Workspace: {workspace}

Oluşan dosyalar:
{chr(10).join("- " + x for x in created) if created else "- Yok"}

Not:
Bu adım ana repo dosyalarını değiştirmedi.
Sadece izole workspace içinde proposal/test/risk/living-docs çıktısı üretti.

Log:
{task_log}
"""
    report_path.write_text(report, encoding="utf-8")
    append_log(task_log, f"{now()} WORKER={worker_id} TASK={task_id} CONTROLLED_CODEX_DONE status={status} created={len(created)}")

    return status, str(report_path)

def run_worker(worker_id: str) -> None:
    log_file = LOG_DIR / f"{worker_id}.service.log"
    append_log(log_file, f"{now()} {worker_id} service started pid={os.getpid()}")
    update_worker(worker_id, "IDLE", None, "service_started")

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

            status, report_path = execute_safe_task(worker_id, task)
            finish_task(task_id, worker_id, status, "controlled_execution_proposal_completed", report_path)
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
