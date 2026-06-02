#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()
STATE = ROOT / "state"
REPORTS = ROOT / "reports"
SAFE_ADD_PATHS = ["AGENTS.md", "constitution", "docs", "memory", "modules", "prompts", "scripts", "state_templates", "supervisor", "web_panel", "workers", "reports"]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def find_git() -> str | None:
    found = shutil.which("git")
    if found:
        return found
    for candidate in [
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
    ]:
        if Path(candidate).exists():
            return candidate
    return None


def run_git(args: list[str], timeout: int = 120) -> dict[str, Any]:
    git = find_git()
    if not git:
        return {"ok": False, "stdout": "", "stderr": "git_not_found", "returncode": 1, "cmd": "git " + " ".join(args)}
    proc = subprocess.run([git, *args], cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
    return {"ok": proc.returncode == 0, "stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode, "cmd": "git " + " ".join(args)}


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def secret_scan() -> list[dict[str, Any]]:
    patterns = [
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
        re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    ]
    findings = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in {".git", "state", "logs", "workspaces", "backups", "tmp", "__pycache__"} for part in rel.parts):
            continue
        if path.suffix.lower() not in {".py", ".md", ".json", ".sh", ".html", ".txt", ".css", ".js"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in patterns:
                if pattern.search(line):
                    findings.append({"file": str(rel), "line": lineno, "pattern": pattern.pattern})
    return findings


def status_payload() -> dict[str, Any]:
    status = run_git(["status", "--short", "--branch"])
    branch = run_git(["branch", "--show-current"])
    remote = run_git(["remote", "-v"])
    diff_files = run_git(["diff", "--name-only"])
    diff_stat = run_git(["diff", "--stat"])
    upstream = run_git(["status", "--porcelain=v2", "--branch"])
    secrets = secret_scan()
    changed = [x for x in diff_files["stdout"].splitlines() if x.strip()]
    for line in status["stdout"].splitlines():
        if line.startswith("?? "):
            changed.append(line[3:].strip())
    changed = sorted(dict.fromkeys(changed))
    payload = {
        "ok": bool(status["ok"] and branch["ok"] and remote["ok"] and not secrets),
        "checked_at": now(),
        "git_available": bool(find_git()),
        "status_short": status["stdout"],
        "current_branch": branch["stdout"].strip(),
        "remote": remote["stdout"],
        "diff_files": changed,
        "diff_stat": diff_stat["stdout"],
        "upstream": upstream["stdout"],
        "secret_findings": secrets,
    }
    atomic_write_json(STATE / "github_safe_flow_status.json", payload)
    write_report(payload)
    return payload


def write_report(payload: dict[str, Any]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    lines = [
        "# GitHub Safe Flow Last Report",
        "",
        f"Generated at: {payload['checked_at']}",
        f"Status: {'PASS' if payload['ok'] else 'FAIL'}",
        f"Branch: {payload.get('current_branch') or '-'}",
        "",
        "## Changed Files",
    ]
    lines += [f"- {item}" for item in payload.get("diff_files", [])] or ["- Yok"]
    lines += ["", "## Secret Findings"]
    lines += [f"- {item}" for item in payload.get("secret_findings", [])] or ["- Yok"]
    (REPORTS / "github_safe_flow_last_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def commit_push(message: str) -> dict[str, Any]:
    payload = status_payload()
    if payload["secret_findings"]:
        payload["commit_push"] = {"ok": False, "reason": "secret_findings"}
        return payload
    if not payload["diff_files"]:
        payload["commit_push"] = {"ok": True, "reason": "nothing_to_commit"}
        return payload
    add_result = run_git(["add", "--", *SAFE_ADD_PATHS], timeout=120)
    commit_result = run_git(["commit", "-m", message], timeout=180)
    push_result = run_git(["push", "origin", payload["current_branch"] or "main"], timeout=300)
    verify = run_git(["status", "--short", "--branch"], timeout=120)
    head = run_git(["rev-parse", "HEAD"], timeout=60)
    payload["commit_push"] = {
        "ok": bool(add_result["ok"] and commit_result["ok"] and push_result["ok"]),
        "add": add_result,
        "commit": commit_result,
        "push": push_result,
        "verify": verify,
        "head": head["stdout"].strip(),
    }
    atomic_write_json(STATE / "github_safe_flow_status.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dry-run")
    sub.add_parser("precommit")
    commit = sub.add_parser("commit-push")
    commit.add_argument("--message", default="Add autonomous production delivery system v1")
    args = parser.parse_args()
    if args.cmd in {"dry-run", "precommit"}:
        payload = status_payload()
    else:
        payload = commit_push(args.message)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.cmd == "precommit" and payload.get("secret_findings"):
        raise SystemExit(1)
    if args.cmd == "commit-push" and not payload.get("commit_push", {}).get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
