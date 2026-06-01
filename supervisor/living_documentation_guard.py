#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timezone

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
REPORTS = APP / "reports"
LOGS = APP / "logs"

REQUIRED = [
    "docs/LIVING_DOCUMENTATION_POLICY.md",
    "docs/AGENT_ONBOARDING_MAP.md",
    "AGENTS.md",
    "constitution/ANAYASA.md",
    "docs/HANDOVER.md",
    "docs/ROADMAP.md",
    "memory/project_memory.md",
    "state/system_state.json",
    "state/module_registry.json",
    "state/module_settings.json",
    "state/action_catalog.json",
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

missing = []

for rel in REQUIRED:
    p = APP / rel
    if not p.exists() or p.stat().st_size == 0:
        missing.append(rel)

registry = read_json(STATE / "module_registry.json", {"modules": []})
catalog = read_json(STATE / "action_catalog.json", {"actions": []})

module_ids = {m.get("id") for m in registry.get("modules", [])}
action_ids = {a.get("id") for a in catalog.get("actions", [])}

if "living_documentation_guard" not in module_ids:
    missing.append("module_registry:living_documentation_guard")

if "validate_living_documentation" not in action_ids:
    missing.append("action_catalog:validate_living_documentation")

status = "PASS" if not missing else "FAIL"
score = max(0, 100 - len(missing) * 15)
checked_at = now()

result = {
    "ok": not missing,
    "status": status,
    "score": score,
    "missing": missing,
    "checked_at": checked_at,
}

STATE.mkdir(exist_ok=True)
REPORTS.mkdir(exist_ok=True)
LOGS.mkdir(exist_ok=True)

(STATE / "living_documentation_status.json").write_text(
    json.dumps(result, indent=2, ensure_ascii=False) + "\n"
)

(REPORTS / "LIVING_DOCUMENTATION_STATUS.md").write_text(
    "# LIVING DOCUMENTATION STATUS\n\n"
    f"Tarih: {checked_at}\n\n"
    f"Status: {status}\n\n"
    f"Score: {score}\n\n"
    "Missing:\n" + "\n".join([f"- {x}" for x in missing] or ["- Yok"]) + "\n",
    encoding="utf-8"
)

with (LOGS / "system.log").open("a", encoding="utf-8") as f:
    f.write(f"{checked_at} STEP_17C living documentation validator status={status} score={score}\n")

with (LOGS / "audit.log").open("a", encoding="utf-8") as f:
    f.write(f"{checked_at} action=step_17c_living_doc_validator ok={not missing} status={status}\n")

print("LIVING_STATUS=" + status)
print("LIVING_SCORE=" + str(score))
print("MISSING_COUNT=" + str(len(missing)))
print("VALIDATOR_SCRIPT=YES")
print("STATUS_FILE=YES")
print("REPORT_FILE=YES")
