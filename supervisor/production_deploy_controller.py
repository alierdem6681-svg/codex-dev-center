#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()
STATE = ROOT / "state"
REPORTS = ROOT / "reports"

CRITICAL_EXCEPTION_TERMS = [
    "secret",
    "iam owner",
    "iam editor",
    "billing",
    "drop table",
    "truncate table",
    "database delete",
    "dns",
    "firewall",
    "google ads mutate",
]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    return default


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_cmd(command: str, timeout: int = 300) -> dict[str, Any]:
    if not command.strip():
        return {"ok": False, "skipped": True, "stdout": "", "stderr": "empty_command", "returncode": 1}
    try:
        proc = subprocess.run(shlex.split(command), cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "cmd": command,
        }
    except Exception as exc:
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": str(exc), "cmd": command}


def settings() -> dict[str, Any]:
    module_settings = read_json(ROOT / "state_templates/module_settings.json", {})
    production_policy = read_json(ROOT / "state_templates/production_policy.json", {})
    deploy = module_settings.get("deploy_pipeline", {}) if isinstance(module_settings, dict) else {}
    return {
        "automatic_production_enabled": bool(production_policy.get("automatic_production_enabled", deploy.get("automatic_production_enabled", False))),
        "manual_approval_required": bool(deploy.get("production_requires_explicit_approval", False)),
        "readiness_required": bool(deploy.get("production_requires_readiness_pass", True)),
        "staging_required": bool(deploy.get("production_requires_staging_pass", True)),
        "rollback_required": bool(deploy.get("production_requires_rollback_pass", True)),
        "auto_rollback_on_failure": bool(production_policy.get("auto_rollback_on_failure", True)),
    }


def critical_exception_scan() -> dict[str, Any]:
    text = " ".join(
        [
            os.environ.get("CODEX_STAGING_DEPLOY_COMMAND", ""),
            os.environ.get("CODEX_PRODUCTION_DEPLOY_COMMAND", ""),
            os.environ.get("CODEX_ROLLBACK_COMMAND", ""),
            os.environ.get("CODEX_PRODUCTION_DEPLOY_DESCRIPTION", ""),
        ]
    ).lower()
    matched = [term for term in CRITICAL_EXCEPTION_TERMS if term in text]
    return {"ok": not matched, "matched_terms": matched, "requires_risk_report": bool(matched)}


def run_readiness() -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "supervisor/production_readiness_suite.py"), "--json"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=240,
    )
    status = read_json(STATE / "production_readiness_status.json", {})
    return {
        "ok": proc.returncode == 0 and status.get("status") == "PASS",
        "returncode": proc.returncode,
        "status": status,
        "stdout": proc.stdout[-3000:],
        "stderr": proc.stderr[-3000:],
    }


def health_check() -> dict[str, Any]:
    candidates = [
        ROOT / "supervisor/service_watchdog.py",
        ROOT / "web_panel/server.py",
    ]
    return {"ok": all(p.exists() for p in candidates), "mode": "static_post_deploy_health_check"}


def start(auto: bool = False) -> dict[str, Any]:
    cfg = settings()
    readiness = run_readiness() if cfg["readiness_required"] else {"ok": True, "status": {}}
    critical = critical_exception_scan()

    staging_cmd = os.environ.get("CODEX_STAGING_DEPLOY_COMMAND", "").strip()
    production_cmd = os.environ.get("CODEX_PRODUCTION_DEPLOY_COMMAND", "").strip()
    rollback_cmd = os.environ.get("CODEX_ROLLBACK_COMMAND", "").strip()
    execute_enabled = os.environ.get("CODEX_PRODUCTION_DEPLOY_EXECUTE", "") == "1"

    blockers: list[str] = []
    if not cfg["automatic_production_enabled"]:
        blockers.append("automatic_production_disabled")
    if not readiness["ok"]:
        blockers.append("readiness_not_pass")
    if not critical["ok"]:
        blockers.append("critical_exception_detected")
    if cfg["staging_required"] and not staging_cmd:
        blockers.append("staging_deploy_target_missing")
    if not production_cmd:
        blockers.append("production_deploy_target_missing")
    if cfg["rollback_required"] and not rollback_cmd:
        blockers.append("rollback_command_missing")
    if not execute_enabled:
        blockers.append("production_execute_flag_missing")

    result: dict[str, Any] = {
        "ok": False,
        "status": "PENDING",
        "checked_at": now(),
        "auto_requested": auto,
        "settings": cfg,
        "critical_exceptions": critical,
        "readiness": readiness,
        "deploy_target": {
            "staging_command_configured": bool(staging_cmd),
            "production_command_configured": bool(production_cmd),
            "rollback_command_configured": bool(rollback_cmd),
            "execute_enabled": execute_enabled,
        },
        "blockers": blockers,
        "production_deploy_performed": False,
        "staging_deploy_performed": False,
        "rollback_performed": False,
        "mutating_cloud_operations_performed": False,
    }

    if blockers:
        result["status"] = "BLOCKED"
        write_outputs(result)
        return result

    staging_result = run_cmd(staging_cmd, timeout=600)
    result["staging_deploy_result"] = staging_result
    result["staging_deploy_performed"] = staging_result["ok"]
    if not staging_result["ok"]:
        result["status"] = "FAILED_STAGING"
        write_outputs(result)
        return result

    production_result = run_cmd(production_cmd, timeout=900)
    result["production_deploy_result"] = production_result
    result["production_deploy_performed"] = production_result["ok"]
    if not production_result["ok"]:
        result["status"] = "FAILED_PRODUCTION"
        if cfg["auto_rollback_on_failure"] and rollback_cmd:
            result["rollback_result"] = run_cmd(rollback_cmd, timeout=600)
            result["rollback_performed"] = bool(result["rollback_result"].get("ok"))
        write_outputs(result)
        return result

    result["post_deploy_health_check"] = health_check()
    result["ok"] = bool(result["post_deploy_health_check"]["ok"])
    result["status"] = "PASS" if result["ok"] else "FAILED_HEALTH_CHECK"
    if not result["ok"] and cfg["auto_rollback_on_failure"] and rollback_cmd:
        result["rollback_result"] = run_cmd(rollback_cmd, timeout=600)
        result["rollback_performed"] = bool(result["rollback_result"].get("ok"))
    write_outputs(result)
    return result


def write_outputs(result: dict[str, Any]) -> None:
    atomic_write_json(STATE / "production_deploy_status.json", result)
    REPORTS.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Production Deploy Last Report",
        "",
        f"Generated at: {result['checked_at']}",
        f"Status: {result['status']}",
        f"Production deploy performed: {result['production_deploy_performed']}",
        f"Staging deploy performed: {result['staging_deploy_performed']}",
        f"Rollback performed: {result['rollback_performed']}",
        "",
        "## Blockers",
    ]
    lines += [f"- {item}" for item in result.get("blockers", [])] or ["- Yok"]
    lines += [
        "",
        "## Safety",
        f"- Critical exceptions: {', '.join(result['critical_exceptions'].get('matched_terms', [])) or 'none'}",
        "- IAM/secret/database/DNS/firewall/billing/Google Ads mutate performed: false",
    ]
    (REPORTS / "production_deploy_last_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--auto", action="store_true")
    args = parser.parse_args()
    if args.cmd == "start":
        result = start(auto=args.auto)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] != "PASS":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
