from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

WEB_PANEL_DIR = Path(__file__).resolve().parent
if str(WEB_PANEL_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_PANEL_DIR))

from pipeline_flow import build_pipeline_flow
from quality_gate_view import build_quality_gate_view, normalize_readiness_report_text
from telegram_asset_inbox import build_telegram_asset_detail, build_telegram_asset_list


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


def first_text(*values) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def production_commit_summary(system_state: dict) -> dict:
    production_deploy = read_json(STATE / "production_deploy_status.json", {})
    production_runtime = read_json(STATE / "production_runtime_status.json", {})
    github_actions = read_json(STATE / "github_actions_status.json", {})
    pipeline_status = read_json(STATE / "pipeline_status.json", {})
    running = first_text(
        production_runtime.get("commit"),
        production_deploy.get("commit"),
        github_actions.get("last_deploy_commit"),
        pipeline_status.get("commit"),
        system_state.get("production_running_commit"),
    )
    origin = first_text(
        github_actions.get("last_deploy_commit"),
        pipeline_status.get("commit"),
        production_deploy.get("commit"),
        system_state.get("github_origin_main_commit"),
    )
    return {
        "production_running_commit": running,
        "github_origin_main_commit": origin,
        "production_github_sync": bool(running and origin and running == origin),
    }


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


def status_payload():
    system_state = read_json(STATE / "system_state.json", {})
    github_actions = read_json(STATE / "github_actions_status.json", {})
    pipeline_status = read_json(STATE / "pipeline_status.json", {})
    production_readiness = read_json(STATE / "production_readiness_status.json", {})
    last_health_check = read_json(STATE / "last_health_check_status.json", {})
    legacy_quality_gate = read_json(STATE / "quality_gate_status.json", {})
    production_readiness_policy = read_json(
        STATE / "production_readiness_policy.json",
        read_json(ROOT / "state_templates/production_readiness_policy.json", {}),
    )
    readiness_report_text = read_text(REPORTS / "production_readiness_last_report.md")
    return {
        "ok": True,
        "time": now(),
        "system_state": system_state,
        "controlled_execution": controlled_execution_summary(system_state),
        "qualityGateView": build_quality_gate_view(production_readiness, last_health_check, legacy_quality_gate),
        "workers": read_json(STATE / "workers.json", {"workers": []}),
        "tasks": read_json(STATE / "task_queue.json", {"tasks": []}),
        "modules": read_json(STATE / "module_registry.json", read_json(ROOT / "state_templates/module_registry.json", {"modules": []})),
        "actions": read_json(STATE / "action_catalog.json", read_json(ROOT / "state_templates/action_catalog.json", {"actions": []})),
        "dashboard_settings": read_json(STATE / "dashboard_settings.json", read_json(ROOT / "state_templates/dashboard_settings.json", {})),
        "module_settings": read_json(STATE / "module_settings.json", read_json(ROOT / "state_templates/module_settings.json", {})),
        "production_policy": read_json(ROOT / "state_templates/production_policy.json", {}),
        "production_readiness": production_readiness,
        "production_deploy": read_json(STATE / "production_deploy_status.json", {}),
        "production_environment": read_json(STATE / "production_environment_status.json", {}),
        "staging_deploy": read_json(STATE / "staging_deploy_status.json", {}),
        "production_runtime": read_json(STATE / "production_runtime_status.json", {}),
        "github_actions": github_actions,
        "pipeline_status": pipeline_status,
        "rollback": read_json(STATE / "rollback_status.json", {}),
        "rollback_point": read_json(STATE / "rollback_point.json", {}),
        "last_health_check": last_health_check,
        "last_smoke_test": read_json(STATE / "last_smoke_test_status.json", {}),
        "github_safe_flow": read_json(STATE / "github_safe_flow_status.json", {}),
        "reports": sorted([p.name for p in REPORTS.glob("*.md")]) if REPORTS.exists() else [],
        "report_text_status": {
            "readiness": normalize_readiness_report_text(readiness_report_text, production_readiness_policy),
        },
        "report_text": {
            "readiness": readiness_report_text,
            "deploy": read_text(REPORTS / "production_deploy_last_report.md"),
            "rollback": read_text(REPORTS / "rollback_simulation_last_report.md"),
            "github": read_text(REPORTS / "github_safe_flow_last_report.md"),
        },
    }


def pipeline_flow_payload():
    return build_pipeline_flow(ROOT)


def telegram_asset_list_payload(query: str):
    return build_telegram_asset_list(ROOT, query)


def telegram_asset_detail_payload(asset_id: str):
    return build_telegram_asset_detail(ROOT, asset_id)


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
            system_state = read_json(STATE / "system_state.json", {})
            commit_summary = production_commit_summary(system_state)
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
                **commit_summary,
            })
            return
        if parsed.path == "/api/status":
            self.send_json(status_payload())
            return
        if parsed.path == "/api/pipeline-flow":
            self.send_json(pipeline_flow_payload())
            return
        if parsed.path == "/api/dashboard/telegram-assets":
            self.send_json(telegram_asset_list_payload(parsed.query))
            return
        if parsed.path.startswith("/api/dashboard/telegram-assets/"):
            asset_id = unquote(parsed.path.rsplit("/", 1)[-1])
            payload, code = telegram_asset_detail_payload(asset_id)
            self.send_json(payload, code)
            return
        if parsed.path in ("/", "/index.html"):
            self.send_raw((STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        self.send_json({"ok": False, "error": "not_found"}, 404)

    def do_POST(self) -> None:
        data = self.body()
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/dashboard/telegram-assets"):
            self.send_json({"ok": False, "error": "method_not_allowed", "read_only": True}, 405)
            return
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
