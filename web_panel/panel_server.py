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

import auth as panel_auth


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()
STATE = ROOT / "state"
REPORTS = ROOT / "reports"
LOGS = ROOT / "logs"
STATIC_DIR = ROOT / "web_panel" / "static"
HOST = os.environ.get("CODEX_PANEL_HOST", "0.0.0.0")
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
    names = ["codex-panel", "codex-lifecycle", "codex-cto", "codex-worker-1", "codex-worker-2", "codex-worker-3", "codex-worker-4", "codex-watchdog"]
    return [{"name": n, "active": service_status(n), "enabled": service_enabled(n)} for n in names]


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


def status_payload():
    return {
        "ok": True,
        "time": now(),
        "system_state": read_json(STATE / "system_state.json", {}),
        "workers": read_json(STATE / "workers.json", {"workers": []}),
        "tasks": read_json(STATE / "task_queue.json", {"tasks": []}),
        "services": services(),
        "modules": read_json(STATE / "module_registry.json", read_json(ROOT / "state_templates/module_registry.json", {"modules": []})),
        "actions": read_json(STATE / "action_catalog.json", read_json(ROOT / "state_templates/action_catalog.json", {"actions": []})),
        "dashboard_settings": read_json(STATE / "dashboard_settings.json", read_json(ROOT / "state_templates/dashboard_settings.json", {})),
        "module_settings": read_json(STATE / "module_settings.json", read_json(ROOT / "state_templates/module_settings.json", {})),
        "production_policy": read_json(ROOT / "state_templates/production_policy.json", {}),
        "auth": panel_auth.public_auth_state(),
        "production_readiness": read_json(STATE / "production_readiness_status.json", {}),
        "production_deploy": read_json(STATE / "production_deploy_status.json", {}),
        "production_environment": read_json(STATE / "production_environment_status.json", {}),
        "staging_deploy": read_json(STATE / "staging_deploy_status.json", {}),
        "production_runtime": read_json(STATE / "production_runtime_status.json", {}),
        "github_actions": read_json(STATE / "github_actions_status.json", {}),
        "pipeline_status": read_json(STATE / "pipeline_status.json", {}),
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
