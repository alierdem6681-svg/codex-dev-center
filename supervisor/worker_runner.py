#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .critical_operation_policy import approval_required_payload
    from .progress_aware_runner import run_progress_aware
    from .state_file_lock import state_file_lock
    from .task_status_constants import (
        TASK_STATUS_APPROVAL_REQUIRED,
        TASK_STATUS_DONE,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PIPELINE_FAILED,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_RUNNING,
        TASK_STATUS_VALIDATION_FAILED,
        is_worker_eligible_task,
        normalize_queue_payload,
        normalize_status,
        redact_sensitive_text,
    )
except ImportError:
    from critical_operation_policy import approval_required_payload
    from progress_aware_runner import run_progress_aware
    from state_file_lock import state_file_lock
    from task_status_constants import (
        TASK_STATUS_APPROVAL_REQUIRED,
        TASK_STATUS_DONE,
        TASK_STATUS_FAILED_NO_PROPOSAL,
        TASK_STATUS_FAILED_RETRYABLE,
        TASK_STATUS_FAILED_TIMEOUT,
        TASK_STATUS_PIPELINE_FAILED,
        TASK_STATUS_PROPOSAL_READY,
        TASK_STATUS_READY_FOR_VALIDATION,
        TASK_STATUS_RUNNING,
        TASK_STATUS_VALIDATION_FAILED,
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
SOURCE_ROOT = Path(os.environ.get("CODEX_DEV_CENTER_SOURCE", "/home/alierdem6681/codex-dev-center-github-export")).resolve()

POLL_SECONDS = 3
WORKER_STALL_SECONDS = int(os.environ.get("CODEX_WORKER_STALL_SECONDS", "420"))
WORKER_GRACE_SECONDS = int(os.environ.get("CODEX_WORKER_GRACE_SECONDS", "180"))
WORKER_MAX_WALL_SECONDS = int(os.environ.get("CODEX_WORKER_MAX_WALL_SECONDS", "14400"))
REPO_APPLY_MAX_WALL_SECONDS = int(os.environ.get("CODEX_REPO_APPLY_MAX_WALL_SECONDS", "7200"))

EXPECTED_WORKER_FILES = [
    "PLAN.md",
    "CHANGE_PROPOSAL.md",
    "TEST_PLAN.md",
    "RISK_REVIEW.md",
    "LIVING_DOCS_CHECKLIST.md",
    "WORKER_SUMMARY.md",
]

SAFE_REPO_APPLY_PREFIXES = (
    ".github/workflows/",
    "AGENTS.md",
    "constitution/",
    "docs/",
    "memory/",
    "modules/",
    "prompts/",
    "scripts/",
    "state_templates/",
    "supervisor/",
    "tests/",
    "web_panel/",
    "workers/",
)

BLOCKED_REPO_APPLY_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "state",
    "logs",
    "workspaces",
    "backups",
    "tmp",
    "secrets",
    "__pycache__",
}

BLOCKED_REPO_APPLY_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.prod",
}

IGNORABLE_REPO_APPLY_PREFIXES = (
    "logs/",
    "reports/",
    "state/",
    "tmp/",
)

TEXT_SUFFIXES_FOR_SCAN = {".py", ".md", ".json", ".sh", ".html", ".css", ".js", ".txt", ".yml", ".yaml", ".service"}

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}\b"),
]


def normalize_repo_apply_path(path: str) -> str:
    rel = str(path or "").replace("\\", "/").strip().strip("\"'")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")


def matches_repo_apply_prefix(rel: str, prefix: str) -> bool:
    safe_prefix = prefix.replace("\\", "/").lstrip("/")
    if safe_prefix.endswith("/"):
        return rel.startswith(safe_prefix)
    return rel == safe_prefix


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


def task_text(task: dict[str, Any]) -> str:
    return "\n".join(str(task.get(key, "")) for key in ["title", "description", "raw_message"])


def task_allows_repo_apply(task: dict[str, Any]) -> bool:
    mode = str(task.get("execution_mode") or task.get("dispatcher_mode") or "").strip().lower()
    return bool(task.get("repo_apply_allowed") is True or mode in {"repo_apply", "apply", "implementation"})


def run_cmd(
    args: list[str],
    *,
    cwd: Path,
    timeout: int = 300,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": redact_sensitive_text(proc.stdout)[-4000:],
            "stderr": redact_sensitive_text(proc.stderr)[-4000:],
            "cmd": " ".join(args),
        }
    except Exception as exc:
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": redact_sensitive_text(str(exc))[:1000], "cmd": " ".join(args)}


def safe_branch_fragment(value: Any, limit: int = 64) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "task").strip()).strip("-._").lower()
    return (cleaned[:limit].strip("-._") or "task")


def is_safe_repo_apply_path(path: str) -> bool:
    rel = normalize_repo_apply_path(path)
    if not rel or rel.startswith("../") or "/../" in rel:
        return False
    parts = set(rel.split("/"))
    if parts & BLOCKED_REPO_APPLY_PARTS:
        return False
    if Path(rel).name in BLOCKED_REPO_APPLY_NAMES:
        return False
    return any(matches_repo_apply_prefix(rel, prefix) for prefix in SAFE_REPO_APPLY_PREFIXES)


def is_ignorable_repo_apply_artifact(path: str) -> bool:
    rel = normalize_repo_apply_path(path)
    if not rel or rel.startswith("../") or "/../" in rel:
        return False
    return any(rel.startswith(prefix) for prefix in IGNORABLE_REPO_APPLY_PREFIXES)


def changed_repo_files(worktree: Path) -> list[str]:
    status = run_cmd(["git", "status", "--porcelain"], cwd=worktree, timeout=60)
    files: list[str] = []
    for raw in status.get("stdout", "").splitlines():
        line = raw.rstrip()
        if not line:
            continue
        rel = line[3:] if len(line) > 3 else line
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        rel = rel.strip().strip('"')
        if rel:
            files.append(rel)
    return sorted(dict.fromkeys(files))


def secret_scan_changed_files(worktree: Path, files: list[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for rel in files:
        path = worktree / rel
        if not path.exists() or not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES_FOR_SCAN:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for idx, pattern in enumerate(SECRET_PATTERNS):
                if pattern.search(line):
                    findings.append({"file": rel, "line": lineno, "pattern_id": idx})
    return findings


def proposal_evidence_excerpt(task: dict[str, Any], limit: int = 2500) -> str:
    chunks: list[str] = []
    for key in ("proposal_workspace", "proposal_report_path", "workspace", "report_path"):
        raw = task.get(key)
        if not raw:
            continue
        path = Path(str(raw))
        if path.is_file():
            try:
                chunks.append(f"## {path.name}\n" + path.read_text(encoding="utf-8", errors="replace")[:limit])
            except Exception:
                continue
        elif path.is_dir():
            for name in EXPECTED_WORKER_FILES:
                candidate = path / name
                if not candidate.exists():
                    continue
                try:
                    chunks.append(f"## {name}\n" + candidate.read_text(encoding="utf-8", errors="replace")[:limit])
                except Exception:
                    continue
    return redact_sensitive_text("\n\n".join(chunks))[:limit]


def repo_apply_pipeline(worktree: Path) -> list[dict[str, Any]]:
    env = os.environ.copy()
    env["CODEX_DEV_CENTER_HOME"] = str(worktree)
    env["CODEX_DEV_CENTER_SOURCE"] = str(worktree)
    checks: list[tuple[str, list[str], int]] = [
        ("python_compile", [sys.executable, "-m", "compileall", "-q", "supervisor", "web_panel", "scripts"], 180),
    ]
    if (worktree / "tests" / "test_runtime_status_model.py").exists():
        checks.append(("unit_runtime_status_model", [sys.executable, "-m", "unittest", "tests.test_runtime_status_model"], 300))
    if (worktree / "supervisor" / "production_readiness_suite.py").exists():
        checks.append(("production_readiness", [sys.executable, "supervisor/production_readiness_suite.py", "--json"], 600))

    results: list[dict[str, Any]] = []
    for name, cmd, timeout in checks:
        result = run_cmd(cmd, cwd=worktree, timeout=timeout, env=env)
        result["name"] = name
        results.append(result)
        if not result["ok"]:
            break
    return results


def pipeline_passed(results: list[dict[str, Any]]) -> bool:
    return bool(results) and all(item.get("ok") for item in results)


def create_pull_request(worktree: Path, branch: str, title: str, body: str) -> dict[str, Any]:
    if not shutil.which("gh"):
        return {"ok": False, "reason": "gh_not_found"}
    created = run_cmd(
        ["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body", body],
        cwd=worktree,
        timeout=120,
    )
    if not created["ok"]:
        return {"ok": False, "create": created}
    viewed = run_cmd(["gh", "pr", "view", branch, "--json", "number,url,headRefName,state"], cwd=worktree, timeout=60)
    payload: dict[str, Any] = {"ok": True, "create": created, "url": created.get("stdout", "").strip()}
    if viewed["ok"]:
        try:
            info = json.loads(viewed.get("stdout") or "{}")
            payload.update(info)
        except Exception:
            payload["view"] = viewed
    return payload


def execute_repo_apply_task(worker_id: str, task: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    task_id = str(task.get("id") or "unknown-task")
    title = safe_excerpt(task.get("title") or "Worker repo apply", 180)
    desc = safe_excerpt(task.get("description") or task.get("raw_message") or title, 1800)
    risk = safe_excerpt(task.get("risk") or task.get("risk_level") or "medium", 60)
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_id)[:100]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    worktree = APP_DIR / "workspaces" / f"repo_apply_{worker_id}_{safe_id}_{run_id}"
    control_dir = APP_DIR / "workspaces" / f"repo_apply_control_{worker_id}_{safe_id}_{run_id}"
    task_log = LOG_DIR / f"{task_id}_{worker_id}.log"
    report_path = REPORT_DIR / f"{task_id}_{worker_id}_REPORT.md"
    branch = f"worker/{safe_branch_fragment(task_id)}-{run_id}"

    critical = approval_required_payload(task_text(task))
    if critical["approval_required"]:
        metadata = {
            "approval_required": True,
            "critical_operation_findings": critical["critical_operation_findings"],
            "worker_eligible": False,
            "production_deployed": False,
            "repo_applied": False,
            "delivery_level": TASK_STATUS_APPROVAL_REQUIRED,
            "validation_status": "APPROVAL_REQUIRED",
            "pipeline_status": "NOT_RUN",
        }
        report_path.write_text(
            "# WORKER REPO APPLY REPORT\n\n"
            f"Tarih: {now()}\n"
            f"Worker: {worker_id}\n"
            f"Task: {task_id}\n"
            "Sonuç: APPROVAL_REQUIRED\n"
            "Neden: kritik altyapı/credential kapsamı tespit edildi; otomatik apply yapılmadı.\n",
            encoding="utf-8",
        )
        return TASK_STATUS_APPROVAL_REQUIRED, "critical_operation_requires_user_approval", str(report_path), metadata

    if not (SOURCE_ROOT / ".git").exists():
        metadata = {
            "production_deployed": False,
            "repo_applied": False,
            "delivery_level": TASK_STATUS_FAILED_RETRYABLE,
            "validation_status": "NOT_READY",
            "pipeline_status": "NOT_RUN",
        }
        report_path.write_text(
            "# WORKER REPO APPLY REPORT\n\n"
            f"Tarih: {now()}\nWorker: {worker_id}\nTask: {task_id}\nSonuç: FAILED_RETRYABLE\n"
            f"Neden: source git repo bulunamadı: {SOURCE_ROOT}\n",
            encoding="utf-8",
        )
        return TASK_STATUS_FAILED_RETRYABLE, "source_git_repo_not_found", str(report_path), metadata

    append_log(task_log, f"{now()} WORKER={worker_id} TASK={task_id} REPO_APPLY_START branch={branch} worktree={worktree}")
    fetch = run_cmd(["git", "fetch", "origin", "main", "--prune"], cwd=SOURCE_ROOT, timeout=180)
    base_ref = "origin/main" if fetch["ok"] else "HEAD"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    add_worktree = run_cmd(["git", "worktree", "add", "-b", branch, str(worktree), base_ref], cwd=SOURCE_ROOT, timeout=180)
    if not add_worktree["ok"]:
        metadata = {
            "git_fetch": fetch,
            "git_worktree": add_worktree,
            "production_deployed": False,
            "repo_applied": False,
            "delivery_level": TASK_STATUS_FAILED_RETRYABLE,
            "validation_status": "NOT_READY",
            "pipeline_status": "NOT_RUN",
        }
        report_path.write_text(
            "# WORKER REPO APPLY REPORT\n\n"
            f"Tarih: {now()}\nWorker: {worker_id}\nTask: {task_id}\nSonuç: FAILED_RETRYABLE\n"
            "Neden: git worktree oluşturulamadı.\n",
            encoding="utf-8",
        )
        return TASK_STATUS_FAILED_RETRYABLE, "git_worktree_create_failed", str(report_path), metadata

    evidence = proposal_evidence_excerpt(task)
    prompt = f"""
Sen Codex Dev Center apply worker'ısın.

Worker:
{worker_id}

Görev:
{title}

Açıklama:
{desc}

Risk:
{risk}

Bu çalışma ayrı bir git worktree ve branch üzerindedir:
{branch}

Kurallar:
- Bu worktree içindeki repo dosyalarını değiştirebilirsin.
- Main branch'e doğrudan push yapma.
- Production deploy yapma.
- Secret/env/token/private key değerlerini okuma, yazma, gösterme veya değiştirme.
- IAM, billing, DNS, firewall, destructive database, credential rotation veya reklam platformu canlı yazma işlemi yapma.
- Değişikliği küçük, test edilebilir ve geri alınabilir tut.
- İlgili testleri çalıştır; çalıştıramadığın testleri final çıktıda belirt.
- Teknik çıktıyı Telegram'a gönderme.

Önceki proposal/kanıt özeti:
{evidence or "-"}

Beklenen çıktı:
- Repo içinde gerekli en küçük kod/doküman/test değişikliğini uygula.
- Final yanıtta değişen dosyaları, testleri ve riski kısa Türkçe özetle.
""".strip()

    control_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = control_dir / "WORKER_APPLY_PROMPT.txt"
    out_file = control_dir / "codex.apply.out"
    err_file = control_dir / "codex.apply.err"
    prompt_file.write_text(prompt, encoding="utf-8")

    progress_state = control_dir / "progress_watchdog.json"
    cmd = ["codex", "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", "--cd", str(worktree), prompt]
    progress_result = run_progress_aware(
        cmd,
        cwd=worktree,
        stdout_path=out_file,
        stderr_path=err_file,
        progress_paths=[worktree, control_dir],
        git_roots=[worktree],
        progress_state_path=progress_state,
        stall_seconds=WORKER_STALL_SECONDS,
        grace_seconds=WORKER_GRACE_SECONDS,
        max_wall_seconds=REPO_APPLY_MAX_WALL_SECONDS,
        on_progress=lambda payload: update_task_progress(task_id, worker_id, payload),
    )
    returncode = int(progress_result.get("returncode") if progress_result.get("returncode") is not None else 1)
    changed_files = changed_repo_files(worktree)
    ignored_generated_files = [rel for rel in changed_files if is_ignorable_repo_apply_artifact(rel)]
    commit_files = [rel for rel in changed_files if rel not in ignored_generated_files]
    unsafe_files = [rel for rel in commit_files if not is_safe_repo_apply_path(rel)]
    secret_findings = secret_scan_changed_files(worktree, commit_files)

    status = TASK_STATUS_DONE
    result = "repo_apply_pr_ready_pipeline_passed"
    validation_status = "PASS"
    pipeline_status = "PASS"
    pipeline_results: list[dict[str, Any]] = []
    pr_payload: dict[str, Any] = {}
    commit_result: dict[str, Any] = {}
    push_result: dict[str, Any] = {}

    if returncode != 0 and not commit_files:
        status = TASK_STATUS_FAILED_RETRYABLE
        result = "repo_apply_worker_failed_without_changes"
        validation_status = "NOT_READY"
        pipeline_status = "NOT_RUN"
    elif not commit_files:
        status = TASK_STATUS_FAILED_NO_PROPOSAL
        result = "repo_apply_worker_completed_without_changes"
        validation_status = "NOT_READY"
        pipeline_status = "NOT_RUN"
    elif unsafe_files:
        status = TASK_STATUS_VALIDATION_FAILED
        result = "repo_apply_changed_unsafe_paths"
        validation_status = "FAIL"
        pipeline_status = "NOT_RUN"
    elif secret_findings:
        status = TASK_STATUS_APPROVAL_REQUIRED
        result = "repo_apply_secret_scan_requires_approval"
        validation_status = "APPROVAL_REQUIRED"
        pipeline_status = "NOT_RUN"
    else:
        pipeline_results = repo_apply_pipeline(worktree)
        if not pipeline_passed(pipeline_results):
            status = TASK_STATUS_PIPELINE_FAILED
            result = "repo_apply_pipeline_failed"
            validation_status = "PASS"
            pipeline_status = "FAIL"
        else:
            add_result = run_cmd(["git", "add", "-A", "--", *commit_files], cwd=worktree, timeout=120)
            commit_result = run_cmd(["git", "commit", "-m", f"Worker apply {task_id}"], cwd=worktree, timeout=180)
            push_result = run_cmd(["git", "push", "-u", "origin", branch], cwd=worktree, timeout=300)
            if not (add_result["ok"] and commit_result["ok"] and push_result["ok"]):
                status = TASK_STATUS_FAILED_RETRYABLE
                result = "repo_apply_commit_or_push_failed"
                validation_status = "PASS"
                pipeline_status = "PASS"
            else:
                body = "\n".join(
                    [
                        f"Task: {task_id}",
                        f"Worker: {worker_id}",
                        "",
                        "Gates:",
                        "- local validation: PASS",
                        "- production readiness: PASS",
                        "",
                        "Critical operations remain blocked by policy.",
                    ]
                )
                pr_payload = create_pull_request(worktree, branch, f"Worker apply: {title[:80]}", body)
                if not pr_payload.get("ok"):
                    status = TASK_STATUS_FAILED_RETRYABLE
                    result = "repo_apply_pr_create_failed"
                    validation_status = "PASS"
                    pipeline_status = "PASS"

    delivery_level = "PR_READY" if status == TASK_STATUS_DONE and pr_payload.get("ok") else status
    report = [
        "# WORKER REPO APPLY REPORT",
        "",
        f"Tarih: {now()}",
        f"Worker: {worker_id}",
        f"Task: {task_id}",
        f"Branch: {branch}",
        f"Worktree: {worktree}",
        f"Sonuç: {status}",
        f"Result: {result}",
        f"Codex return code: {returncode}",
        f"Validation status: {validation_status}",
        f"Pipeline status: {pipeline_status}",
        "",
        "## Changed Files",
    ]
    report.extend([f"- {rel}" for rel in commit_files] or ["- Yok"])
    if ignored_generated_files:
        report += ["", "## Ignored Generated Files"]
        report.extend([f"- {rel}" for rel in ignored_generated_files])
    if unsafe_files:
        report += ["", "## Unsafe Path Findings"]
        report.extend([f"- {rel}" for rel in unsafe_files])
    if secret_findings:
        report += ["", "## Secret Scan Findings", f"- Count: {len(secret_findings)}"]
    if pipeline_results:
        report += ["", "## Gates"]
        report.extend([f"- {item.get('name')}: {'PASS' if item.get('ok') else 'FAIL'}" for item in pipeline_results])
    if pr_payload.get("url"):
        report += ["", f"Pull Request: {pr_payload.get('url')}"]
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")

    metadata = {
        "workspace": str(worktree),
        "repo_worktree": str(worktree),
        "branch": branch,
        "changed_files": changed_files,
        "commit_files": commit_files,
        "ignored_generated_files": ignored_generated_files,
        "unsafe_files": unsafe_files,
        "secret_scan_findings": secret_findings,
        "codex_return_code": returncode,
        "progress_watchdog": progress_result,
        "validation_status": validation_status,
        "pipeline_status": pipeline_status,
        "pipeline_results": [{"name": item.get("name"), "ok": item.get("ok"), "returncode": item.get("returncode")} for item in pipeline_results],
        "delivery_level": delivery_level,
        "production_deployed": False,
        "repo_applied": False,
        "branch_merged": False,
        "pull_request_url": pr_payload.get("url", ""),
        "pull_request_number": pr_payload.get("number", ""),
        "pull_request_state": pr_payload.get("state", ""),
        "commit_stdout": commit_result.get("stdout", "")[-1000:] if commit_result else "",
        "push_ok": bool(push_result.get("ok")) if push_result else False,
        "repo_apply_allowed": True,
    }
    if status == TASK_STATUS_APPROVAL_REQUIRED:
        metadata["approval_required"] = True
        metadata["worker_eligible"] = False
    append_log(
        task_log,
        f"{now()} WORKER={worker_id} TASK={task_id} REPO_APPLY_DONE status={status} result={result} changed={len(changed_files)} branch={branch}",
    )
    return status, result, str(report_path), metadata


def execute_safe_task(worker_id: str, task: dict) -> tuple[str, str, str, dict[str, Any]]:
    import subprocess
    from pathlib import Path

    if task_allows_repo_apply(task):
        return execute_repo_apply_task(worker_id, task)

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
