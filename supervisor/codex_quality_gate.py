#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
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
    "state/codex_execution_policy.json",
]

JSON_FILES = [
    "state/system_state.json",
    "state/module_registry.json",
    "state/module_settings.json",
    "state/action_catalog.json",
    "state/worker_profiles.json",
    "state/codex_execution_policy.json",
    "state/approval_requests.json",
    "state/approval_policy.json",
    "state/deploy_policy.json",
    "state/telegram_config.json",
]

def now():
    return datetime.now(timezone.utc).isoformat()

def read_json(path, default):
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return default

def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

def log(msg):
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "quality_gate.log").open("a", encoding="utf-8") as f:
        f.write(f"{now()} {msg}\n")

def run(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, cwd=str(APP), text=True, capture_output=True, timeout=timeout)
        return {
            "ok": p.returncode == 0,
            "returncode": p.returncode,
            "stdout": p.stdout[-5000:],
            "stderr": p.stderr[-5000:],
            "cmd": " ".join(cmd),
        }
    except Exception as exc:
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": str(exc), "cmd": " ".join(cmd)}

def preflight():
    issues = []
    warnings = []

    for rel in REQUIRED_FILES:
        if not (APP / rel).exists():
            issues.append(f"missing_required_file:{rel}")

    for rel in JSON_FILES:
        p = APP / rel
        if p.exists():
            try:
                json.loads(p.read_text())
            except Exception as exc:
                issues.append(f"invalid_json:{rel}:{exc}")

    if shutil.which("codex") is None:
        issues.append("codex_cli_not_found")

    system_state = read_json(STATE / "system_state.json", {})
    codex_policy = read_json(STATE / "codex_execution_policy.json", {})

    if system_state.get("production_deploy_enabled") is True:
        issues.append("production_deploy_unexpectedly_enabled")

    if codex_policy.get("unattended_execution_enabled") is True:
        warnings.append("codex_unattended_execution_enabled_true")

    if not (APP / ".git").exists():
        warnings.append("git_repo_missing")

    score = max(0, 100 - len(issues) * 20 - len(warnings) * 5)
    status = "PASS" if not issues else "FAIL"

    result = {
        "ok": not issues,
        "status": status,
        "score": score,
        "issues": issues,
        "warnings": warnings,
        "checked_at": now(),
    }

    write_json(STATE / "quality_gate_preflight.json", result)

    (REPORTS / "QUALITY_GATE_PREFLIGHT.md").write_text(
        "# QUALITY GATE PREFLIGHT\n\n"
        f"Tarih: {result['checked_at']}\n\n"
        f"Status: {status}\n\n"
        f"Score: {score}\n\n"
        "Issues:\n" + "\n".join([f"- {x}" for x in issues] or ["- Yok"]) + "\n\n"
        "Warnings:\n" + "\n".join([f"- {x}" for x in warnings] or ["- Yok"]) + "\n",
        encoding="utf-8"
    )

    log(f"PREFLIGHT status={status} score={score} issues={len(issues)} warnings={len(warnings)}")
    print(json.dumps(result, indent=2, ensure_ascii=False))

def test_suite():
    results = []

    commands = [
        ["python3", "-m", "compileall", "supervisor", "web_panel", "scripts"],
        ["python3", "supervisor/drift_checker.py"],
        ["python3", "supervisor/codex_quality_gate.py", "json-check"],
    ]

    for cmd in commands:
        r = run(cmd, timeout=120)
        results.append(r)

    ok = all(r["ok"] for r in results)
    status = "PASS" if ok else "FAIL"

    result = {
        "ok": ok,
        "status": status,
        "results": results,
        "checked_at": now(),
    }

    write_json(STATE / "quality_gate_tests.json", result)

    report = ["# QUALITY GATE TEST SUITE", "", f"Tarih: {result['checked_at']}", "", f"Status: {status}", ""]
    for r in results:
        report.append(f"## {r['cmd']}")
        report.append(f"- ok: {r['ok']}")
        report.append(f"- returncode: {r['returncode']}")
        if r["stdout"]:
            report.append("### stdout")
            report.append("```")
            report.append(r["stdout"][-2000:])
            report.append("```")
        if r["stderr"]:
            report.append("### stderr")
            report.append("```")
            report.append(r["stderr"][-2000:])
            report.append("```")
        report.append("")

    (REPORTS / "QUALITY_GATE_TESTS.md").write_text("\n".join(report), encoding="utf-8")
    log(f"TEST_SUITE status={status}")
    print(json.dumps(result, indent=2, ensure_ascii=False))

def json_check():
    errors = []
    for rel in JSON_FILES:
        p = APP / rel
        if p.exists():
            try:
                json.loads(p.read_text())
            except Exception as exc:
                errors.append({"file": rel, "error": str(exc)})
    result = {"ok": not errors, "errors": errors}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if errors:
        raise SystemExit(1)

def diff_report():
    if not (APP / ".git").exists():
        result = {"ok": False, "error": "git_repo_missing"}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    status = run(["git", "status", "--short"])
    diffstat = run(["git", "diff", "--stat"])
    diffname = run(["git", "diff", "--name-only"])

    result = {
        "ok": True,
        "checked_at": now(),
        "status_short": status["stdout"],
        "diff_stat": diffstat["stdout"],
        "diff_files": [x for x in diffname["stdout"].splitlines() if x.strip()],
    }

    write_json(STATE / "quality_gate_diff.json", result)

    (REPORTS / "QUALITY_GATE_DIFF.md").write_text(
        "# QUALITY GATE DIFF REPORT\n\n"
        f"Tarih: {result['checked_at']}\n\n"
        "## Git status\n"
        "```text\n" + result["status_short"] + "\n```\n\n"
        "## Diff stat\n"
        "```text\n" + result["diff_stat"] + "\n```\n\n"
        "## Changed files\n"
        + "\n".join([f"- {x}" for x in result["diff_files"]] or ["- Yok"]) + "\n",
        encoding="utf-8"
    )

    log(f"DIFF_REPORT files={len(result['diff_files'])}")
    print(json.dumps(result, indent=2, ensure_ascii=False))

def gate_status():
    pre = read_json(STATE / "quality_gate_preflight.json", {})
    tests = read_json(STATE / "quality_gate_tests.json", {})
    diff = read_json(STATE / "quality_gate_diff.json", {})
    result = {
        "ok": pre.get("ok") is True and tests.get("ok") is True,
        "preflight": pre,
        "tests": tests,
        "diff": diff,
        "checked_at": now(),
    }
    write_json(STATE / "quality_gate_status.json", result)
    print(json.dumps(result, indent=2, ensure_ascii=False))

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["preflight", "test-suite", "json-check", "diff-report", "status"])
    args = parser.parse_args()

    if args.command == "preflight":
        preflight()
    elif args.command == "test-suite":
        test_suite()
    elif args.command == "json-check":
        json_check()
    elif args.command == "diff-report":
        diff_report()
    elif args.command == "status":
        gate_status()

if __name__ == "__main__":
    main()
