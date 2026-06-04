#!/usr/bin/env python3
import errno
import json
from datetime import datetime, timezone
from pathlib import Path

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
DOCS = APP / "docs"
REPORTS = APP / "reports"
LOGS = APP / "logs"

REQUIRED_FILES = [
    "AGENTS.md",
    "constitution/ANAYASA.md",
    "docs/MODULAR_ARCHITECTURE_STANDARD.md",
    "docs/CTO_FULL_AUTHORITY_POLICY.md",
    "docs/WORKER_LIFECYCLE_POLICY.md",
    "docs/DRIFT_CONTROL_POLICY.md",
    "docs/HANDOVER.md",
    "docs/ROADMAP.md",
    "memory/project_memory.md",
    "state/system_state.json",
    "state/module_registry.json",
    "state/module_settings.json",
    "state/action_catalog.json",
    "state/worker_profiles.json",
]

def now():
    return datetime.now(timezone.utc).isoformat()

def read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default

def read_only_write_error(exc):
    return isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.EROFS

def write_text_best_effort(path, text, encoding="utf-8"):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=encoding)
        return {"ok": True, "path": str(path)}
    except OSError as exc:
        return {
            "ok": False,
            "path": str(path),
            "error": type(exc).__name__,
            "errno": getattr(exc, "errno", None),
            "read_only": read_only_write_error(exc),
        }

def write_json(path, data):
    data["updated_at"] = now()
    return write_text_best_effort(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

def log(msg):
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with (LOGS / "drift_checker.log").open("a", encoding="utf-8") as f:
            f.write(f"{now()} {msg}\n")
    except OSError:
        pass

def run_check():
    issues = []
    warnings = []

    for rel in REQUIRED_FILES:
        if not (APP / rel).exists():
            issues.append(f"missing_required_file:{rel}")

    registry = read_json(STATE / "module_registry.json", {"modules": []})
    settings = read_json(STATE / "module_settings.json", {})
    catalog = read_json(STATE / "action_catalog.json", {"actions": []})

    modules = registry.get("modules", [])
    actions = catalog.get("actions", [])

    if len(modules) < 8:
        issues.append("module_count_too_low")

    if len(actions) < 8:
        issues.append("action_count_too_low")

    for m in modules:
        mid = m.get("id")
        if not mid:
            issues.append("module_without_id")
            continue
        if m.get("dashboard_visible") is not True:
            warnings.append(f"module_not_dashboard_visible:{mid}")
        if m.get("settings_enabled") is True and mid not in settings:
            warnings.append(f"module_settings_missing_key:{mid}")

    required_modules = [
        "dashboard",
        "supervisor",
        "workers",
        "telegram",
        "codex_execution",
        "deploy_pipeline",
        "backup_recovery",
        "security_approval",
        "cto_authority",
        "modular_architecture",
        "worker_lifecycle",
        "drift_control",
    ]

    existing_ids = {m.get("id") for m in modules}
    for mid in required_modules:
        if mid not in existing_ids:
            issues.append(f"required_module_missing:{mid}")

    state = read_json(STATE / "system_state.json", {})
    if state.get("production_deploy_enabled") is True:
        issues.append("production_deploy_unexpectedly_enabled")
    if state.get("codex_unattended_execution_enabled") is True:
        issues.append("codex_unattended_unexpectedly_enabled")

    score = 100
    score -= len(issues) * 15
    score -= len(warnings) * 5
    score = max(0, score)

    status = "PASS" if not issues else "FAIL"

    result = {
        "ok": not issues,
        "status": status,
        "score": score,
        "issues": issues,
        "warnings": warnings,
        "checked_at": now(),
    }

    result["runtime_write_status"] = {
        "drift_report": write_json(STATE / "drift_report.json", result),
    }

    result["runtime_write_status"]["report"] = write_text_best_effort(
        REPORTS / "DRIFT_CHECK_REPORT.md",
        "# DRIFT CHECK REPORT\n\n"
        f"Tarih: {result['checked_at']}\n\n"
        f"Status: {status}\n\n"
        f"Score: {score}\n\n"
        "Issues:\n" + "\n".join([f"- {x}" for x in issues] or ["- Yok"]) + "\n\n"
        "Warnings:\n" + "\n".join([f"- {x}" for x in warnings] or ["- Yok"]) + "\n",
    )

    system_state = read_json(STATE / "system_state.json", {})
    system_state["drift_control_implemented"] = True
    system_state["last_drift_check_status"] = status
    system_state["last_drift_check_score"] = score
    result["runtime_write_status"]["system_state"] = write_json(STATE / "system_state.json", system_state)

    log(f"DRIFT_CHECK status={status} score={score} issues={len(issues)} warnings={len(warnings)}")
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    run_check()
