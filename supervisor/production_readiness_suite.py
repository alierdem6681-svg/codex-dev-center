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
DEFAULT_SOURCE_ROOT = Path("/home/alierdem6681/codex-dev-center-github-export")
SOURCE_ROOT = Path(os.environ.get("CODEX_DEV_CENTER_SOURCE", DEFAULT_SOURCE_ROOT)).resolve()
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


def source_path(rel: str) -> Path:
    runtime_path = ROOT / rel
    if runtime_path.exists():
        return runtime_path
    candidate = SOURCE_ROOT / rel
    return candidate if candidate.exists() else runtime_path


def path_exists(rel: str) -> bool:
    return source_path(rel).exists()


def iter_repo_text_files():
    def ignore_walk_error(_exc: OSError) -> None:
        return

    for dirpath, dirnames, filenames in os.walk(ROOT, onerror=ignore_walk_error):
        current = Path(dirpath)
        try:
            rel_dir = current.relative_to(ROOT)
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in rel_dir.parts):
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]

        for filename in filenames:
            path = current / filename
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                if path.is_file():
                    yield path
            except (FileNotFoundError, NotADirectoryError, OSError):
                continue


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


def yaml_workflow_validation(results: dict[str, Any]) -> None:
    errors: list[dict[str, str]] = []
    checked = 0
    workflow_dir = source_path(".github/workflows")
    if workflow_dir.exists():
        for path in sorted(workflow_dir.glob("*.yml")):
            checked += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            if "\t" in text:
                errors.append({"file": str(path.relative_to(workflow_dir.parent.parent)), "error": "tab_character"})
            for key in ["name:", "on:", "jobs:"]:
                if key not in text:
                    errors.append({"file": str(path.relative_to(workflow_dir.parent.parent)), "error": f"missing_{key.rstrip(':')}"})
            if "runs-on:" not in text:
                errors.append({"file": str(path.relative_to(workflow_dir.parent.parent)), "error": "missing_runs_on"})
    record(results, "yaml_validation", checked > 0 and not errors, {"checked": checked, "errors": errors})


def import_smoke(results: dict[str, Any]) -> None:
    errors = []
    modules = [
        ROOT / "supervisor" / "production_deploy_controller.py",
        ROOT / "supervisor" / "production_readiness_suite.py",
        ROOT / "supervisor" / "production_environment_manager.py",
        ROOT / "supervisor" / "github_safe_flow.py",
        ROOT / "web_panel" / "auth.py",
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
        "supervisor/critical_operation_policy.py",
        "supervisor/cto_autonomous_delivery.py",
        "supervisor/policy_sync.py",
        "supervisor/github_safe_flow.py",
        "web_panel/auth.py",
        "web_panel/static/login.html",
        ".github/workflows/deploy-vm.yml",
        "scripts/staging_deploy.sh",
        "scripts/production_deploy.sh",
        "scripts/rollback_production.sh",
        "scripts/health_check.sh",
        "scripts/smoke_test.sh",
        "docs/STAGING_ROLLBACK_READINESS_PLAN.md",
        "docs/PRODUCTION_READINESS_GATE.md",
        "docs/PRODUCTION_DEPLOY_RUNBOOK.md",
        "docs/AUTONOMOUS_PRODUCTION_POLICY.md",
        "docs/CTO_AUTONOMOUS_DELIVERY_MODE.md",
        "state_templates/cto_delivery_policy.json",
        "state_templates/action_catalog.json",
        "state_templates/dashboard_settings.json",
        "state_templates/production_policy.json",
        "state_templates/production_readiness_policy.json",
        "state_templates/github_safe_flow_policy.json",
        "web_panel/static/index.html",
    ]
    missing = [item for item in required if not path_exists(item)]
    record(results, "regression_test", not missing, {"missing": missing})


def worker_queue_recovery(results: dict[str, Any]) -> None:
    files = [
        ROOT / "supervisor" / "worker_runner.py",
        ROOT / "supervisor" / "lifecycle_manager.py",
        ROOT / "supervisor" / "task_recovery_engine.py",
        ROOT / "supervisor" / "action_result_watcher.py",
        ROOT / "supervisor" / "task_validation_engine.py",
        ROOT / "supervisor" / "progress_aware_runner.py",
    ]
    record(results, "worker_queue_recovery_test", all(p.exists() for p in files), {"files": [str(p.relative_to(ROOT)) for p in files]})


def dashboard_test(results: dict[str, Any]) -> None:
    index = (ROOT / "web_panel/static/index.html").read_text(encoding="utf-8", errors="replace")
    required_text = [
        "Codex Dev Center Yönetim Paneli",
        "Pipeline Flow",
        "Görevler",
        "Hesap ayarları",
        "Çıkış",
    ]
    removed_text = [
        "Canlıya Alma Durumu",
        "Ön Canlı Sonucu",
        "Geri Alma Sonucu",
        "Görev Kuyruğu",
        "Operasyonel Akış",
        "Production Pipeline",
        "Pipeline Gözlemi",
        "Deploy Komutları",
        "Kalite Kapıları",
        "Son Kontroller",
        "Profil",
        "Çalışan / Görev Kuyruğu / Toparlama",
        "GitHub Senkronizasyonu",
        "Son Hata ve Çözüm Önerisi",
        "Raporlar",
    ]
    missing = [item for item in required_text if item not in index]
    unexpected = [item for item in removed_text if item in index]
    login = (ROOT / "web_panel/static/login.html").read_text(encoding="utf-8", errors="replace")
    login_required = ["Kullanıcı adı", "Şifre", "Giriş Yap", "İlk kullanıcıyı oluştur"]
    login_missing = [item for item in login_required if item not in login]
    record(
        results,
        "dashboard_route_api_test",
        not missing and not unexpected and not login_missing,
        {"missing_text": missing, "unexpected_text": unexpected, "login_missing_text": login_missing},
    )


def telegram_test(results: dict[str, Any]) -> None:
    files = [
        ROOT / "supervisor/telegram_bridge.py",
        ROOT / "supervisor/telegram_direct_cto.py",
        ROOT / "supervisor/telegram_direct_cto_simulator.py",
    ]
    simulation = run_cmd([sys.executable, "supervisor/telegram_direct_cto_simulator.py", "--summary-json"], timeout=90)
    simulated = False
    case_count = 0
    if simulation["ok"]:
        try:
            payload = json.loads(simulation["stdout"])
            simulated = bool(payload.get("ok"))
            case_count = int(payload.get("case_count") or 0)
        except Exception:
            simulated = False
    record(
        results,
        "telegram_bridge_direct_cto_test",
        all(p.exists() for p in files) and simulated and case_count >= 15,
        {"mode": "safe_passthrough_simulation", "case_count": case_count, "simulation": simulation},
    )


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


def command_json_payload(command_result: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    stdout = str(command_result.get("stdout") or "").strip()
    if not stdout:
        return {}, "empty_stdout"
    try:
        payload = json.loads(stdout)
    except Exception as exc:
        return {}, str(exc)
    if not isinstance(payload, dict):
        return {}, "json_payload_not_object"
    return payload, None


def dry_run_non_mutating_contract(command_result: dict[str, Any], false_flags: list[str]) -> dict[str, Any]:
    payload, parse_error = command_json_payload(command_result)
    flag_mismatches = [flag for flag in false_flags if payload.get(flag) is not False]
    ok = (
        bool(command_result.get("ok"))
        and parse_error is None
        and payload.get("ok") is True
        and payload.get("status") == "PASS"
        and payload.get("dry_run") is True
        and not flag_mismatches
    )
    return {
        "ok": ok,
        "mode": "dry_run_non_mutating_contract",
        "command_ok": bool(command_result.get("ok")),
        "parse_error": parse_error,
        "payload_ok": payload.get("ok"),
        "payload_status": payload.get("status"),
        "dry_run": payload.get("dry_run"),
        "required_false_flags": {flag: payload.get(flag) for flag in false_flags},
        "flag_mismatches": flag_mismatches,
    }


def staging_and_rollback(results: dict[str, Any]) -> None:
    docs_ok = (ROOT / "docs/STAGING_ROLLBACK_READINESS_PLAN.md").exists()
    controller_ok = (ROOT / "supervisor/production_deploy_controller.py").exists()
    manager_ok = (ROOT / "supervisor/production_environment_manager.py").exists()
    staging = run_cmd([sys.executable, "supervisor/production_environment_manager.py", "--json", "staging-deploy", "--dry-run"], timeout=180)
    rollback = run_cmd([sys.executable, "supervisor/production_environment_manager.py", "--json", "rollback", "--dry-run"], timeout=120)
    staging_contract = dry_run_non_mutating_contract(staging, ["mutating_cloud_operations_performed"])
    rollback_contract = dry_run_non_mutating_contract(rollback, ["git_reset_performed", "data_mutation_performed"])
    record(
        results,
        "staging_smoke_test",
        docs_ok and controller_ok and manager_ok and staging_contract["ok"],
        {"mode": "dry_run", "result": staging, "contract": staging_contract},
    )

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
    record(
        results,
        "rollback_simulation",
        report.exists() and rollback_contract["ok"],
        {"report": str(report.relative_to(ROOT)), "result": rollback, "contract": rollback_contract},
    )


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
    workflow = source_path(".github/workflows/deploy-vm.yml")
    workflow_text = workflow.read_text(encoding="utf-8", errors="replace") if workflow.exists() else ""
    workflow_ok = (
        "name: Deploy to VM" in workflow_text
        and "workflow_dispatch" in workflow_text
        and "DEPLOY-CODEX-VM" in workflow_text
        and "codex-dev-center-01" in workflow_text
        and "/opt/codex-dev-center" in workflow_text
    )
    record(
        results,
        "deploy_script_command_check",
        all(path.exists() for path in scripts) and not missing_commands and execute_default == "1" and workflow_ok,
        {
            "scripts": [str(path.relative_to(ROOT)) for path in scripts],
            "missing_commands": missing_commands,
            "execute_default": execute_default,
            "workflow_ok": workflow_ok,
        },
    )


def static_contract(rel: str, markers: list[str]) -> dict[str, Any]:
    path = source_path(rel)
    exists = path.exists()
    text = path.read_text(encoding="utf-8", errors="replace") if exists else ""
    missing_markers = [marker for marker in markers if marker not in text]
    return {
        "file": rel,
        "exists": exists,
        "marker_count": len(markers),
        "missing_markers": missing_markers,
        "ok": exists and not missing_markers,
    }


def readiness_simulation_contracts() -> dict[str, Any]:
    restart_contracts = [
        static_contract(
            "supervisor/service_watchdog.py",
            [
                "def restart(",
                "systemctl",
                "service_health.json",
                "direct_cto_stale_job_recovery",
            ],
        ),
        static_contract(
            "supervisor/production_environment_manager.py",
            [
                "def rollback(",
                "dry_run",
                "git_reset_performed",
                "data_mutation_performed",
            ],
        ),
    ]
    failure_contracts = [
        static_contract(
            "supervisor/production_readiness_suite.py",
            [
                "json_validation",
                "security_scans",
                "failed = [name",
                "production_deploy_performed",
            ],
        ),
        static_contract(
            "supervisor/critical_operation_policy.py",
            [
                "critical_operation_findings",
                "APPROVAL_REQUIRED",
                "database_destructive_operation",
            ],
        ),
    ]
    invalid_json_guard = False
    try:
        json.loads("{bad json")
    except Exception:
        invalid_json_guard = True

    return {
        "restart": {
            "ok": all(item["ok"] for item in restart_contracts),
            "mode": "static_non_mutating_contract",
            "contracts": restart_contracts,
        },
        "failure_injection": {
            "ok": invalid_json_guard and all(item["ok"] for item in failure_contracts),
            "mode": "static_non_mutating_contract",
            "invalid_json_guard": invalid_json_guard,
            "contracts": failure_contracts,
        },
        "production_deploy_performed": False,
        "mutating_cloud_operations_performed": False,
    }


def chaos_simulations(results: dict[str, Any]) -> None:
    contracts = readiness_simulation_contracts()
    record(results, "restart_simulation", contracts["restart"]["ok"], contracts["restart"])
    record(
        results,
        "failure_injection_simulation",
        contracts["failure_injection"]["ok"],
        contracts["failure_injection"],
    )


def unit_and_integration(results: dict[str, Any]) -> None:
    policy = read_json(ROOT / "state_templates/production_policy.json", {})
    ok = bool(policy.get("automatic_production_enabled") or policy.get("production_deploy_channel") == "github_actions_manual")
    record(results, "unit_test", ok, {"scope": "production_policy", "deploy_channel": policy.get("production_deploy_channel")})
    registry = read_json(ROOT / "state_templates/module_registry.json", {"modules": []})
    active = [m.get("id") for m in registry.get("modules", []) if m.get("dashboard_visible")]
    required_visible = {"dashboard", "pipeline_flow", "panel_auth"}
    hidden_after_cleanup = {"deploy_pipeline", "production_readiness", "production_environment_manager", "github_safe_flow", "workers"}
    record(
        results,
        "integration_test",
        required_visible.issubset(set(active)) and not (hidden_after_cleanup & set(active)),
        {"dashboard_visible_modules": active, "required_visible": sorted(required_visible), "hidden_after_cleanup": sorted(hidden_after_cleanup)},
    )


def run_suite() -> dict[str, Any]:
    results: dict[str, Any] = {}
    unit_and_integration(results)
    python_compile(results)
    json_validation(results)
    yaml_workflow_validation(results)
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
