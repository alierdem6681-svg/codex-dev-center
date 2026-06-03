from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()
STATE = ROOT / "state"
REPORTS = ROOT / "reports"
STATIC_DIR = ROOT / "web_panel" / "static"
HOST = os.environ.get("CODEX_PANEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("CODEX_PANEL_PORT", "8080"))
SCOPE = os.environ.get("CODEX_PANEL_SCOPE", "production")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"error": str(exc), "path": str(path)}
    return default


def read_text(path: Path, default: str = "") -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return default


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


def pipeline_tracking_summary(github_actions, pipeline_status):
    github_actions = github_actions if isinstance(github_actions, dict) else {}
    pipeline_status = pipeline_status if isinstance(pipeline_status, dict) else {}
    task_marker = pipeline_status.get("task_to_deploy_test") or pipeline_status.get("status")
    deploy_status = github_actions.get("last_deploy_status") or pipeline_status.get("deploy_status")
    smoke_status = github_actions.get("last_smoke_status") or pipeline_status.get("last_smoke_status")
    workflow_run_id = pipeline_status.get("workflow_run_id") or github_actions.get("last_deploy_run_id") or github_actions.get("last_smoke_run_id")
    commit = pipeline_status.get("commit") or github_actions.get("last_deploy_commit") or github_actions.get("last_smoke_commit")
    updated_at = (
        pipeline_status.get("updated_at")
        or github_actions.get("updated_at")
        or github_actions.get("last_deploy_at")
        or github_actions.get("last_smoke_at")
    )
    missing = [
        name
        for name, value in (
            ("last_deploy_status", deploy_status),
            ("last_smoke_status", smoke_status),
            ("task_to_deploy_test", task_marker),
        )
        if not value
    ]
    values = [str(value).upper() for value in (deploy_status, smoke_status, task_marker) if value]
    errors = [payload.get("error") for payload in (github_actions, pipeline_status) if payload.get("error")]
    if errors:
        status = "ERROR"
    elif not values:
        status = "WAITING_FOR_RUNTIME_STATE"
    elif any(value in {"FAIL", "FAILED", "ERROR"} for value in values):
        status = "FAIL"
    elif not missing and all(value == "PASS" for value in values):
        status = "PASS"
    else:
        status = "TRACKING"
    return {
        "status": status,
        "runtime_state_present": bool(values),
        "last_deploy_status": deploy_status,
        "last_smoke_status": smoke_status,
        "task_to_deploy_test": task_marker,
        "workflow_run_id": workflow_run_id,
        "commit": commit,
        "commit_short": str(commit)[:8] if commit else None,
        "updated_at": updated_at,
        "source": pipeline_status.get("source") or github_actions.get("source") or ("runtime_state_files" if values else None),
        "missing_markers": missing,
        "read_only": True,
        "visibility_grants_production_deploy": False,
        "errors": errors,
    }


def status_payload():
    system_state = read_json(STATE / "system_state.json", {})
    github_actions = read_json(STATE / "github_actions_status.json", {})
    pipeline_status = read_json(STATE / "pipeline_status.json", {})
    return {
        "ok": True,
        "time": now(),
        "system_state": system_state,
        "controlled_execution": controlled_execution_summary(system_state),
        "workers": read_json(STATE / "workers.json", {"workers": []}),
        "tasks": read_json(STATE / "task_queue.json", {"tasks": []}),
        "modules": read_json(STATE / "module_registry.json", read_json(ROOT / "state_templates/module_registry.json", {"modules": []})),
        "actions": read_json(STATE / "action_catalog.json", read_json(ROOT / "state_templates/action_catalog.json", {"actions": []})),
        "dashboard_settings": read_json(STATE / "dashboard_settings.json", read_json(ROOT / "state_templates/dashboard_settings.json", {})),
        "module_settings": read_json(STATE / "module_settings.json", read_json(ROOT / "state_templates/module_settings.json", {})),
        "production_policy": read_json(ROOT / "state_templates/production_policy.json", {}),
        "production_readiness": read_json(STATE / "production_readiness_status.json", {}),
        "production_deploy": read_json(STATE / "production_deploy_status.json", {}),
        "production_environment": read_json(STATE / "production_environment_status.json", {}),
        "staging_deploy": read_json(STATE / "staging_deploy_status.json", {}),
        "production_runtime": read_json(STATE / "production_runtime_status.json", {}),
        "github_actions": github_actions,
        "pipeline_status": pipeline_status,
        "pipeline_tracking": pipeline_tracking_summary(github_actions, pipeline_status),
        "rollback": read_json(STATE / "rollback_status.json", {}),
        "rollback_point": read_json(STATE / "rollback_point.json", {}),
        "last_health_check": read_json(STATE / "last_health_check_status.json", {}),
        "last_smoke_test": read_json(STATE / "last_smoke_test_status.json", {}),
        "github_safe_flow": read_json(STATE / "github_safe_flow_status.json", {}),
        "reports": sorted([p.name for p in REPORTS.glob("*.md")]) if REPORTS.exists() else [],
        "report_text": {
            "readiness": read_text(REPORTS / "production_readiness_last_report.md"),
            "deploy": read_text(REPORTS / "production_deploy_last_report.md"),
            "rollback": read_text(REPORTS / "rollback_simulation_last_report.md"),
            "github": read_text(REPORTS / "github_safe_flow_last_report.md"),
        },
    }


class PanelHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_raw(self, payload: bytes, content_type: str = "application/json; charset=utf-8", code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, data, code: int = 200):
        self.send_raw(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), code=code)

    def body(self):
        size = int(self.headers.get("Content-Length", "0") or "0")
        if size <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(size).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json({
                "ok": True,
                "service": "codex-panel",
                "production_pipeline": True,
                "production_environment_manager": True,
                "scope": SCOPE,
                "root": str(ROOT),
                "port": PORT,
                "version": "production-environment-v1"
            })
            return
        if parsed.path == "/api/status":
            self.send_json(status_payload())
            return
        if parsed.path in ("/", "/index.html"):
            self.send_raw((STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        self.send_json({"ok": False, "error": "not_found"}, 404)

    def do_POST(self) -> None:
        data = self.body()
        action = data.get("action")
        if action == "production_readiness_suite":
            self.send_json(run_cmd([sys.executable, "supervisor/production_readiness_suite.py", "--json"], 240))
            return
        if action == "production_deploy_start":
            self.send_json(run_cmd([sys.executable, "supervisor/production_deploy_controller.py", "start", "--auto"], 300))
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
        if action == "rollback_simulation":
            self.send_json(run_cmd([sys.executable, "supervisor/production_environment_manager.py", "rollback", "--dry-run"], 120))
            return
        self.send_json({"ok": False, "error": "unknown_action"}, 400)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), PanelHandler)
    print(f"Codex Dev Center panel: http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
