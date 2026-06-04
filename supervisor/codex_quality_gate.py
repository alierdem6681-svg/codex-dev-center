#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

APP = Path(os.environ.get("CODEX_DEV_CENTER_HOME", "/opt/codex-dev-center")).resolve()
STATE = APP / "state"
REPORTS = APP / "reports"
LOGS = APP / "logs"

STANDARD_REPORT_SOURCE = "state/production_readiness_status.json"
STANDARD_REPORT_JSON = "quality-gate-report.json"
STANDARD_REPORT_SUMMARY = "quality-gate-summary.md"
RETRY_SIMULATION_REPORT_JSON = "quality-gate-retry-simulation.json"
RETRY_SIMULATION_SOURCE = "reports/" + RETRY_SIMULATION_REPORT_JSON
RETRY_SIMULATION_MAX_ATTEMPTS = 2
RETRY_SIMULATION_ATTEMPT_FIELDS = [
    "command",
    "attempt",
    "exit_code",
    "duration_seconds",
    "result",
    "failure_hint",
    "retry_changed_result",
]
RETRY_SIMULATION_COMMAND_FIELDS = [
    "name",
    "command",
    "attempt_count",
    "final_result",
    "retry_changed_result",
]

STANDARD_REPORT_GATES = {
    "lint": [
        "python_compile_check",
        "json_validation",
        "yaml_validation",
        "secret_leakage_scan",
        "forbidden_operation_scan",
    ],
    "unit_test": ["unit_test"],
    "integration_test": ["integration_test"],
    "simulation_dry_run": [
        "staging_smoke_test",
        "rollback_simulation",
        "restart_simulation",
        "failure_injection_simulation",
    ],
}

QUALITY_GATE_TEST_COMMANDS = [
    {
        "name": "python_compile_check",
        "command": ["python3", "-m", "compileall", "supervisor", "web_panel", "scripts"],
        "timeout": 120,
    },
    {
        "name": "drift_checker",
        "command": ["python3", "supervisor/drift_checker.py"],
        "timeout": 120,
    },
    {
        "name": "json_check",
        "command": ["python3", "supervisor/codex_quality_gate.py", "json-check"],
        "timeout": 120,
    },
]

QUALITY_GATE_RETRY_SIMULATION_COMMANDS = [
    {
        "name": "python_compile_check",
        "command": ["python3", "-m", "compileall", "-q", "supervisor", "web_panel", "scripts"],
        "timeout": 120,
    },
    {
        "name": "json_check",
        "command": ["python3", "supervisor/codex_quality_gate.py", "json-check"],
        "timeout": 120,
    },
    {
        "name": "unit_test",
        "command": ["python3", "-m", "unittest", "tests.test_runtime_status_model"],
        "timeout": 180,
    },
]

NON_MUTATING_FLAGS = [
    "production_deploy_performed",
    "staging_deploy_performed",
    "mutating_cloud_operations_performed",
]

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
            return json.loads(p.read_text(encoding="utf-8-sig"))
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

    for spec in QUALITY_GATE_TEST_COMMANDS:
        cmd = spec["command"]
        r = run(cmd, timeout=spec["timeout"])
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

def _missing_artifact_checks(reason):
    return [
        {
            "name": name,
            "status": "missing",
            "reason": reason,
            "artifact": STANDARD_REPORT_SOURCE,
        }
        for name in STANDARD_REPORT_GATES
    ]

def _summarize_gate_group(payload, check_name, gate_names):
    tests = payload.get("tests")
    if not isinstance(tests, dict):
        return {
            "name": check_name,
            "status": "missing",
            "reason": "missing_tests_object",
            "artifact": STANDARD_REPORT_SOURCE,
            "gates": gate_names,
        }

    missing = [name for name in gate_names if name not in tests]
    if missing:
        return {
            "name": check_name,
            "status": "missing",
            "reason": "missing_gates:" + ",".join(missing),
            "artifact": STANDARD_REPORT_SOURCE,
            "gates": gate_names,
        }

    failed = [name for name in gate_names if tests.get(name, {}).get("ok") is not True]
    if failed:
        return {
            "name": check_name,
            "status": "fail",
            "reason": "failed_gates:" + ",".join(failed),
            "artifact": STANDARD_REPORT_SOURCE,
            "gates": gate_names,
        }

    return {
        "name": check_name,
        "status": "pass",
        "reason": "all_required_gates_passed",
        "artifact": STANDARD_REPORT_SOURCE,
        "gates": gate_names,
    }

def _summarize_simulation_group(payload):
    check = _summarize_gate_group(payload, "simulation_dry_run", STANDARD_REPORT_GATES["simulation_dry_run"])
    if check["status"] != "pass":
        return check

    unsafe_flags = [name for name in NON_MUTATING_FLAGS if payload.get(name) is not False]
    if unsafe_flags:
        check["status"] = "fail"
        check["reason"] = "mutating_flags_not_false:" + ",".join(unsafe_flags)
        check["required_false_flags"] = {name: payload.get(name) for name in NON_MUTATING_FLAGS}
        return check

    check["reason"] = "dry_run_non_mutating_simulation_gates_passed"
    check["required_false_flags"] = {name: payload.get(name) for name in NON_MUTATING_FLAGS}
    return check

def _command_text(command):
    return " ".join(str(part) for part in command)

def _failure_hint(command_result):
    if command_result.get("ok"):
        return "none"

    text = " ".join(
        str(command_result.get(key) or "")
        for key in ("stderr", "stdout", "error", "failure_hint")
    ).lower()
    if "timeout" in text:
        return "timeout"
    if "syntaxerror" in text:
        return "syntax_error"
    if "modulenotfounderror" in text or "no module named" in text:
        return "missing_dependency"
    if "assertionerror" in text or "failed" in text:
        return "test_failure"
    if command_result.get("returncode") not in (0, None):
        return "nonzero_exit"
    return "execution_error"

def _retry_simulation_safety(payload):
    reasons = []
    if payload.get("dry_run") is not True:
        reasons.append("dry_run_not_true")

    required_false_flags = {name: payload.get(name) for name in NON_MUTATING_FLAGS}
    for name, value in required_false_flags.items():
        if value is not False:
            reasons.append(f"{name}_not_false")

    return {
        "safety_status": "pass" if not reasons else "fail",
        "safety_reasons": reasons,
        "required_false_flags": required_false_flags,
    }

def _run_retry_simulation_command(root, command, timeout):
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        duration = round(time.monotonic() - started, 3)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "duration_seconds": duration,
            "stdout": proc.stdout[-1000:],
            "stderr": proc.stderr[-1000:],
        }
    except subprocess.TimeoutExpired as exc:
        duration = round(time.monotonic() - started, 3)
        return {
            "ok": False,
            "returncode": 124,
            "duration_seconds": duration,
            "stdout": str(exc.stdout or "")[-1000:],
            "stderr": str(exc.stderr or "")[-1000:],
            "failure_hint": "timeout",
        }
    except Exception:
        duration = round(time.monotonic() - started, 3)
        return {
            "ok": False,
            "returncode": 1,
            "duration_seconds": duration,
            "stdout": "",
            "stderr": "",
            "failure_hint": "execution_error",
        }

def _attempt_record(command_text, attempt_number, command_result):
    result = "pass" if command_result.get("ok") else "fail"
    return {
        "command": command_text,
        "attempt": attempt_number,
        "exit_code": command_result.get("returncode"),
        "duration_seconds": float(command_result.get("duration_seconds") or 0.0),
        "result": result,
        "failure_hint": _failure_hint(command_result),
        "retry_changed_result": False,
    }

def _sanitize_retry_simulation_payload(payload):
    attempts = []
    for attempt in payload.get("attempts", []):
        if isinstance(attempt, dict):
            attempts.append({field: attempt.get(field) for field in RETRY_SIMULATION_ATTEMPT_FIELDS})

    commands = []
    for command in payload.get("commands", []):
        if isinstance(command, dict):
            commands.append({field: command.get(field) for field in RETRY_SIMULATION_COMMAND_FIELDS})

    sanitized = {
        "status": payload.get("status", "invalid"),
        "artifact": RETRY_SIMULATION_SOURCE,
        "generated_at": payload.get("generated_at"),
        "dry_run": payload.get("dry_run"),
        "non_blocking": True,
        "max_attempts": payload.get("max_attempts"),
        "attempts": attempts,
        "commands": commands,
        "flaky_commands": payload.get("flaky_commands") if isinstance(payload.get("flaky_commands"), list) else [],
        "failed_commands": payload.get("failed_commands") if isinstance(payload.get("failed_commands"), list) else [],
        "production_deploy_performed": payload.get("production_deploy_performed"),
        "staging_deploy_performed": payload.get("staging_deploy_performed"),
        "mutating_cloud_operations_performed": payload.get("mutating_cloud_operations_performed"),
    }
    sanitized.update(_retry_simulation_safety(sanitized))
    return sanitized

def build_quality_gate_retry_simulation_report(root=APP, command_specs=None, generated_at=None, runner=None):
    root = Path(root)
    command_specs = command_specs or QUALITY_GATE_RETRY_SIMULATION_COMMANDS
    generated_at = generated_at or now()
    runner = runner or _run_retry_simulation_command

    attempts = []
    commands = []
    for spec in command_specs:
        command = list(spec["command"])
        timeout = int(spec.get("timeout") or 120)
        command_text = _command_text(command)
        command_attempts = []

        first = runner(root, command, timeout)
        command_attempts.append(_attempt_record(command_text, 1, first))

        if not first.get("ok"):
            retry = runner(root, command, timeout)
            command_attempts.append(_attempt_record(command_text, 2, retry))

        retry_changed = command_attempts[0]["result"] != command_attempts[-1]["result"]
        for attempt in command_attempts:
            attempt["retry_changed_result"] = retry_changed

        final_result = command_attempts[-1]["result"]
        attempts.extend(command_attempts)
        commands.append(
            {
                "name": spec.get("name") or command_text,
                "command": command_text,
                "attempt_count": len(command_attempts),
                "final_result": final_result,
                "retry_changed_result": retry_changed,
            }
        )

    failed_commands = [item["name"] for item in commands if item["final_result"] != "pass"]
    flaky_commands = [
        item["name"]
        for item in commands
        if item["final_result"] == "pass" and item["retry_changed_result"]
    ]
    status = "pass" if not failed_commands else "fail"
    report = {
        "status": status,
        "generated_at": generated_at,
        "dry_run": True,
        "non_blocking": True,
        "max_attempts": RETRY_SIMULATION_MAX_ATTEMPTS,
        "attempts": attempts,
        "commands": commands,
        "flaky_commands": flaky_commands,
        "failed_commands": failed_commands,
        "production_deploy_performed": False,
        "staging_deploy_performed": False,
        "mutating_cloud_operations_performed": False,
    }
    report.update(_retry_simulation_safety(report))
    return report

def write_quality_gate_retry_simulation_report(root=APP, command_specs=None):
    root = Path(root)
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    report = build_quality_gate_retry_simulation_report(root, command_specs=command_specs)
    (reports / RETRY_SIMULATION_REPORT_JSON).write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report

def _read_retry_simulation_report(root):
    artifact = Path(root) / RETRY_SIMULATION_SOURCE
    if not artifact.exists():
        return {
            "status": "not_run",
            "artifact": RETRY_SIMULATION_SOURCE,
            "non_blocking": True,
            "attempts": [],
            "commands": [],
            "reason": "retry_simulation_artifact_missing",
        }
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {
            "status": "invalid",
            "artifact": RETRY_SIMULATION_SOURCE,
            "non_blocking": True,
            "attempts": [],
            "commands": [],
            "reason": "invalid_retry_simulation_json:" + str(exc),
        }
    if not isinstance(payload, dict):
        return {
            "status": "invalid",
            "artifact": RETRY_SIMULATION_SOURCE,
            "non_blocking": True,
            "attempts": [],
            "commands": [],
            "reason": "retry_simulation_payload_not_object",
        }
    return _sanitize_retry_simulation_payload(payload)

def build_standard_quality_report(root=APP, generated_at=None):
    root = Path(root)
    artifact = root / STANDARD_REPORT_SOURCE
    generated_at = generated_at or now()
    retry_simulation = _read_retry_simulation_report(root)

    if not artifact.exists():
        checks = _missing_artifact_checks("missing_artifact:" + STANDARD_REPORT_SOURCE)
        return {
            "status": "fail",
            "generated_at": generated_at,
            "source_artifacts": [STANDARD_REPORT_SOURCE],
            "checks": checks,
            "retry_simulation": retry_simulation,
            "production_deploy_performed": None,
            "staging_deploy_performed": None,
            "mutating_cloud_operations_performed": None,
        }

    try:
        payload = json.loads(artifact.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        checks = _missing_artifact_checks("invalid_json:" + str(exc))
        return {
            "status": "fail",
            "generated_at": generated_at,
            "source_artifacts": [STANDARD_REPORT_SOURCE],
            "checks": checks,
            "retry_simulation": retry_simulation,
            "production_deploy_performed": None,
            "staging_deploy_performed": None,
            "mutating_cloud_operations_performed": None,
        }

    checks = [
        _summarize_gate_group(payload, "lint", STANDARD_REPORT_GATES["lint"]),
        _summarize_gate_group(payload, "unit_test", STANDARD_REPORT_GATES["unit_test"]),
        _summarize_gate_group(payload, "integration_test", STANDARD_REPORT_GATES["integration_test"]),
        _summarize_simulation_group(payload),
    ]
    status = "pass" if all(item["status"] == "pass" for item in checks) else "fail"
    return {
        "status": status,
        "generated_at": generated_at,
        "source_artifacts": [STANDARD_REPORT_SOURCE],
        "checks": checks,
        "retry_simulation": retry_simulation,
        "production_deploy_performed": payload.get("production_deploy_performed"),
        "staging_deploy_performed": payload.get("staging_deploy_performed"),
        "mutating_cloud_operations_performed": payload.get("mutating_cloud_operations_performed"),
    }

def render_standard_quality_summary(report):
    lines = [
        "# Quality Gate Summary",
        "",
        f"Generated at: {report['generated_at']}",
        f"Status: {report['status']}",
        "",
        "## Checks",
    ]
    for check in report["checks"]:
        lines.append(f"- {check['name']}: {check['status']} - {check['reason']} ({check['artifact']})")

    retry = report.get("retry_simulation") or {}
    lines += [
        "",
        "## Retry Simulation",
        f"- Status: {retry.get('status', 'not_run')}",
        f"- Non-blocking: {str(retry.get('non_blocking', True)).lower()}",
        f"- Artifact: {retry.get('artifact', RETRY_SIMULATION_SOURCE)}",
        f"- Safety status: {retry.get('safety_status', 'not_run')}",
        f"- Safety reasons: {', '.join(retry.get('safety_reasons') or ['none'])}",
    ]
    for attempt in retry.get("attempts", []):
        lines.append(
            "- "
            + f"{attempt.get('command')} attempt {attempt.get('attempt')}: "
            + f"{attempt.get('result')} exit={attempt.get('exit_code')} "
            + f"retry_changed={str(attempt.get('retry_changed_result')).lower()} "
            + f"hint={attempt.get('failure_hint')}"
        )
    lines += [
        "",
        "## Safety",
        f"- Production deploy performed: {str(report.get('production_deploy_performed')).lower()}",
        f"- Staging deploy performed: {str(report.get('staging_deploy_performed')).lower()}",
        f"- Mutating cloud operations performed: {str(report.get('mutating_cloud_operations_performed')).lower()}",
    ]
    return "\n".join(lines) + "\n"

def write_standard_quality_report(root=APP):
    root = Path(root)
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    report = build_standard_quality_report(root)
    (reports / STANDARD_REPORT_JSON).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (reports / STANDARD_REPORT_SUMMARY).write_text(render_standard_quality_summary(report), encoding="utf-8")
    return report

def standard_report():
    result = write_standard_quality_report(APP)
    log(f"STANDARD_REPORT status={result['status']}")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "pass":
        raise SystemExit(1)

def retry_simulation():
    result = write_quality_gate_retry_simulation_report(APP)
    log(f"RETRY_SIMULATION status={result['status']} attempts={len(result['attempts'])}")
    print(json.dumps(result, indent=2, ensure_ascii=False))

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "preflight",
            "test-suite",
            "json-check",
            "diff-report",
            "status",
            "standard-report",
            "retry-simulation",
        ],
    )
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
    elif args.command == "standard-report":
        standard_report()
    elif args.command == "retry-simulation":
        retry_simulation()

if __name__ == "__main__":
    main()
