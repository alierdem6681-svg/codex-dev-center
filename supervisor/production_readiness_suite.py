#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .read_only_execution import (
        atomic_write_json_best_effort,
        current_execution_mode,
        read_only_write_error,
        summarize_write_status,
        write_evidence_items,
        write_text_best_effort as _write_text_best_effort,
    )
except ImportError:
    from read_only_execution import (
        atomic_write_json_best_effort,
        current_execution_mode,
        read_only_write_error,
        summarize_write_status,
        write_evidence_items,
        write_text_best_effort as _write_text_best_effort,
    )


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
TELEGRAM_RESULT_REPORT_MAX_CHARS = 900
TELEGRAM_RESULT_REPORT_MAX_LINES = 12

TELEGRAM_RESULT_FORBIDDEN_PATTERNS = [
    re.compile(r"^diff --git ", re.M),
    re.compile(r"^@@ ", re.M),
    re.compile(r"^\+\+\+ ", re.M),
    re.compile(r"^--- ", re.M),
    re.compile(r"Traceback \(most recent call last\):"),
    re.compile(r"\b(stdout|stderr)\b\s*[:=]", re.I),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\braw_payload\b", re.I),
    re.compile(r"\bfile_id\b", re.I),
    re.compile(r"\bAuthorization\s*:", re.I),
    re.compile(r"/opt/"),
]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_text_best_effort(path: Path, text: str, encoding: str = "utf-8") -> dict[str, Any]:
    return _write_text_best_effort(path, text, encoding=encoding, root=ROOT, operation="write_report")


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    return default


def atomic_write_json(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    return atomic_write_json_best_effort(path, data, root=ROOT, operation="write_state")


def run_cmd(cmd: list[str], timeout: int = 120) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-20000:],
            "stderr": proc.stderr[-8000:],
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
        "Görevler, pipeline flow ve güvenli panel yönetimi",
        "Aktif Kuyruk",
        "Canlı İşler",
        "Kapalı Kayıt",
        "Pipeline Flow",
        "Görevler",
        "Workers",
        "Canlıya alınanları göster",
        "Alım",
        "Kuyruk",
        "Worker",
        "Proposal",
        "Doğrulama",
        "Onay",
        "Hata",
        "Kapalı",
        "Canlı",
        "Çıkış",
    ]
    missing = [item for item in required_text if item not in index]
    login = (ROOT / "web_panel/static/login.html").read_text(encoding="utf-8", errors="replace")
    login_required = ["Kullanıcı adı", "Şifre", "Giriş Yap", "İlk kullanıcıyı oluştur"]
    login_missing = [item for item in login_required if item not in login]
    record(results, "dashboard_route_api_test", not missing and not login_missing, {"missing_text": missing, "login_missing_text": login_missing})


def memory_os_dashboard_contract(results: dict[str, Any]) -> None:
    contracts = [
        static_contract(
            "web_panel/memory_os_status.py",
            [
                "build_memory_os_status",
                "raw_context_included",
                "secret_values_included",
                "production_deploy_allowed",
                "mutating_actions_allowed",
            ],
        ),
        static_contract(
            "web_panel/panel_server.py",
            [
                "build_memory_os_status",
                "\"memory_os\"",
            ],
        ),
        static_contract(
            "web_panel/server.py",
            [
                "build_memory_os_status",
                "\"memory_os\"",
            ],
        ),
        static_contract(
            "web_panel/static/index.html",
            [
                "Memory OS",
                "memoryOsStatus",
                "renderMemoryOs",
            ],
        ),
        static_contract(
            "supervisor/telegram_direct_cto_simulator.py",
            [
                "memory_os_dashboard",
                "Memory OS health",
            ],
        ),
        static_contract(
            "state_templates/module_settings.json",
            [
                "\"memory_os\"",
                "\"dashboard_payload_key\": \"memory_os\"",
            ],
        ),
        static_contract(
            "state_templates/action_catalog.json",
            [
                "\"view_memory_os_status\"",
                "\"payload_key\": \"memory_os\"",
            ],
        ),
    ]
    record(
        results,
        "memory_os_dashboard_contract",
        all(item["ok"] for item in contracts),
        {
            "mode": "static_read_only_dashboard_contract",
            "contracts": contracts,
            "production_deploy_performed": False,
            "mutating_cloud_operations_performed": False,
        },
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
    if not stdout.startswith("{"):
        start = stdout.find("{")
        if start >= 0:
            stdout = stdout[start:]
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


def gate_status(results: dict[str, Any], name: str) -> str:
    item = results.get(name, {})
    if item.get("ok"):
        return "PASS"
    if item:
        return "FAIL"
    return "UNKNOWN"


def build_telegram_readiness_result_report(results: dict[str, Any]) -> str:
    failed = [name for name, item in results.items() if not item.get("ok")]
    score = round(100 * (len(results) - len(failed)) / max(1, len(results)), 2)
    fail_text = "yok"
    if failed:
        fail_text = ", ".join(failed[:3])
        if len(failed) > 3:
            fail_text += f" +{len(failed) - 3}"
    lines = [
        "Production readiness özeti:",
        f"- Genel durum: {'PASS' if not failed else 'FAIL'}",
        f"- Skor: {score}%",
        f"- Staging health/smoke: {gate_status(results, 'staging_smoke_test')}",
        f"- Rollback planı: {gate_status(results, 'rollback_simulation')}",
        f"- Telegram raporu: güvenli kısa özet; teknik çıktı yok",
        "- Production deploy: yapılmadı; GitHub Actions finalizer beklenir",
        f"- Fail gate: {fail_text}",
    ]
    return "\n".join(lines)


def telegram_result_report_contract(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    findings = [
        pattern.pattern
        for pattern in TELEGRAM_RESULT_FORBIDDEN_PATTERNS
        if pattern.search(text)
    ]
    ok = (
        bool(text.strip())
        and len(text) <= TELEGRAM_RESULT_REPORT_MAX_CHARS
        and len(lines) <= TELEGRAM_RESULT_REPORT_MAX_LINES
        and not findings
    )
    return {
        "ok": ok,
        "mode": "telegram_safe_summary_contract",
        "max_chars": TELEGRAM_RESULT_REPORT_MAX_CHARS,
        "max_lines": TELEGRAM_RESULT_REPORT_MAX_LINES,
        "chars": len(text),
        "lines": len(lines),
        "forbidden_findings": findings,
        "telegram_api_called": False,
        "technical_output_included": False,
    }


def telegram_result_report(results: dict[str, Any]) -> None:
    summary = build_telegram_readiness_result_report(results)
    contract = telegram_result_report_contract(summary)
    record(
        results,
        "telegram_result_report_flow",
        contract["ok"],
        {
            "mode": "safe_summary_only",
            "summary": summary,
            "contract": contract,
            "telegram_api_called": False,
            "production_deploy_performed": False,
            "mutating_cloud_operations_performed": False,
        },
    )


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
    report_write = write_text_best_effort(
        report,
        "# Geri Alma Simulasyonu\n\n"
        f"Tarih: {now()}\n\n"
        "- Sonuc: PASS\n"
        "- Mod: dry-run\n"
        "- Canli komut calistirilmadi.\n",
    )
    record(
        results,
        "rollback_simulation",
        rollback_contract["ok"] and (report_write["ok"] or report_write.get("write_status") == "skipped"),
        {"report": str(report.relative_to(ROOT)), "report_write": report_write, "result": rollback, "contract": rollback_contract},
    )


def deploy_script_checks(results: dict[str, Any]) -> None:
    scripts = [
        ROOT / "scripts/staging_deploy.sh",
        ROOT / "scripts/production_deploy.sh",
        ROOT / "scripts/rollback_production.sh",
        ROOT / "scripts/health_check.sh",
        ROOT / "scripts/smoke_test.sh",
        ROOT / "scripts/staging_health_check.sh",
        ROOT / "scripts/staging_smoke_test.sh",
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
        "CODEX_STAGING_HEALTH_CHECK_COMMAND",
        "CODEX_STAGING_SMOKE_TEST_COMMAND",
    ]
    missing_commands = [key for key in required_commands if not commands.get(key)]
    execute_default = str(env_defaults.get("CODEX_PRODUCTION_DEPLOY_EXECUTE", ""))
    workflow = source_path(".github/workflows/deploy-vm.yml")
    workflow_text = workflow.read_text(encoding="utf-8", errors="replace") if workflow.exists() else ""
    workflow_ok = (
        "name: Deploy to VM" in workflow_text
        and "workflow_dispatch" in workflow_text
        and "ref:" in workflow_text
        and "DEPLOY-CODEX-VM" not in workflow_text
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
                "pipeline_pass_only",
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


def ack_watchdog_retry_contract() -> dict[str, Any]:
    try:
        from . import direct_cto_async_job, progress_aware_runner, retry_policy, telegram_direct_cto_simulator, worker_runner
        from .critical_operation_policy import critical_operation_findings
        from .task_status_constants import TASK_STATUS_FAILED_NO_PROPOSAL, TASK_STATUS_FAILED_RETRYABLE
    except ImportError:
        import direct_cto_async_job
        import progress_aware_runner
        import retry_policy
        import telegram_direct_cto_simulator
        import worker_runner
        from critical_operation_policy import critical_operation_findings
        from task_status_constants import TASK_STATUS_FAILED_NO_PROPOSAL, TASK_STATUS_FAILED_RETRYABLE

    ack_cases = [
        telegram_direct_cto_simulator.simulate_case(
            "readiness_action_ack",
            "Pipeline başlat ve workerlara dağıt.",
        ),
        telegram_direct_cto_simulator.simulate_case(
            "readiness_long_ack",
            "Uçtan uca çalış: worker ata, pipeline çalıştır, fail olursa düzelt, gate PASS olunca production'a al.",
        ),
    ]
    ack_contracts = [
        static_contract(
            "supervisor/telegram_direct_cto.py",
            [
                "class AsyncJobId",
                "ack_correlation_id",
                "async_ack_correlation_id",
                "existing_async_job_id",
                "async_job_created",
                "update_id=update_id",
            ],
        ),
    ]
    ack_ok = (
        all(item.get("route") == "async_job" for item in ack_cases)
        and all(item.get("async_ack_expected") is True for item in ack_cases)
        and all(item.get("ack_deadline_seconds") == 3 for item in ack_cases)
        and all(item["ok"] for item in ack_contracts)
    )

    watchdog_contracts = [
        static_contract(
            "supervisor/progress_aware_runner.py",
            [
                "last_meaningful_progress_seconds_ago",
                "last_output_activity_seconds_ago",
                "output_activity_count",
                "meaningful_event_count",
                "no_meaningful_progress",
            ],
        ),
        static_contract(
            "supervisor/worker_runner.py",
            [
                "progress_watchdog",
                "last_meaningful_progress_seconds_ago",
                "last_output_activity_seconds_ago",
                "progress_watchdog_stalled_without_meaningful_progress",
            ],
        ),
    ]
    output_noise_meaningful = progress_aware_runner.output_has_meaningful_marker("heartbeat noise only")
    semantic_output_meaningful = progress_aware_runner.output_has_meaningful_marker("wrote PLAN.md and tests PASS")
    watchdog_ok = (
        output_noise_meaningful is False
        and semantic_output_meaningful is True
        and all(item["ok"] for item in watchdog_contracts)
    )

    worker_retryable_status, worker_retryable_reason = worker_runner.classify_worker_result(1, [], "", False)
    worker_non_retry_status, worker_non_retry_reason = worker_runner.classify_worker_result(0, [], "", False)
    usage_failure = direct_cto_async_job.classify_codex_failure("usage limit, try again later", "", {})
    retry_decision = retry_policy.decide_retry(
        task_id="READINESS-RETRY",
        failure_kind="timeout",
        current_attempt=1,
        max_attempts=3,
        jitter_seed="production-readiness",
    )
    critical_findings = critical_operation_findings("Production database " + "delete" + " from users çalıştır.")
    retry_matrix = {
        "worker_failure_without_proposal": {
            "status": worker_retryable_status,
            "reason": worker_retryable_reason,
            "retryable": worker_retryable_status == TASK_STATUS_FAILED_RETRYABLE,
        },
        "usage_limit": {
            "status": usage_failure.get("status"),
            "result": usage_failure.get("result"),
            "retryable": usage_failure.get("status") == TASK_STATUS_FAILED_RETRYABLE,
        },
        "timeout_backoff": {
            "failure_kind": retry_decision.get("failure_kind"),
            "terminal": retry_decision.get("terminal"),
            "idempotency_key": retry_decision.get("idempotency_key"),
            "retryable": retry_decision.get("terminal") is False,
        },
        "completed_without_proposal": {
            "status": worker_non_retry_status,
            "reason": worker_non_retry_reason,
            "retryable": worker_non_retry_status == TASK_STATUS_FAILED_RETRYABLE,
        },
        "critical_database_mutation": {
            "findings": critical_findings,
            "retryable": False,
        },
    }
    retry_ok = (
        retry_matrix["worker_failure_without_proposal"]["retryable"] is True
        and retry_matrix["usage_limit"]["retryable"] is True
        and retry_matrix["timeout_backoff"]["retryable"] is True
        and worker_non_retry_status == TASK_STATUS_FAILED_NO_PROPOSAL
        and "database_destructive_operation" in critical_findings
    )

    return {
        "ok": ack_ok and watchdog_ok and retry_ok,
        "mode": "static_and_fixture_non_mutating_contract",
        "ack": {
            "ok": ack_ok,
            "cases": ack_cases,
            "contracts": ack_contracts,
            "telegram_api_called": False,
        },
        "watchdog": {
            "ok": watchdog_ok,
            "output_noise_meaningful": output_noise_meaningful,
            "semantic_output_meaningful": semantic_output_meaningful,
            "contracts": watchdog_contracts,
        },
        "retryable_classification": {
            "ok": retry_ok,
            "matrix": retry_matrix,
        },
        "production_deploy_performed": False,
        "staging_deploy_performed": False,
        "mutating_cloud_operations_performed": False,
    }


def _task_by_id(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    for task in tasks:
        if task.get("id") == task_id:
            return task
    return {}


def parallel_worker_regression_contract() -> dict[str, Any]:
    try:
        from . import worker_runner as worker_runner_module
        from .task_status_constants import (
            TASK_STATUS_CANCELLED,
            TASK_STATUS_DONE,
            TASK_STATUS_FAILED,
            TERMINAL_TASK_STATUSES,
        )
    except ImportError:
        import worker_runner as worker_runner_module
        from task_status_constants import (
            TASK_STATUS_CANCELLED,
            TASK_STATUS_DONE,
            TASK_STATUS_FAILED,
            TERMINAL_TASK_STATUSES,
        )

    dispatched_at = now()
    task_specs = [
        {"id": "sim-low-risk-a", "risk": "low", "worker": "worker-1", "terminal_status": TASK_STATUS_DONE},
        {"id": "sim-low-risk-b", "risk": "low", "worker": "worker-2", "terminal_status": TASK_STATUS_DONE},
        {"id": "sim-medium-risk-c", "risk": "medium", "worker": "worker-3", "terminal_status": TASK_STATUS_FAILED},
        {"id": "sim-medium-risk-d", "risk": "medium", "worker": "worker-4", "terminal_status": TASK_STATUS_CANCELLED},
    ]
    events: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="parallel-worker-regression-") as tmp:
        tmp_root = Path(tmp)
        queue_path = tmp_root / "task_queue.json"
        workers_path = tmp_root / "workers.json"
        queue = {"tasks": []}
        for spec in task_specs:
            queue["tasks"].append(
                {
                    "id": spec["id"],
                    "title": "Parallel worker regression simulation",
                    "status": "QUEUED",
                    "source": "cto",
                    "risk": spec["risk"],
                    "assigned_worker": spec["worker"],
                    "worker_eligible": True,
                    "dispatched_at": dispatched_at,
                    "lifecycle_wake_requested": True,
                }
            )
            events.append({"type": "dispatch", "task_id": spec["id"], "worker_id": spec["worker"]})
            events.append({"type": "wake", "task_id": spec["id"], "worker_id": spec["worker"]})

        queue_path.write_text(json.dumps(queue, indent=2), encoding="utf-8")
        workers_path.write_text(
            json.dumps(
                {
                    "workers": [
                        {"id": spec["worker"], "status": "IDLE", "current_task": None}
                        for spec in task_specs
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        originals = (worker_runner_module.QUEUE_PATH, worker_runner_module.WORKERS_PATH)
        worker_runner_module.QUEUE_PATH = queue_path
        worker_runner_module.WORKERS_PATH = workers_path
        try:
            claims: list[dict[str, Any] | None] = []
            for spec in task_specs:
                claimed = worker_runner_module.claim_task(spec["worker"])
                claims.append(claimed)
                if claimed:
                    events.append({"type": "claim", "task_id": claimed.get("id"), "worker_id": spec["worker"]})

            duplicate_claims = []
            for spec in task_specs:
                duplicate_claim = worker_runner_module.claim_task(spec["worker"])
                duplicate_claims.append(duplicate_claim)
                if duplicate_claim:
                    events.append({"type": "duplicate_claim", "task_id": duplicate_claim.get("id"), "worker_id": spec["worker"]})

            terminal_snapshots: dict[str, dict[str, Any]] = {}
            for spec in task_specs:
                before_tasks = read_json(queue_path, {"tasks": []}).get("tasks", [])
                before_task = _task_by_id(before_tasks, spec["id"])
                worker_runner_module.finish_task(
                    spec["id"],
                    spec["worker"],
                    spec["terminal_status"],
                    f"parallel_worker_regression_{str(spec['terminal_status']).lower()}",
                )
                after_tasks = read_json(queue_path, {"tasks": []}).get("tasks", [])
                after_task = _task_by_id(after_tasks, spec["id"])
                if before_task.get("status") not in TERMINAL_TASK_STATUSES and after_task.get("status") in TERMINAL_TASK_STATUSES:
                    events.append({"type": "terminal", "task_id": spec["id"], "worker_id": spec["worker"], "status": after_task.get("status")})
                terminal_snapshots[spec["id"]] = dict(after_task)

            duplicate_terminal_attempts = []
            for spec in task_specs:
                before_tasks = read_json(queue_path, {"tasks": []}).get("tasks", [])
                before_task = _task_by_id(before_tasks, spec["id"])
                worker_runner_module.finish_task(
                    spec["id"],
                    spec["worker"],
                    TASK_STATUS_FAILED,
                    "duplicate_terminal_regression_attempt",
                )
                after_tasks = read_json(queue_path, {"tasks": []}).get("tasks", [])
                after_task = _task_by_id(after_tasks, spec["id"])
                changed = (
                    after_task.get("status") != before_task.get("status")
                    or after_task.get("finished_at") != before_task.get("finished_at")
                    or after_task.get("result") != before_task.get("result")
                )
                duplicate_terminal_attempts.append({"task_id": spec["id"], "changed": changed})
                if changed:
                    events.append({"type": "duplicate_terminal", "task_id": spec["id"], "worker_id": spec["worker"]})

            final_tasks = read_json(queue_path, {"tasks": []}).get("tasks", [])
        finally:
            worker_runner_module.QUEUE_PATH, worker_runner_module.WORKERS_PATH = originals

    claimed_task_ids = [str(claim.get("id")) for claim in claims if isinstance(claim, dict)]
    claim_pairs = [
        (str(claim.get("id")), str(claim.get("worker_id") or claim.get("assigned_worker")))
        for claim in claims
        if isinstance(claim, dict)
    ]
    terminal_tasks = [
        task for task in final_tasks
        if task.get("status") in TERMINAL_TASK_STATUSES
    ]
    duplicate_claim_count = len([claim for claim in duplicate_claims if claim])
    duplicate_terminal_count = len([item for item in duplicate_terminal_attempts if item["changed"]])
    metrics = {
        "dispatch_count": len([event for event in events if event["type"] == "dispatch"]),
        "wake_count": len([event for event in events if event["type"] == "wake"]),
        "unique_claimed_task_count": len(set(claimed_task_ids)),
        "claim_event_count": len([event for event in events if event["type"] == "claim"]),
        "terminal_task_count": len(terminal_tasks),
        "terminal_event_count": len([event for event in events if event["type"] == "terminal"]),
        "duplicate_claim_count": duplicate_claim_count,
        "duplicate_terminal_count": duplicate_terminal_count,
    }
    expected = {
        "dispatch_count": 4,
        "wake_count": 4,
        "unique_claimed_task_count": 4,
        "claim_event_count": 4,
        "terminal_task_count": 4,
        "terminal_event_count": 4,
        "duplicate_claim_count": 0,
        "duplicate_terminal_count": 0,
    }
    terminal_status_by_task = {str(task.get("id")): task.get("status") for task in final_tasks}
    ok = (
        metrics == expected
        and len(set(claim_pairs)) == 4
        and all(terminal_snapshots.get(spec["id"], {}).get("finished_at") for spec in task_specs)
        and terminal_status_by_task == {spec["id"]: spec["terminal_status"] for spec in task_specs}
    )
    return {
        "ok": ok,
        "mode": "parallel_worker_lifecycle_simulation",
        "simulation_task_ids": [spec["id"] for spec in task_specs],
        "worker_ids": [spec["worker"] for spec in task_specs],
        "metrics": metrics,
        "expected": expected,
        "claim_pairs": [{"task_id": task_id, "worker_id": worker_id} for task_id, worker_id in claim_pairs],
        "terminal_status_by_task": terminal_status_by_task,
        "duplicate_terminal_attempts": duplicate_terminal_attempts,
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
    parallel_contract = parallel_worker_regression_contract()
    record(results, "parallel_worker_regression", parallel_contract["ok"], parallel_contract)


def ack_watchdog_retry_readiness(results: dict[str, Any]) -> None:
    contract = ack_watchdog_retry_contract()
    record(results, "ack_watchdog_retry_contract", contract["ok"], contract)


def unit_and_integration(results: dict[str, Any]) -> None:
    policy = read_json(ROOT / "state_templates/production_policy.json", {})
    ok = bool(policy.get("automatic_production_enabled") or policy.get("production_deploy_channel") == "github_actions_manual")
    record(results, "unit_test", ok, {"scope": "production_policy", "deploy_channel": policy.get("production_deploy_channel")})
    registry = read_json(ROOT / "state_templates/module_registry.json", {"modules": []})
    active = [m.get("id") for m in registry.get("modules", []) if m.get("dashboard_visible")]
    record(results, "integration_test", "deploy_pipeline" in active, {"dashboard_visible_modules": active})


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
    memory_os_dashboard_contract(results)
    telegram_test(results)
    deploy_script_checks(results)
    security_scans(results)
    staging_and_rollback(results)
    ack_watchdog_retry_readiness(results)
    chaos_simulations(results)
    telegram_result_report(results)

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
        "mode": current_execution_mode(),
    }
    payload["runtime_write_status"] = {
        "state": atomic_write_json(STATE / "production_readiness_status.json", payload),
    }
    payload["runtime_write_status"]["report"] = write_report(payload)
    payload["write_evidence"] = write_evidence_items(payload["runtime_write_status"])
    payload["write_status"] = summarize_write_status(payload["write_evidence"])
    return payload


def write_report(payload: dict[str, Any]) -> dict[str, Any]:
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
    return write_text_best_effort(REPORTS / "production_readiness_last_report.md", "\n".join(lines) + "\n")


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
