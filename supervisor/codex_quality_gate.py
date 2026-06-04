#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

APP = Path(os.environ.get("CODEX_DEV_CENTER_HOME", "/opt/codex-dev-center")).resolve()
STATE = APP / "state"
REPORTS = APP / "reports"
LOGS = APP / "logs"

STANDARD_REPORT_SOURCE = "state/production_readiness_status.json"
STANDARD_REPORT_JSON = "quality-gate-report.json"
STANDARD_REPORT_SUMMARY = "quality-gate-summary.md"

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

NON_MUTATING_FLAGS = [
    "production_deploy_performed",
    "staging_deploy_performed",
    "mutating_cloud_operations_performed",
]

SIMULATION_EVIDENCE_CONTRACTS = {
    "staging_smoke_test": {
        "mode": "dry_run_non_mutating_contract",
        "path": ["details", "contract"],
    },
    "rollback_simulation": {
        "mode": "dry_run_non_mutating_contract",
        "path": ["details", "contract"],
    },
    "restart_simulation": {
        "mode": "static_non_mutating_contract",
        "path": ["details"],
    },
    "failure_injection_simulation": {
        "mode": "static_non_mutating_contract",
        "path": ["details"],
    },
}

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

def _simulation_evidence_contracts(payload):
    tests = payload.get("tests")
    if not isinstance(tests, dict):
        return ["missing_tests_object"], {}

    evidence = {}
    failures = []

    for gate_name, expected in SIMULATION_EVIDENCE_CONTRACTS.items():
        current = tests.get(gate_name)
        if not isinstance(current, dict):
            failures.append(f"{gate_name}:missing_gate_payload")
            evidence[gate_name] = {}
            continue

        for key in expected["path"]:
            current = current.get(key) if isinstance(current, dict) else None

        if not isinstance(current, dict):
            failures.append(f"{gate_name}:missing_contract_payload")
            evidence[gate_name] = {}
            continue

        gate_evidence = {
            "mode": current.get("mode"),
            "ok": current.get("ok"),
        }
        evidence[gate_name] = gate_evidence

        if gate_evidence["ok"] is not True:
            failures.append(f"{gate_name}:contract_not_ok")
        if gate_evidence["mode"] != expected["mode"]:
            failures.append(f"{gate_name}:mode_not_{expected['mode']}")

    return failures, evidence

def _summarize_simulation_group(payload):
    check = _summarize_gate_group(payload, "simulation_dry_run", STANDARD_REPORT_GATES["simulation_dry_run"])
    if check["status"] != "pass":
        return check

    check["required_false_flags"] = {name: payload.get(name) for name in NON_MUTATING_FLAGS}
    unsafe_flags = [name for name in NON_MUTATING_FLAGS if payload.get(name) is not False]
    if unsafe_flags:
        check["status"] = "fail"
        check["reason"] = "mutating_flags_not_false:" + ",".join(unsafe_flags)
        return check

    evidence_failures, evidence = _simulation_evidence_contracts(payload)
    check["simulation_contract_evidence"] = evidence
    if evidence_failures:
        check["status"] = "fail"
        check["reason"] = "missing_simulation_contract_evidence:" + ",".join(evidence_failures)
        return check

    check["reason"] = "dry_run_non_mutating_simulation_gates_passed"
    return check

def build_standard_quality_report(root=APP, generated_at=None):
    root = Path(root)
    artifact = root / STANDARD_REPORT_SOURCE
    generated_at = generated_at or now()

    if not artifact.exists():
        checks = _missing_artifact_checks("missing_artifact:" + STANDARD_REPORT_SOURCE)
        return {
            "status": "fail",
            "generated_at": generated_at,
            "source_artifacts": [STANDARD_REPORT_SOURCE],
            "checks": checks,
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

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["preflight", "test-suite", "json-check", "diff-report", "status", "standard-report"],
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

if __name__ == "__main__":
    main()
