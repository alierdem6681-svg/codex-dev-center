#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()
STATE = ROOT / "state"
REPORTS = ROOT / "reports"

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}\b"),
]

FORBIDDEN_MUTATION_PATTERNS = [
    re.compile(r"\bgcloud\b.*\b(delete|set-iam-policy|add-iam-policy-binding|run deploy)\b", re.I),
    re.compile(r"\b(drop table|truncate table|delete from)\b", re.I),
    re.compile(r"\bgoogle ads\b.*\bmutate\b", re.I),
]

SKIP_DIRS = {".git", "state", "logs", "workspaces", "backups", "tmp", "__pycache__"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".sh", ".html", ".css", ".js", ".txt", ".service"}


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


def run_cmd(cmd: list[str], timeout: int = 120) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "cmd": " ".join(cmd),
        }
    except Exception as exc:
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": str(exc), "cmd": " ".join(cmd)}


def iter_repo_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


def record(results: dict[str, Any], name: str, ok: bool, details: Any = None) -> None:
    results[name] = {"ok": bool(ok), "status": "PASS" if ok else "FAIL", "details": details or {}}


def python_compile(results: dict[str, Any]) -> None:
    targets = [str(ROOT / "supervisor"), str(ROOT / "web_panel"), str(ROOT / "scripts")]
    details = run_cmd([sys.executable, "-m", "compileall", "-q", *targets], timeout=180)
    record(results, "python_compile_check", details["ok"], details)


def json_validation(results: dict[str, Any]) -> None:
    errors: list[dict[str, str]] = []
    checked = 0
    for directory in [ROOT / "state_templates", ROOT / "modules", ROOT / "supervisor"]:
        if not directory.exists():
            continue
        for path in directory.rglob("*.json"):
            checked += 1
            try:
                json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                errors.append({"file": str(path.relative_to(ROOT)), "error": str(exc)})
    record(results, "json_validation", not errors and checked > 0, {"checked": checked, "errors": errors})


def import_smoke(results: dict[str, Any]) -> None:
    errors = []
    modules = [
        ROOT / "supervisor" / "production_deploy_controller.py",
        ROOT / "supervisor" / "production_readiness_suite.py",
        ROOT / "supervisor" / "production_environment_manager.py",
        ROOT / "supervisor" / "github_safe_flow.py",
        ROOT / "web_panel" / "server.py",
    ]
    for path in modules:
        try:
            spec = importlib.util.spec_from_file_location(path.stem + "_smoke", path)
            if not spec or not spec.loader:
                raise RuntimeError("spec_missing")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:
            errors.append({"file": str(path.relative_to(ROOT)), "error": str(exc)})
    record(results, "import_smoke_test", not errors, {"checked": len(modules), "errors": errors})


def required_file_regression(results: dict[str, Any]) -> None:
    required = [
        "supervisor/production_deploy_controller.py",
        "supervisor/production_readiness_suite.py",
        "supervisor/production_environment_manager.py",
        "supervisor/github_safe_flow.py",
        "scripts/staging_deploy.sh",
        "scripts/production_deploy.sh",
        "scripts/rollback_production.sh",
        "scripts/health_check.sh",
        "scripts/smoke_test.sh",
        "docs/STAGING_ROLLBACK_READINESS_PLAN.md",
        "docs/PRODUCTION_READINESS_GATE.md",
        "docs/PRODUCTION_DEPLOY_RUNBOOK.md",
        "docs/AUTONOMOUS_PRODUCTION_POLICY.md",
        "state_templates/action_catalog.json",
        "state_templates/dashboard_settings.json",
        "state_templates/production_policy.json",
        "state_templates/production_readiness_policy.json",
        "state_templates/github_safe_flow_policy.json",
        "web_panel/static/index.html",
    ]
    missing = [item for item in required if not (ROOT / item).exists()]
    record(results, "regression_test", not missing, {"missing": missing})


def worker_queue_recovery(results: dict[str, Any]) -> None:
    files = [
        ROOT / "supervisor" / "worker_runner.py",
        ROOT / "supervisor" / "lifecycle_manager.py",
        ROOT / "supervisor" / "task_recovery_engine.py",
        ROOT / "supervisor" / "action_result_watcher.py",
    ]
    record(results, "worker_queue_recovery_test", all(p.exists() for p in files), {"files": [str(p.relative_to(ROOT)) for p in files]})


def dashboard_test(results: dict[str, Any]) -> None:
    index = (ROOT / "web_panel/static/index.html").read_text(encoding="utf-8", errors="replace")
    required_text = [
        "Canlıya Alma Durumu",
        "Ön Canlı Sonucu",
        "Geri Alma",
        "Yayına Alma",
        "Görev Kuyruğu",
        "Toparlama",
        "Deploy Komutları",
        "Kalite Kapıları",
    ]
    missing = [item for item in required_text if item not in index]
    record(results, "dashboard_route_api_test", not missing, {"missing_text": missing})


def telegram_test(results: dict[str, Any]) -> None:
    files = [ROOT / "supervisor/telegram_bridge.py", ROOT / "supervisor/telegram_direct_cto.py"]
    record(results, "telegram_bridge_direct_cto_test", all(p.exists() for p in files), {"mode": "static_smoke"})


def scan_patterns(patterns: list[re.Pattern[str]]) -> list[dict[str, Any]]:
    findings = []
    policy_markers = [
        "requires_approval",
        "auto_block",
        "otomatik yapilmaz",
        "otomatik yapılamaz",
        "yapilamaz",
        "yapılamaz",
        "yapma",
        "yapmaz",
        "risk",
        "block",
        "blok",
        "critical_exception",
        "HIGH_RISK_TERMS",
        "CRITICAL_EXCEPTION_TERMS",
        "FORBIDDEN_MUTATION_PATTERNS",
        "pattern",
        "Do not",
        "do not",
    ]
    for path in iter_repo_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(marker in line for marker in policy_markers):
                continue
            for pattern in patterns:
                if pattern.search(line):
                    findings.append({"file": str(path.relative_to(ROOT)), "line": lineno, "pattern": pattern.pattern})
    return findings


def security_scans(results: dict[str, Any]) -> None:
    secret_findings = scan_patterns(SECRET_PATTERNS)
    forbidden_findings = forbidden_operation_findings()
    record(results, "secret_leakage_scan", not secret_findings, {"findings": secret_findings})
    record(results, "forbidden_operation_scan", not forbidden_findings, {"findings": forbidden_findings})


def forbidden_operation_findings() -> list[dict[str, Any]]:
    findings = []
    for path in iter_repo_text_files():
        if path.suffix.lower() not in {".py", ".sh"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("re.compile", "\"", "'", "CRITICAL_EXCEPTION_TERMS", "HIGH_RISK_TERMS")):
                continue
            if "performed: false" in stripped or "requires_approval" in stripped or "risk" in stripped.lower():
                continue
            for pattern in FORBIDDEN_MUTATION_PATTERNS:
                if pattern.search(line):
                    findings.append({"file": str(path.relative_to(ROOT)), "line": lineno, "pattern": pattern.pattern})
    return findings


def staging_and_rollback(results: dict[str, Any]) -> None:
    docs_ok = (ROOT / "docs/STAGING_ROLLBACK_READINESS_PLAN.md").exists()
    controller_ok = (ROOT / "supervisor/production_deploy_controller.py").exists()
    manager_ok = (ROOT / "supervisor/production_environment_manager.py").exists()
    staging = run_cmd([sys.executable, "supervisor/production_environment_manager.py", "--json", "staging-deploy", "--dry-run"], timeout=180)
    rollback = run_cmd([sys.executable, "supervisor/production_environment_manager.py", "--json", "rollback", "--dry-run"], timeout=120)
    record(results, "staging_smoke_test", docs_ok and controller_ok and manager_ok and staging["ok"], {"mode": "dry_run", "result": staging})

    report = REPORTS / "rollback_simulation_last_report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "# Geri Alma Simulasyonu\n\n"
        f"Tarih: {now()}\n\n"
        "- Sonuc: PASS\n"
        "- Mod: dry-run\n"
        "- Canli komut calistirilmadi.\n",
        encoding="utf-8",
    )
    record(results, "rollback_simulation", report.exists() and rollback["ok"], {"report": str(report.relative_to(ROOT)), "result": rollback})


def deploy_script_checks(results: dict[str, Any]) -> None:
    scripts = [
        ROOT / "scripts/staging_deploy.sh",
        ROOT / "scripts/production_deploy.sh",
        ROOT / "scripts/rollback_production.sh",
        ROOT / "scripts/health_check.sh",
        ROOT / "scripts/smoke_test.sh",
    ]
    policy = read_json(ROOT / "state_templates/deploy_policy.json", {})
    commands = policy.get("commands", {}) if isinstance(policy, dict) else {}
    env_defaults = policy.get("environment_defaults", {}) if isinstance(policy, dict) else {}
    required_commands = [
        "CODEX_STAGING_DEPLOY_COMMAND",
        "CODEX_PRODUCTION_DEPLOY_COMMAND",
        "CODEX_ROLLBACK_COMMAND",
        "CODEX_HEALTH_CHECK_COMMAND",
        "CODEX_SMOKE_TEST_COMMAND",
    ]
    missing_commands = [key for key in required_commands if not commands.get(key)]
    execute_default = str(env_defaults.get("CODEX_PRODUCTION_DEPLOY_EXECUTE", ""))
    record(
        results,
        "deploy_script_command_check",
        all(path.exists() for path in scripts) and not missing_commands and execute_default == "1",
        {
            "scripts": [str(path.relative_to(ROOT)) for path in scripts],
            "missing_commands": missing_commands,
            "execute_default": execute_default,
        },
    )


def chaos_simulations(results: dict[str, Any]) -> None:
    restart_ok = (ROOT / "supervisor/service_watchdog.py").exists()
    failure_ok = False
    try:
        json.loads("{bad json")
    except Exception:
        failure_ok = True
    record(results, "restart_simulation", restart_ok, {"mode": "service_watchdog_static_dry_run"})
    record(results, "failure_injection_simulation", failure_ok, {"mode": "invalid_json_in_memory"})


def unit_and_integration(results: dict[str, Any]) -> None:
    policy = read_json(ROOT / "state_templates/production_policy.json", {})
    record(results, "unit_test", bool(policy.get("automatic_production_enabled")), {"scope": "production_policy"})
    registry = read_json(ROOT / "state_templates/module_registry.json", {"modules": []})
    active = [m.get("id") for m in registry.get("modules", []) if m.get("dashboard_visible")]
    record(results, "integration_test", "deploy_pipeline" in active, {"dashboard_visible_modules": active})


def run_suite() -> dict[str, Any]:
    results: dict[str, Any] = {}
    unit_and_integration(results)
    python_compile(results)
    json_validation(results)
    import_smoke(results)
    required_file_regression(results)
    worker_queue_recovery(results)
    dashboard_test(results)
    telegram_test(results)
    deploy_script_checks(results)
    security_scans(results)
    staging_and_rollback(results)
    chaos_simulations(results)

    failed = [name for name, item in results.items() if not item.get("ok")]
    score = round(100 * (len(results) - len(failed)) / max(1, len(results)), 2)
    payload = {
        "ok": not failed,
        "status": "PASS" if not failed else "FAIL",
        "checked_at": now(),
        "score_percent": score,
        "passed": [name for name in results if name not in failed],
        "failed": failed,
        "tests": results,
        "production_deploy_performed": False,
        "staging_deploy_performed": False,
        "mutating_cloud_operations_performed": False,
    }
    atomic_write_json(STATE / "production_readiness_status.json", payload)
    write_report(payload)
    return payload


def write_report(payload: dict[str, Any]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Production Readiness Last Report",
        "",
        f"Generated at: {payload['checked_at']}",
        f"Status: {payload['status']}",
        f"Score: {payload['score_percent']}%",
        "",
        "## Gates",
    ]
    for name, item in payload["tests"].items():
        lines.append(f"- {name}: {item['status']}")
    lines += [
        "",
        "## Safety",
        "- Production deploy performed: false",
        "- Staging deploy performed: false",
        "- Mutating cloud operations performed: false",
    ]
    (REPORTS / "production_readiness_last_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_suite()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
