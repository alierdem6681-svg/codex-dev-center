#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()
STATE = ROOT / "state"
REPORTS = ROOT / "reports"
LOGS = ROOT / "logs"
STATIC_DIR = ROOT / "web_panel" / "static"
TOKEN_FILE = STATE / "panel_token.txt"
HOST = "0.0.0.0"
PORT = 8080


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


def token() -> str:
    return read_text(TOKEN_FILE).strip()


def authorized(handler: BaseHTTPRequestHandler) -> bool:
    current = token()
    if not current:
        return False
    parsed = urlparse(handler.path)
    query = parse_qs(parsed.query)
    if query.get("token", [""])[0] == current:
        return True
    return f"codex_panel_token={current}" in handler.headers.get("Cookie", "")


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
        "production_readiness": read_json(STATE / "production_readiness_status.json", {}),
        "production_deploy": read_json(STATE / "production_deploy_status.json", {}),
        "github_safe_flow": read_json(STATE / "github_safe_flow_status.json", {}),
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

    def send_raw(self, payload: bytes, content_type: str = "application/json; charset=utf-8", code: int = 200, cookie: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if cookie and token():
            self.send_header("Set-Cookie", f"codex_panel_token={token()}; Path=/; HttpOnly; SameSite=Lax")
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

    def do_GET(self):
        parsed = urlparse(self.path)
        if not authorized(self):
            self.send_json({"ok": False, "error": "unauthorized"}, 401)
            return
        if parsed.path == "/health":
            self.send_json({"ok": True, "service": "codex-panel", "production_pipeline": True})
            return
        if parsed.path == "/api/status":
            self.send_json(status_payload())
            return
        if parsed.path in ("/", "/index.html"):
            self.send_raw((STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8", 200, True)
            return
        self.send_json({"ok": False, "error": "not_found"}, 404)

    def do_POST(self):
        if not authorized(self):
            self.send_json({"ok": False, "error": "unauthorized"}, 401)
            return
        data = self.body()
        action = data.get("action")
        if action == "production_readiness_suite":
            self.send_json(run_cmd([sys.executable, "supervisor/production_readiness_suite.py", "--json"], 240))
            return
        if action == "production_deploy_start":
            self.send_json(run_cmd([sys.executable, "supervisor/production_deploy_controller.py", "start", "--auto"], 300))
            return
        if action == "github_safe_flow_dry_run":
            self.send_json(run_cmd([sys.executable, "supervisor/github_safe_flow.py", "dry-run"], 180))
            return
        if action == "rollback_simulation":
            self.send_json(run_cmd([sys.executable, "supervisor/production_readiness_suite.py", "--json"], 240))
            return
        self.send_json({"ok": False, "error": "unknown_action"}, 400)


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Codex dashboard listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
