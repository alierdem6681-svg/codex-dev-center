#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

WEB_PANEL_DIR = Path(__file__).resolve().parent
if str(WEB_PANEL_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_PANEL_DIR))

import auth as panel_auth
from pipeline_flow import build_pipeline_flow


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()
STATE = ROOT / "state"
REPORTS = ROOT / "reports"
LOGS = ROOT / "logs"
STATIC_DIR = ROOT / "web_panel" / "static"
HOST = os.environ.get("CODEX_PANEL_HOST", "0.0.0.0")
PORT = int(os.environ.get("CODEX_PANEL_PORT", "8080"))
SCOPE = os.environ.get("CODEX_PANEL_SCOPE", "production")

SUPERVISOR_DIR = ROOT / "supervisor"
if str(SUPERVISOR_DIR) not in sys.path:
    sys.path.insert(0, str(SUPERVISOR_DIR))

try:
    from task_status_constants import normalize_status, read_json as read_state_json, worker_block_reason
except Exception:
    def normalize_status(value, default="QUEUED"):
        return str(value or default).strip().upper()

    def read_state_json(path, default):
        try:
            if Path(path).exists():
                return json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except Exception as exc:
            return {"error": str(exc), "path": str(path)}
        return default

    def worker_block_reason(task):
        if str(task.get("source", "")).lower() == "telegram":
            return "telegram_reserved_for_cto"
        if str(task.get("risk") or task.get("risk_level") or "").lower() in {"high", "critical"}:
            return "approval_required"
        if task.get("worker_eligible") is False:
            return "worker_eligible_false"
        return ""


ACTIVE_STATUSES = {"PENDING", "QUEUED", "ASSIGNED", "RUNNING"}
RECOVERABLE_STATUSES = {
    "FAILED",
    "FAILED_NO_PROPOSAL",
    "FAILED_RETRYABLE",
    "FAILED_TIMEOUT",
    "PIPELINE_FAILED",
    "PROPOSAL_DONE",
    "PROPOSAL_READY",
    "READY_FOR_VALIDATION",
    "STALLED",
    "VALIDATION_FAILED",
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default):
    return read_state_json(Path(path), default)


def read_text(path: Path, default: str = "") -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return default


def is_loopback(handler: BaseHTTPRequestHandler) -> bool:
    host = handler.client_address[0]
    return host in {"127.0.0.1", "::1", "localhost"}


def setup_allowed(handler: BaseHTTPRequestHandler) -> bool:
    return is_loopback(handler) or os.environ.get("CODEX_PANEL_ALLOW_REMOTE_SETUP", "") == "1"


def authorized(handler: BaseHTTPRequestHandler) -> bool:
    return bool(panel_auth.user_from_cookie(handler.headers.get("Cookie", "")))


def run_cmd(cmd: list[str], timeout: int = 180):
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-5000:],
            "stderr": proc.stderr[-5000:],
            "cmd": " ".join(cmd),
        }
    except Exception as exc:
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": str(exc), "cmd": " ".join(cmd)}


def service_status(name: str):
    return run_cmd(["systemctl", "is-active", name], 15).get("stdout", "").strip() or "unknown"


def service_enabled(name: str):
    return run_cmd(["systemctl", "is-enabled", name], 15).get("stdout", "").strip() or "unknown"


def services():
    names = ["codex-panel", "codex-direct-cto", "codex-lifecycle", "codex-cto", "codex-worker-1", "codex-worker-2", "codex-worker-3", "codex-worker-4", "codex-watchdog"]
    return [{"name": n, "active": service_status(n), "enabled": service_enabled(n)} for n in names]


def compact_task(task):
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "status": normalize_status(task.get("status")),
        "source": task.get("source"),
        "risk": task.get("risk") or task.get("risk_level"),
        "assigned_worker": task.get("assigned_worker"),
        "reason": worker_block_reason(task),
        "parent_task": task.get("parent_task"),
    }


def queue_diagnostics(tasks_payload, workers_payload, system_state, production_deploy, github_actions):
    tasks = tasks_payload.get("tasks", []) if isinstance(tasks_payload, dict) else []
    workers = workers_payload.get("workers", []) if isinstance(workers_payload, dict) else []
    counts = {}
    for task in tasks:
        status = normalize_status(task.get("status"))
        counts[status] = counts.get(status, 0) + 1

    active = [task for task in tasks if normalize_status(task.get("status")) in ACTIVE_STATUSES]
    blocked_active = [task for task in active if worker_block_reason(task)]
    worker_eligible = [task for task in active if not worker_block_reason(task)]
    sleeping = [worker for worker in workers if str(worker.get("status", "")).upper() == "SLEEPING"]
    running = [worker for worker in workers if str(worker.get("status", "")).upper() == "RUNNING"]
    recoverable = [task for task in tasks if normalize_status(task.get("status")) in RECOVERABLE_STATUSES and not worker_block_reason(task)]

    if worker_eligible:
        sleep_reason = "eligible_task_exists"
    elif active and blocked_active:
        sleep_reason = "active_tasks_blocked_for_workers"
    elif recoverable:
        sleep_reason = "waiting_for_backlog_dispatcher_single_mode"
    else:
        sleep_reason = "no_worker_eligible_pending_tasks"

    deploy_status = str(production_deploy.get("status", "") if isinstance(production_deploy, dict) else "").upper()
    last_deploy = str(github_actions.get("last_deploy_status", "") if isinstance(github_actions, dict) else "").upper()
    if last_deploy == "PASS" and deploy_status in {"BLOCKED", "FAIL", "FAILED"}:
        deploy_reconciliation = "dashboard_deploy_state_stale_or_conflicting"
    else:
        deploy_reconciliation = "consistent_or_unknown"

    return {
        "status_counts": counts,
        "active_task_count": len(active),
        "worker_eligible_active_count": len(worker_eligible),
        "blocked_active_count": len(blocked_active),
        "recoverable_task_count": len(recoverable),
        "workers_sleeping_count": len(sleeping),
        "workers_running_count": len(running),
        "worker_sleep_reason": sleep_reason,
        "next_worker_eligible_task": compact_task(worker_eligible[0]) if worker_eligible else None,
        "blocked_active_examples": [compact_task(task) for task in blocked_active[:8]],
        "recoverable_examples": [compact_task(task) for task in recoverable[:8]],
        "dispatcher": {
            "active": bool(system_state.get("backlog_dispatcher_active")),
            "mode": system_state.get("backlog_dispatcher_mode", "single"),
            "last_tick": system_state.get("backlog_dispatcher_last_tick"),
            "last_result": system_state.get("backlog_dispatcher_last_result"),
            "last_parent": system_state.get("backlog_dispatcher_last_parent"),
            "last_child": system_state.get("backlog_dispatcher_last_child"),
            "last_mode": system_state.get("backlog_dispatcher_last_mode"),
            "worker_active": system_state.get("backlog_dispatcher_worker_active"),
            "recoverable_count": system_state.get("backlog_dispatcher_recoverable_count"),
        },
        "deploy_reconciliation": deploy_reconciliation,
    }


def deploy_commands():
    policy = read_json(ROOT / "state_templates/deploy_policy.json", {})
    commands = policy.get("commands", {}) if isinstance(policy, dict) else {}
    env_defaults = policy.get("environment_defaults", {}) if isinstance(policy, dict) else {}
    keys = [
        "CODEX_STAGING_DEPLOY_COMMAND",
        "CODEX_PRODUCTION_DEPLOY_COMMAND",
        "CODEX_ROLLBACK_COMMAND",
        "CODEX_HEALTH_CHECK_COMMAND",
        "CODEX_SMOKE_TEST_COMMAND",
    ]
    result = {}
    for key in keys:
        value = os.environ.get(key, "").strip() or commands.get(key, "") or env_defaults.get(key, "")
        result[key] = {
            "configured": bool(value),
            "source": "environment" if os.environ.get(key, "").strip() else "policy_default",
            "command": value,
        }
    result["CODEX_PRODUCTION_DEPLOY_EXECUTE"] = {
        "configured": (os.environ.get("CODEX_PRODUCTION_DEPLOY_EXECUTE", "").strip() or str(env_defaults.get("CODEX_PRODUCTION_DEPLOY_EXECUTE", "1"))) == "1",
        "source": "environment" if os.environ.get("CODEX_PRODUCTION_DEPLOY_EXECUTE", "").strip() else "policy_default",
    }
    return result


def direct_cto_jobs_summary(limit: int = 12):
    jobs_dir = STATE / "direct_cto_jobs"
    if not jobs_dir.exists():
        return {"count": 0, "active_count": 0, "jobs": []}
    active_statuses = {"QUEUED", "RUNNING"}
    paths = sorted(
        [path for path in jobs_dir.glob("JOB-*.json") if not path.name.endswith(".progress.json")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    payloads = []
    active_paths = []
    for path in paths:
        payload = read_json(path, {})
        if not isinstance(payload, dict):
            continue
        payloads.append((path, payload))
        if str(payload.get("status", "")).upper() in active_statuses:
            active_paths.append(path)

    selected_paths = paths[:limit]
    selected = {str(path) for path in selected_paths}
    for path in active_paths:
        if str(path) not in selected:
            selected_paths.append(path)
            selected.add(str(path))

    payload_by_path = {str(path): payload for path, payload in payloads}
    jobs = []
    for path in selected_paths:
        payload = payload_by_path.get(str(path), {})
        progress = payload.get("progress_watchdog") if isinstance(payload.get("progress_watchdog"), dict) else {}
        jobs.append(
            {
                "id": payload.get("id") or path.stem,
                "status": payload.get("status"),
                "generic_task_name": payload.get("generic_task_name"),
                "created_at": payload.get("created_at"),
                "started_at": payload.get("started_at"),
                "finished_at": payload.get("finished_at"),
                "updated_at": payload.get("updated_at"),
                "router_task_id": payload.get("router_task_id"),
                "action_command": bool(payload.get("action_command")),
                "progress": {
                    "status": progress.get("status"),
                    "elapsed_seconds": progress.get("elapsed_seconds"),
                    "last_meaningful_progress_seconds_ago": progress.get("last_meaningful_progress_seconds_ago"),
                    "last_output_activity_seconds_ago": progress.get("last_output_activity_seconds_ago"),
                    "meaningful_event_count": progress.get("meaningful_event_count"),
                },
            }
        )
    hidden_active_count = max(0, len(active_paths) - len([job for job in jobs if str(job.get("status", "")).upper() in active_statuses]))
    return {"count": len(payloads), "active_count": len(active_paths), "hidden_active_count": hidden_active_count, "jobs": jobs}


def controlled_execution_summary(system_state):
    reports = []
    if REPORTS.exists():
        reports = sorted(REPORTS.glob("CONTROLLED_EXECUTION_*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    proposal_ready = bool(system_state.get("controlled_execution_proposal_ready"))
    return {
        "status": "PROPOSAL_READY" if proposal_ready else "WAITING",
        "proposal_ready": proposal_ready,
        "last_task": system_state.get("last_controlled_execution_task"),
        "last_workspace": system_state.get("last_controlled_execution_workspace"),
        "latest_report": reports[0].name if reports else None,
        "proposal_mode_repo_mutation_allowed": False,
        "proposal_mode_production_deploy_allowed": False,
        "critical_operations_allowed": False,
    }


def status_payload():
    system_state = read_json(STATE / "system_state.json", {})
    workers_payload = read_json(STATE / "workers.json", {"workers": []})
    tasks_payload = read_json(STATE / "task_queue.json", {"tasks": []})
    production_deploy = read_json(STATE / "production_deploy_status.json", {})
    github_actions = read_json(STATE / "github_actions_status.json", {})
    pipeline_status = read_json(STATE / "pipeline_status.json", {})
    return {
        "ok": True,
        "time": now(),
        "system_state": system_state,
        "controlled_execution": controlled_execution_summary(system_state),
        "workers": workers_payload,
        "tasks": tasks_payload,
        "operations": queue_diagnostics(tasks_payload, workers_payload, system_state, production_deploy, github_actions),
        "services": services(),
        "modules": read_json(STATE / "module_registry.json", read_json(ROOT / "state_templates/module_registry.json", {"modules": []})),
        "actions": read_json(STATE / "action_catalog.json", read_json(ROOT / "state_templates/action_catalog.json", {"actions": []})),
        "dashboard_settings": read_json(STATE / "dashboard_settings.json", read_json(ROOT / "state_templates/dashboard_settings.json", {})),
        "module_settings": read_json(STATE / "module_settings.json", read_json(ROOT / "state_templates/module_settings.json", {})),
        "production_policy": read_json(ROOT / "state_templates/production_policy.json", {}),
        "cto_delivery": read_json(STATE / "cto_delivery_state.json", read_json(ROOT / "state_templates/cto_delivery_policy.json", {})),
        "auth": panel_auth.public_auth_state(),
        "production_readiness": read_json(STATE / "production_readiness_status.json", {}),
        "production_deploy": production_deploy,
        "production_environment": read_json(STATE / "production_environment_status.json", {}),
        "staging_deploy": read_json(STATE / "staging_deploy_status.json", {}),
        "production_runtime": read_json(STATE / "production_runtime_status.json", {}),
        "github_actions": github_actions,
        "pipeline_status": pipeline_status,
        "direct_cto_jobs": direct_cto_jobs_summary(),
        "rollback": read_json(STATE / "rollback_status.json", {}),
        "rollback_point": read_json(STATE / "rollback_point.json", {}),
        "last_health_check": read_json(STATE / "last_health_check_status.json", {}),
        "last_smoke_test": read_json(STATE / "last_smoke_test_status.json", {}),
        "deploy_commands": deploy_commands(),
        "github_safe_flow": read_json(STATE / "github_safe_flow_status.json", {}),
        "cto_router": read_json(STATE / "cto_router_state.json", {}),
        "cto_doctor": read_json(STATE / "cto_doctor_status.json", {}),
        "reports": sorted([p.name for p in REPORTS.glob("*.md")]) if REPORTS.exists() else [],
        "report_text": {
            "readiness": read_text(REPORTS / "production_readiness_last_report.md"),
            "deploy": read_text(REPORTS / "production_deploy_last_report.md"),
            "rollback": read_text(REPORTS / "rollback_simulation_last_report.md"),
            "github": read_text(REPORTS / "github_safe_flow_last_report.md"),
        },
    }


def pipeline_flow_payload():
    return build_pipeline_flow(ROOT)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        LOGS.mkdir(parents=True, exist_ok=True)
        with (LOGS / "panel_access.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{now()} {fmt % args}\n")

    def send_raw(self, payload: bytes, content_type: str = "application/json; charset=utf-8", code: int = 200, headers: dict[str, str] | None = None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, data, code: int = 200):
        self.send_raw(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), code=code)

    def redirect_login(self):
        self.send_raw(b"", "text/plain; charset=utf-8", 302, {"Location": "/login"})

    def send_login(self):
        self.send_raw((STATIC_DIR / "login.html").read_bytes(), "text/html; charset=utf-8")

    def send_with_session(self, data, username: str, code: int = 200):
        self.send_raw(
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json; charset=utf-8",
            code,
            {"Set-Cookie": panel_auth.session_cookie_header(username)},
        )

    def send_logout(self):
        self.send_raw(
            json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            200,
            {"Set-Cookie": panel_auth.clear_cookie_header()},
        )

    def body(self):
        size = int(self.headers.get("Content-Length", "0") or "0")
        if size <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(size).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            system_state = read_json(STATE / "system_state.json", {})
            self.send_json({
                "ok": True,
                "service": "codex-panel",
                "production_pipeline": True,
                "production_environment_manager": True,
                "scope": SCOPE,
                "root": str(ROOT),
                "port": PORT,
                "version": "production-environment-v1",
                "system_state": system_state.get("system_state") or system_state.get("state") or system_state.get("phase"),
                "active_queue_remaining": system_state.get("active_queue_remaining"),
                "production_running_commit": system_state.get("production_running_commit"),
                "github_origin_main_commit": system_state.get("github_origin_main_commit"),
                "production_github_sync": system_state.get("production_github_sync"),
            })
            return
        if parsed.path in ("/login", "/login.html"):
            self.send_login()
            return
        if parsed.path == "/api/auth/state":
            self.send_json(panel_auth.public_auth_state())
            return
        if not authorized(self):
            if parsed.path in ("/", "/index.html"):
                self.redirect_login()
            else:
                self.send_json({"ok": False, "error": "unauthorized", "login": "/login"}, 401)
            return
        if parsed.path == "/api/status":
            self.send_json(status_payload())
            return
        if parsed.path == "/api/pipeline-flow":
            self.send_json(pipeline_flow_payload())
            return
        if parsed.path in ("/", "/index.html"):
            self.send_raw((STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        self.send_json({"ok": False, "error": "not_found"}, 404)

    def do_POST(self):
        data = self.body()
        parsed = urlparse(self.path)
        if parsed.path == "/api/auth/setup":
            if panel_auth.auth_configured():
                self.send_json({"ok": False, "error": "auth_already_configured", "message": "Kullanıcı zaten oluşturuldu."}, 409)
                return
            if not setup_allowed(self):
                self.send_json({"ok": False, "error": "remote_setup_disabled", "message": "İlk kullanıcı yalnızca yerel erişimden oluşturulabilir."}, 403)
                return
            try:
                panel_auth.setup_user(str(data.get("username", "")), str(data.get("password", "")))
                self.send_with_session({"ok": True, "auth": panel_auth.public_auth_state()}, str(data.get("username", "")).strip())
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc), "message": "Kullanıcı adı veya şifre geçersiz."}, 400)
            return
        if parsed.path == "/api/auth/login":
            username = str(data.get("username", "")).strip()
            password = str(data.get("password", ""))
            if panel_auth.verify_credentials(username, password):
                self.send_with_session({"ok": True, "auth": panel_auth.public_auth_state()}, username)
            else:
                self.send_json({"ok": False, "error": "invalid_credentials", "message": "Kullanıcı adı veya şifre hatalı."}, 401)
            return
        if parsed.path == "/api/auth/logout":
            self.send_logout()
            return
        if not authorized(self):
            self.send_json({"ok": False, "error": "unauthorized", "login": "/login"}, 401)
            return
        action = data.get("action")
        if action == "production_readiness_suite":
            self.send_json(run_cmd([sys.executable, "supervisor/production_readiness_suite.py", "--json"], 240))
            return
        if action == "production_deploy_start":
            self.send_json(run_cmd([sys.executable, "supervisor/cto_autonomous_delivery.py", "deploy-latest", "--execute", "--wait"], 1200))
            return
        if action == "cto_delivery_status":
            self.send_json(run_cmd([sys.executable, "supervisor/cto_autonomous_delivery.py", "status"], 120))
            return
        if action == "staging_deploy":
            self.send_json(run_cmd([sys.executable, "supervisor/production_environment_manager.py", "staging-deploy"], 420))
            return
        if action == "health_check":
            self.send_json(run_cmd([sys.executable, "supervisor/production_environment_manager.py", "health-check", "--scope", "production"], 120))
            return
        if action == "smoke_test":
            self.send_json(run_cmd([sys.executable, "supervisor/production_environment_manager.py", "smoke-test", "--scope", "production"], 120))
            return
        if action == "github_safe_flow_dry_run":
            self.send_json(run_cmd([sys.executable, "supervisor/github_safe_flow.py", "dry-run"], 180))
            return
        if action == "cto_doctor_check":
            self.send_json(run_cmd([sys.executable, "supervisor/cto_doctor.py", "--json"], 120))
            return
        if action == "cto_doctor_fix":
            self.send_json(run_cmd([sys.executable, "supervisor/cto_doctor.py", "--fix", "--json"], 120))
            return
        if action == "rollback_simulation":
            self.send_json(run_cmd([sys.executable, "supervisor/production_environment_manager.py", "rollback", "--dry-run"], 120))
            return
        self.send_json({"ok": False, "error": "unknown_action"}, 400)


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Codex dashboard listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
