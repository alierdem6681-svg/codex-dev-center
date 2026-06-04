#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from .read_only_execution import (
        current_execution_mode,
        read_only_write_error,
        summarize_write_status,
        write_evidence_items,
        write_json_best_effort,
        write_text_best_effort as _write_text_best_effort,
    )
except ImportError:
    from read_only_execution import (
        current_execution_mode,
        read_only_write_error,
        summarize_write_status,
        write_evidence_items,
        write_json_best_effort,
        write_text_best_effort as _write_text_best_effort,
    )

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

def write_text_best_effort(path, text, encoding="utf-8"):
    return _write_text_best_effort(path, text, encoding=encoding, root=APP, operation="write_report")

def write_json(path, data):
    return write_json_best_effort(path, data, root=APP, operation="write_state")

def log(msg):
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with (LOGS / "drift_checker.log").open("a", encoding="utf-8") as f:
            f.write(f"{now()} {msg}\n")
    except OSError:
        pass

def classify_module_registry_settings_candidates(registry, settings, catalog=None):
    modules = registry.get("modules", []) if isinstance(registry, dict) else []
    settings = settings if isinstance(settings, dict) else {}
    catalog = catalog if isinstance(catalog, dict) else {"actions": []}
    module_ids = {str(module.get("id")) for module in modules if module.get("id")}
    setting_keys = {str(key) for key in settings if key not in {"global", "updated_at"}}
    action_modules = {str(action.get("module")) for action in catalog.get("actions", []) if action.get("module")}
    candidates = []

    for module in modules:
        module_id = str(module.get("id") or "").strip()
        if not module_id:
            continue
        if module.get("settings_enabled") is True and module_id not in setting_keys:
            active_signal = module.get("status") in {"active", "contract_ready", "framework_ready_locked"}
            candidates.append(
                {
                    "candidate_id": f"missing-setting:{module_id}",
                    "module_id": module_id,
                    "setting_key": module_id,
                    "registry_key": module_id,
                    "classification": "missing_module_setting_candidate",
                    "confidence": "medium" if active_signal else "low",
                    "evidence_sources": ["module_registry"],
                    "recommended_action": "settings_proposal",
                    "reason": "settings_enabled module has no module_settings entry",
                }
            )
        if module.get("actions_enabled") is True and module_id not in action_modules:
            candidates.append(
                {
                    "candidate_id": f"missing-action-module:{module_id}",
                    "module_id": module_id,
                    "setting_key": "",
                    "registry_key": module_id,
                    "classification": "missing_registry_candidate",
                    "confidence": "low",
                    "evidence_sources": ["module_registry", "action_catalog"],
                    "recommended_action": "needs_review",
                    "reason": "actions_enabled module has no action_catalog module reference",
                }
            )

    for setting_key in sorted(setting_keys - module_ids):
        candidates.append(
            {
                "candidate_id": f"stale-setting:{setting_key}",
                "module_id": setting_key,
                "setting_key": setting_key,
                "registry_key": "",
                "classification": "stale_alert_noop",
                "confidence": "low",
                "evidence_sources": ["module_settings"],
                "recommended_action": "no_op",
                "reason": "module_settings entry is not backed by module_registry",
            }
        )
    return candidates

def run_check():
    issues = []
    warnings = []

    for rel in REQUIRED_FILES:
        if not (APP / rel).exists():
            issues.append(f"missing_required_file:{rel}")

    registry = read_json(STATE / "module_registry.json", {"modules": []})
    settings = read_json(STATE / "module_settings.json", {})
    catalog = read_json(STATE / "action_catalog.json", {"actions": []})
    drift_candidates = classify_module_registry_settings_candidates(registry, settings, catalog)

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
        "drift_candidates": drift_candidates,
        "drift_candidate_count": len(drift_candidates),
        "checked_at": now(),
        "mode": current_execution_mode(),
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
    result["write_evidence"] = write_evidence_items(result["runtime_write_status"])
    result["write_status"] = summarize_write_status(result["write_evidence"])

    log(f"DRIFT_CHECK status={status} score={score} issues={len(issues)} warnings={len(warnings)}")
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    run_check()
