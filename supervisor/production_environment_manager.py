#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .read_only_execution import (
        atomic_write_json_best_effort,
        summarize_write_status,
        write_evidence_items,
        write_text_best_effort,
    )
except ImportError:
    from read_only_execution import (
        atomic_write_json_best_effort,
        summarize_write_status,
        write_evidence_items,
        write_text_best_effort,
    )


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()
DEFAULT_SOURCE_ROOT = Path("/home/alierdem6681/codex-dev-center-github-export")
SOURCE_ROOT = Path(os.environ.get("CODEX_DEV_CENTER_SOURCE", DEFAULT_SOURCE_ROOT)).resolve()
STATE = ROOT / "state"
REPORTS = ROOT / "reports"
LOGS = ROOT / "logs"

PRODUCTION_PORT = int(os.environ.get("CODEX_PRODUCTION_PANEL_PORT", "8080"))
STAGING_PORT = int(os.environ.get("CODEX_STAGING_PANEL_PORT", "18080"))

DEFAULT_COMMANDS = {
    "CODEX_STAGING_DEPLOY_COMMAND": "{python} supervisor/production_environment_manager.py staging-deploy",
    "CODEX_PRODUCTION_DEPLOY_COMMAND": "{python} supervisor/production_environment_manager.py production-deploy",
    "CODEX_ROLLBACK_COMMAND": "{python} supervisor/production_environment_manager.py rollback",
    "CODEX_HEALTH_CHECK_COMMAND": "{python} supervisor/production_environment_manager.py health-check --scope production",
    "CODEX_SMOKE_TEST_COMMAND": "{python} supervisor/production_environment_manager.py smoke-test --scope production",
}

CRITICAL_EXCEPTION_TERMS = [
    "secret value",
    "token value",
    "private key",
    "env change",
    "iam owner",
    "iam editor",
    "iam ",
    "billing",
    "drop table",
    "truncate table",
    "delete from",
    "database delete",
    "dns",
    "firewall",
    "google ads mutate",
]

ALLOWED_RUNTIME_DIRTY_PREFIXES = [
    "reports/",
    "state/",
    "logs/",
]


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
    return atomic_write_json_best_effort(path, data, root=ROOT, operation="write_state")


def command_root() -> Path:
    if (SOURCE_ROOT / ".git").exists():
        return SOURCE_ROOT
    return ROOT


def run(args: list[str], timeout: int = 120, env: dict[str, str] | None = None, cwd: Path | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(args, cwd=str(cwd or ROOT), text=True, capture_output=True, timeout=timeout, env=env)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "cmd": " ".join(args),
        }
    except Exception as exc:
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": str(exc), "cmd": " ".join(args)}


def git_bin() -> str | None:
    candidates = [
        os.environ.get("CODEX_GIT", ""),
        shutil.which("git") or "",
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def powershell_bin() -> str | None:
    return shutil.which("powershell") or shutil.which("powershell.exe")


def automation_headers() -> dict[str, str]:
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from web_panel import auth as panel_auth

        return {"Cookie": panel_auth.automation_cookie_header()}
    except Exception:
        return {}


def deploy_policy() -> dict[str, Any]:
    policy = read_json(ROOT / "state_templates/deploy_policy.json", {})
    production = read_json(ROOT / "state_templates/production_policy.json", {})
    env_defaults = policy.get("environment_defaults", {}) if isinstance(policy, dict) else {}
    commands = policy.get("commands", {}) if isinstance(policy, dict) else {}
    merged = {
        **DEFAULT_COMMANDS,
        **{k: v for k, v in commands.items() if isinstance(v, str) and v.strip()},
        **{k: v for k, v in env_defaults.items() if isinstance(v, str) and k in DEFAULT_COMMANDS},
    }
    return {"deploy_policy": policy, "production_policy": production, "commands": merged}


def deploy_channel() -> str:
    policy = deploy_policy()["deploy_policy"]
    return str(policy.get("production_deploy_channel", "local_controller"))


def github_actions_context() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def truthy(value: Any) -> bool:
    return value is True or str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def local_deploy_fallback_enabled() -> bool:
    if truthy(os.environ.get("CODEX_LOCAL_DEPLOY_FALLBACK")):
        return True
    policies = deploy_policy()
    deploy = policies["deploy_policy"]
    production = policies["production_policy"]
    return bool(
        truthy(deploy.get("local_vm_deploy_fallback_enabled"))
        or truthy(production.get("local_vm_deploy_fallback_enabled"))
    )


def local_deploy_fallback_context() -> bool:
    actor = os.environ.get("CODEX_DEPLOY_ACTOR", "").strip()
    return bool(truthy(os.environ.get("CODEX_LOCAL_DEPLOY_FALLBACK")) or actor == "cto_finalizer")


def github_actions_local_fallback_allowed() -> bool:
    return bool(local_deploy_fallback_enabled() and local_deploy_fallback_context())


def source_sync_excludes() -> list[str]:
    return [
        ".git/",
        ".env",
        "*.pem",
        "*.key",
        "__pycache__/",
        ".pytest_cache/",
        "state/",
        "logs/",
        "reports/",
        "archives/",
        "workspaces/",
        "tmp/",
    ]


def create_runtime_code_backup() -> dict[str, Any]:
    archives = ROOT / "archives" / "production_code_backups"
    archives.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = archives / f"runtime_code_{stamp}.tar.gz"
    tar = shutil.which("tar")
    if not tar:
        return {"ok": False, "reason": "tar_not_found", "path": str(target)}
    args = [tar]
    for item in source_sync_excludes():
        args.append(f"--exclude={item.rstrip('/')}")
    args += ["-czf", str(target), "-C", str(ROOT), "."]
    result = run(args, timeout=300, cwd=ROOT)
    return {"ok": bool(result.get("ok")), "path": str(target), "result": result}


def sync_source_to_runtime() -> dict[str, Any]:
    if SOURCE_ROOT == ROOT:
        return {"ok": True, "skipped": True, "reason": "source_is_runtime", "source": str(SOURCE_ROOT), "runtime": str(ROOT)}
    if not (SOURCE_ROOT / ".git").exists():
        return {"ok": False, "reason": "source_git_root_not_found", "source": str(SOURCE_ROOT), "runtime": str(ROOT)}
    backup: dict[str, Any] = {"ok": True, "skipped": True, "reason": "backup_not_required_by_policy"}
    policies = deploy_policy()
    if truthy(policies["deploy_policy"].get("local_vm_deploy_fallback_requires_backup")) or truthy(
        policies["production_policy"].get("local_vm_deploy_fallback_requires_backup")
    ):
        backup = create_runtime_code_backup()
        if not backup.get("ok"):
            return {"ok": False, "reason": "runtime_code_backup_failed", "backup": backup}
    rsync = shutil.which("rsync")
    if not rsync:
        return {"ok": False, "reason": "rsync_not_found", "backup": backup}
    args = [rsync, "-a", "--delete"]
    for item in source_sync_excludes():
        args.append(f"--exclude={item}")
    args += [str(SOURCE_ROOT) + "/", str(ROOT) + "/"]
    result = run(args, timeout=300, cwd=SOURCE_ROOT)
    head = git_status().get("head", "")
    if result.get("ok") and head:
        (ROOT / ".production_commit").write_text(head + "\n", encoding="utf-8")
        update_runtime_commit_markers(head)
    return {
        "ok": bool(result.get("ok")),
        "source": str(SOURCE_ROOT),
        "runtime": str(ROOT),
        "backup": backup,
        "head": head,
        "result": result,
    }


def git_origin_main_head() -> str:
    git = git_bin()
    if not git:
        return ""
    result = run([git, "rev-parse", "origin/main"], 30, cwd=command_root())
    if result.get("ok"):
        return result.get("stdout", "").strip()
    return ""


def update_runtime_commit_markers(head: str, origin_head: str | None = None) -> None:
    head = str(head or "").strip()
    if not head:
        return
    origin = str(origin_head or git_origin_main_head() or head).strip()
    state_path = STATE / "system_state.json"
    state = read_json(state_path, {})
    if not isinstance(state, dict):
        state = {}
    state.update(
        {
            "production_running_commit": head,
            "github_origin_main_commit": origin,
            "production_github_sync": bool(origin and origin == head),
        }
    )
    atomic_write_json(state_path, state)


def configured_commands() -> dict[str, Any]:
    policy = deploy_policy()
    commands = {}
    for key, default_value in policy["commands"].items():
        value = os.environ.get(key, "").strip() or default_value
        commands[key] = {
            "configured": bool(value),
            "source": "environment" if os.environ.get(key, "").strip() else "policy_default",
            "command": value,
        }
    execute = os.environ.get("CODEX_PRODUCTION_DEPLOY_EXECUTE", "").strip()
    if not execute:
        env_defaults = policy["deploy_policy"].get("environment_defaults", {})
        execute = str(env_defaults.get("CODEX_PRODUCTION_DEPLOY_EXECUTE", "1"))
    return {
        "commands": commands,
        "CODEX_PRODUCTION_DEPLOY_EXECUTE": {
            "configured": execute == "1",
            "source": "environment" if os.environ.get("CODEX_PRODUCTION_DEPLOY_EXECUTE", "").strip() else "policy_default",
            "value": "1" if execute == "1" else "0",
        },
    }


def command_text(name: str) -> str:
    return str(configured_commands()["commands"].get(name, {}).get("command", "")).strip()


def critical_exception_scan(extra_text: str = "") -> dict[str, Any]:
    commands = configured_commands()["commands"]
    text = " ".join([item.get("command", "") for item in commands.values()] + [extra_text]).lower()
    matched = [term for term in CRITICAL_EXCEPTION_TERMS if term in text]
    return {"ok": not matched, "matched_terms": matched, "requires_risk_report": bool(matched)}


def git_status() -> dict[str, Any]:
    git = git_bin()
    if not git:
        return {"ok": False, "git_available": False, "reason": "git_not_found", "blocking_dirty_files": []}
    git_root = command_root()
    branch = run([git, "rev-parse", "--abbrev-ref", "HEAD"], 30, cwd=git_root)
    head = run([git, "rev-parse", "HEAD"], 30, cwd=git_root)
    status = run([git, "status", "--porcelain"], 30, cwd=git_root)
    dirty_lines = [line for line in status.get("stdout", "").splitlines() if line.strip()]
    dirty_files = []
    blocking = []
    for line in dirty_lines:
        rel = line[3:].strip() if len(line) > 3 else line.strip()
        rel = rel.replace("\\", "/")
        dirty_files.append(rel)
        if not any(rel.startswith(prefix) for prefix in ALLOWED_RUNTIME_DIRTY_PREFIXES):
            blocking.append(rel)
    return {
        "ok": bool(branch["ok"] and head["ok"] and status["ok"]),
        "git_available": True,
        "worktree": str(git_root),
        "runtime_root": str(ROOT),
        "runtime_is_deploy_output": git_root != ROOT,
        "branch": branch.get("stdout", "").strip(),
        "head": head.get("stdout", "").strip(),
        "dirty_files": dirty_files,
        "blocking_dirty_files": blocking,
        "clean_for_deploy": not blocking,
    }


def remote_sync() -> dict[str, Any]:
    git = git_bin()
    status = git_status()
    if not git or not status.get("ok"):
        return {"ok": False, "reason": "git_status_unavailable", "git_status": status}
    branch = status.get("branch") or "main"
    remote = run([git, "ls-remote", "origin", f"refs/heads/{branch}"], 60, cwd=command_root())
    remote_hash = ""
    if remote["ok"] and remote["stdout"].strip():
        remote_hash = remote["stdout"].split()[0]
    return {
        "ok": bool(remote["ok"] and remote_hash and remote_hash == status.get("head")),
        "branch": branch,
        "head": status.get("head"),
        "origin_head": remote_hash,
        "remote_result": remote,
    }


def http_json(port: int, path: str, timeout: int = 5) -> dict[str, Any]:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request("GET", path, headers=automation_headers())
        response = conn.getresponse()
        body = response.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body[:2000]}
        return {"ok": response.status < 400, "status": response.status, "body": parsed}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": str(exc)}


def http_text(port: int, path: str, timeout: int = 5) -> dict[str, Any]:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request("GET", path, headers=automation_headers())
        response = conn.getresponse()
        body = response.read().decode("utf-8", errors="replace")
        return {"ok": response.status < 400, "status": response.status, "body": body[:120000]}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": str(exc), "body": ""}


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def windows_port_pids(port: int) -> list[int]:
    ps = powershell_bin()
    if os.name != "nt" or not ps:
        return []
    script = f"Get-NetTCPConnection -LocalPort {port} -State Listen | Select-Object -ExpandProperty OwningProcess"
    result = run([ps, "-NoProfile", "-Command", script], 20)
    pids: list[int] = []
    for line in result.get("stdout", "").splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return sorted(set(pids))


def process_command_line(pid: int) -> str:
    ps = powershell_bin()
    if os.name != "nt" or not ps:
        return ""
    script = f"$p={pid}; (Get-CimInstance Win32_Process -Filter \"ProcessId=$p\").CommandLine"
    result = run([ps, "-NoProfile", "-Command", script], 20)
    return result.get("stdout", "").strip()


def stop_port(port: int) -> dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "reason": "stop_port_only_implemented_for_windows", "port": port}
    stopped = []
    errors = []
    for pid in windows_port_pids(port):
        if pid == os.getpid():
            continue
        result = run(["taskkill", "/PID", str(pid), "/F"], 30)
        if result["ok"]:
            stopped.append(pid)
        else:
            errors.append({"pid": pid, "result": result})
    return {"ok": not errors, "stopped_pids": stopped, "errors": errors, "port": port}


def wait_health(port: int, timeout_seconds: int = 20) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {"ok": False, "error": "not_checked"}
    while time.time() < deadline:
        last = http_json(port, "/health")
        if last.get("ok"):
            return last
        time.sleep(0.5)
    return last


def start_panel(port: int, scope: str, host: str = "127.0.0.1") -> dict[str, Any]:
    LOGS.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CODEX_DEV_CENTER_HOME"] = str(ROOT)
    env["CODEX_PANEL_PORT"] = str(port)
    env["CODEX_PANEL_HOST"] = host
    env["CODEX_PANEL_SCOPE"] = scope
    stdout = (LOGS / f"panel_{scope}_{port}.out.log").open("ab")
    stderr = (LOGS / f"panel_{scope}_{port}.err.log").open("ab")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    proc = subprocess.Popen(
        [sys.executable, "web_panel/panel_server.py"],
        cwd=str(ROOT),
        env=env,
        stdout=stdout,
        stderr=stderr,
        creationflags=flags,
    )
    health = wait_health(port, 20)
    return {"ok": bool(health.get("ok")), "pid": proc.pid, "port": port, "scope": scope, "health": health}


def panel_identity(port: int) -> dict[str, Any]:
    health = http_json(port, "/health")
    body = health.get("body", {}) if isinstance(health.get("body"), dict) else {}
    return {
        "ok": bool(health.get("ok")),
        "port": port,
        "root": body.get("root"),
        "scope": body.get("scope"),
        "version": body.get("version"),
        "matches_repo": body.get("root") == str(ROOT),
        "pids": windows_port_pids(port),
        "commands": [process_command_line(pid) for pid in windows_port_pids(port)],
    }


def ensure_panel(port: int, scope: str, host: str = "127.0.0.1", replace_mismatch: bool = False) -> dict[str, Any]:
    identity = panel_identity(port) if port_open(port) else {"ok": False, "port": port, "matches_repo": False}
    if identity.get("ok") and (identity.get("matches_repo") or not replace_mismatch):
        return {"ok": True, "action": "reused", "identity": identity}
    stopped: dict[str, Any] = {"ok": True, "stopped_pids": []}
    if port_open(port):
        stopped = stop_port(port)
        time.sleep(1)
    started = start_panel(port, scope, host)
    return {"ok": bool(started.get("ok")), "action": "started", "previous": identity, "stopped": stopped, "started": started}


def service_discovery() -> dict[str, Any]:
    return {
        "systemd_available": shutil.which("systemctl") is not None,
        "production_panel": panel_identity(PRODUCTION_PORT) if port_open(PRODUCTION_PORT) else {"ok": False, "port": PRODUCTION_PORT},
        "staging_panel": panel_identity(STAGING_PORT) if port_open(STAGING_PORT) else {"ok": False, "port": STAGING_PORT},
        "production_port": PRODUCTION_PORT,
        "staging_port": STAGING_PORT,
    }


def status_api_auth_required(status: dict[str, Any]) -> bool:
    body = status.get("body") if isinstance(status.get("body"), dict) else {}
    return int(status.get("status") or 0) == 401 and bool(body.get("login"))


def health_check(scope: str = "production") -> dict[str, Any]:
    port = STAGING_PORT if scope == "staging" else PRODUCTION_PORT
    required = [
        ROOT / "web_panel/panel_server.py",
        ROOT / "web_panel/static/index.html",
        ROOT / "supervisor/production_environment_manager.py",
        ROOT / "supervisor/production_deploy_controller.py",
    ]
    health = http_json(port, "/health")
    status = http_json(port, "/api/status") if health.get("ok") else {"ok": False, "reason": "health_failed"}
    status_ok = bool(status.get("ok") or status_api_auth_required(status))
    payload = {
        "ok": bool(health.get("ok") and status_ok and all(path.exists() for path in required)),
        "scope": scope,
        "port": port,
        "checked_at": now(),
        "required_files_missing": [str(path.relative_to(ROOT)) for path in required if not path.exists()],
        "health": health,
        "status_api": {
            "ok": status_ok,
            "raw_ok": status.get("ok"),
            "status": status.get("status"),
            "auth_required": status_api_auth_required(status),
            "keys": sorted((status.get("body") or {}).keys()) if isinstance(status.get("body"), dict) else [],
        },
        "services": service_discovery(),
    }
    payload["runtime_write_status"] = {
        f"{scope}_health_state": atomic_write_json(STATE / f"{scope}_health_check_status.json", payload),
        "last_health_state": atomic_write_json(STATE / "last_health_check_status.json", payload),
    }
    payload["runtime_write_status"]["report"] = write_environment_report("health_check", payload)
    payload["write_evidence"] = write_evidence_items(payload["runtime_write_status"])
    payload["write_status"] = summarize_write_status(payload["write_evidence"])
    return payload


def smoke_test(scope: str = "production") -> dict[str, Any]:
    port = STAGING_PORT if scope == "staging" else PRODUCTION_PORT
    health = health_check(scope)
    status = http_json(port, "/api/status")
    index = http_text(port, "/")
    body = status.get("body") if isinstance(status.get("body"), dict) else {}
    body_text = index.get("body", "")
    auth_required = status_api_auth_required(status)
    labels = [
        "Pipeline Flow",
        "Görevler",
        "Canlıya alınanları göster",
        "Çıkış",
    ]
    checks = {
        "health_pass": bool(health.get("ok")),
        "status_api_pass": bool(status.get("ok") or auth_required),
        "dashboard_has_production_environment": auth_required or "production_environment" in body,
        "dashboard_has_deploy_commands": auth_required or "deploy_commands" in body,
        "index_turkish_labels": auth_required or all(label in body_text for label in labels),
    }
    payload = {
        "ok": all(checks.values()),
        "scope": scope,
        "port": port,
        "checked_at": now(),
        "checks": checks,
        "health": health,
        "status_api_status": status.get("status"),
    }
    payload["runtime_write_status"] = {
        f"{scope}_smoke_state": atomic_write_json(STATE / f"{scope}_smoke_test_status.json", payload),
        "last_smoke_state": atomic_write_json(STATE / "last_smoke_test_status.json", payload),
    }
    payload["runtime_write_status"]["report"] = write_environment_report("smoke_test", payload)
    payload["write_evidence"] = write_evidence_items(payload["runtime_write_status"])
    payload["write_status"] = summarize_write_status(payload["write_evidence"])
    return payload


def rollback_point() -> dict[str, Any]:
    status = git_status()
    return {
        "created_at": now(),
        "branch": status.get("branch"),
        "commit": status.get("head"),
        "production_port": PRODUCTION_PORT,
        "staging_port": STAGING_PORT,
        "rollback_mode": "safe_logical_runtime_rollback",
        "note": "No git reset or data mutation is performed automatically.",
    }


def staging_deploy(dry_run: bool = False) -> dict[str, Any]:
    git = git_status()
    critical = critical_exception_scan()
    result: dict[str, Any] = {
        "ok": False,
        "status": "PENDING",
        "scope": "staging",
        "dry_run": dry_run,
        "started_at": now(),
        "git": git,
        "remote_sync": remote_sync() if git.get("ok") else {"ok": False, "reason": "git_unavailable"},
        "critical_exceptions": critical,
        "commands": configured_commands(),
        "mutating_cloud_operations_performed": False,
    }
    blockers = []
    if not critical["ok"]:
        blockers.append("critical_exception_detected")
    if not git.get("ok"):
        blockers.append("git_unavailable")
    if git.get("blocking_dirty_files") and not dry_run:
        blockers.append("git_blocking_dirty_files")
    if blockers:
        result.update({"status": "BLOCKED", "blockers": blockers})
        write_stage_outputs(result)
        return result
    if dry_run:
        result.update({"ok": True, "status": "PASS", "blockers": [], "health": {"ok": True, "mode": "dry_run"}, "smoke": {"ok": True, "mode": "dry_run"}})
        write_stage_outputs(result)
        return result
    result["panel"] = ensure_panel(STAGING_PORT, "staging", "127.0.0.1", replace_mismatch=True)
    result["health"] = health_check("staging")
    result["smoke"] = smoke_test("staging")
    result["ok"] = bool(result["panel"].get("ok") and result["health"].get("ok") and result["smoke"].get("ok"))
    result["status"] = "PASS" if result["ok"] else "FAIL"
    result["blockers"] = [] if result["ok"] else ["staging_health_or_smoke_failed"]
    write_stage_outputs(result)
    return result


def production_deploy(dry_run: bool = False) -> dict[str, Any]:
    git = git_status()
    remote = remote_sync() if git.get("ok") else {"ok": False, "reason": "git_unavailable"}
    critical = critical_exception_scan()
    staging = read_json(STATE / "staging_deploy_status.json", {})
    execute_enabled = configured_commands()["CODEX_PRODUCTION_DEPLOY_EXECUTE"]["configured"]
    result: dict[str, Any] = {
        "ok": False,
        "status": "PENDING",
        "scope": "production",
        "dry_run": dry_run,
        "started_at": now(),
        "git": git,
        "remote_sync": remote,
        "critical_exceptions": critical,
        "staging": {"status": staging.get("status"), "ok": staging.get("ok"), "commit": staging.get("git", {}).get("head")},
        "commands": configured_commands(),
        "execute_enabled": execute_enabled,
        "deploy_channel": deploy_channel(),
        "local_vm_deploy_fallback_enabled": local_deploy_fallback_enabled(),
        "local_vm_deploy_fallback_context": local_deploy_fallback_context(),
        "mutating_cloud_operations_performed": False,
    }
    blockers = []
    if not execute_enabled:
        blockers.append("production_execute_flag_missing")
    if (
        deploy_channel() == "github_actions_manual"
        and not github_actions_context()
        and not github_actions_local_fallback_allowed()
        and not dry_run
    ):
        blockers.append("github_actions_workflow_required")
    if not critical["ok"]:
        blockers.append("critical_exception_detected")
    if not git.get("ok"):
        blockers.append("git_unavailable")
    if git.get("blocking_dirty_files") and not dry_run:
        blockers.append("git_blocking_dirty_files")
    if not remote.get("ok") and not dry_run:
        blockers.append("github_remote_not_synced")
    if not staging.get("ok") and not dry_run:
        blockers.append("staging_deploy_not_passed")
    if blockers:
        result.update({"status": "BLOCKED", "blockers": blockers})
        write_production_outputs(result)
        return result
    point = rollback_point()
    result["rollback_point"] = point
    if dry_run:
        result.update({"ok": True, "status": "PASS", "blockers": [], "health": {"ok": True, "mode": "dry_run"}, "smoke": {"ok": True, "mode": "dry_run"}})
        write_production_outputs(result)
        return result
    atomic_write_json(STATE / "rollback_point.json", point)
    if github_actions_local_fallback_allowed():
        result["runtime_sync"] = sync_source_to_runtime()
        if not result["runtime_sync"].get("ok"):
            result.update({"status": "FAIL", "blockers": ["runtime_source_sync_failed"]})
            write_production_outputs(result)
            return result
    result["panel"] = ensure_panel(PRODUCTION_PORT, "production", "0.0.0.0", replace_mismatch=True)
    result["health"] = health_check("production")
    result["smoke"] = smoke_test("production")
    result["ok"] = bool(result["panel"].get("ok") and result["health"].get("ok") and result["smoke"].get("ok"))
    result["status"] = "PASS" if result["ok"] else "FAIL"
    result["blockers"] = [] if result["ok"] else ["production_health_or_smoke_failed"]
    if result["ok"]:
        update_runtime_commit_markers(git.get("head", ""), remote.get("origin_head") or remote.get("head"))
    update_system_flags(result["ok"])
    write_production_outputs(result)
    return result


def rollback(dry_run: bool = False) -> dict[str, Any]:
    point = read_json(STATE / "rollback_point.json", rollback_point())
    result = {
        "ok": True,
        "status": "PASS",
        "scope": "production",
        "dry_run": dry_run,
        "checked_at": now(),
        "rollback_point": point,
        "mode": "safe_logical_runtime_rollback",
        "git_reset_performed": False,
        "data_mutation_performed": False,
    }
    if not dry_run:
        result["health"] = health_check("production")
        result["ok"] = bool(result["health"].get("ok"))
        result["status"] = "PASS" if result["ok"] else "FAIL"
    atomic_write_json(STATE / "rollback_status.json", result)
    write_environment_report("rollback", result)
    return result


def update_system_flags(production_ok: bool) -> None:
    state_path = STATE / "system_state.json"
    state = read_json(state_path, {})
    if not isinstance(state, dict):
        state = {}
    state.update(
        {
            "production_deployed": bool(production_ok),
            "staging_deployed": bool(production_ok),
            "repo_changes_applied": bool(production_ok),
            "production_deploy_performed": bool(production_ok),
            "staging_deploy_performed": bool(production_ok),
            "mutating_cloud_operations_performed": False,
            "production_target": "local_codex_dev_center_panel_and_cto_runtime",
        }
    )
    atomic_write_json(state_path, state)


def write_stage_outputs(result: dict[str, Any]) -> None:
    atomic_write_json(STATE / "staging_deploy_status.json", result)
    write_environment_report("staging_deploy", result)


def write_production_outputs(result: dict[str, Any]) -> None:
    atomic_write_json(STATE / "production_runtime_status.json", result)
    write_environment_report("production_deploy", result)


def write_environment_report(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    status = payload.get("status") or ("PASS" if payload.get("ok") else "FAIL")
    lines = [
        "# Production Environment Last Report",
        "",
        f"Generated at: {now()}",
        f"Kind: {kind}",
        f"Status: {status}",
        f"Scope: {payload.get('scope', '-')}",
        f"Dry run: {payload.get('dry_run', False)}",
        "",
        "## Safety",
        "- Secret/IAM/database/DNS/firewall/billing/Google Ads mutate performed: false",
        f"- Critical exception findings: {', '.join(payload.get('critical_exceptions', {}).get('matched_terms', [])) or 'none'}",
        "",
        "## Summary",
        f"- Production port: {PRODUCTION_PORT}",
        f"- Staging port: {STAGING_PORT}",
        f"- Rollback mode: safe logical runtime rollback",
    ]
    blockers = payload.get("blockers", [])
    if blockers:
        lines += ["", "## Blockers"] + [f"- {item}" for item in blockers]
    text = "\n".join(lines) + "\n"
    writes = {
        "production_environment_report": write_text_best_effort(
            REPORTS / "production_environment_last_report.md",
            text,
            root=ROOT,
            operation="write_report",
        )
    }
    if kind == "staging_deploy":
        writes["staging_deploy_report"] = write_text_best_effort(
            REPORTS / "staging_deploy_last_report.md",
            text,
            root=ROOT,
            operation="write_report",
        )
    if kind == "production_deploy":
        writes["production_runtime_report"] = write_text_best_effort(
            REPORTS / "production_runtime_last_report.md",
            text,
            root=ROOT,
            operation="write_report",
        )
    if kind == "rollback":
        writes["rollback_production_report"] = write_text_best_effort(
            REPORTS / "rollback_production_last_report.md",
            text,
            root=ROOT,
            operation="write_report",
        )
    return writes


def inspect_environment() -> dict[str, Any]:
    payload = {
        "ok": True,
        "checked_at": now(),
        "root": str(ROOT),
        "python": sys.executable,
        "git": git_status(),
        "remote_sync": remote_sync(),
        "services": service_discovery(),
        "commands": configured_commands(),
        "critical_exceptions": critical_exception_scan(),
        "production_definition": "Codex Dev Center local web panel, CTO services, worker/recovery/watchdog/lifecycle state and dashboard flow.",
    }
    atomic_write_json(STATE / "production_environment_status.json", payload)
    write_environment_report("inspect", payload)
    return payload


def print_and_exit(payload: dict[str, Any], as_json: bool) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2) if as_json else f"{payload.get('status', 'PASS' if payload.get('ok') else 'FAIL')}: {payload.get('scope', payload.get('checked_at', ''))}")
    if not payload.get("ok"):
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inspect")
    health = sub.add_parser("health-check")
    health.add_argument("--scope", choices=["staging", "production"], default="production")
    smoke = sub.add_parser("smoke-test")
    smoke.add_argument("--scope", choices=["staging", "production"], default="production")
    staging = sub.add_parser("staging-deploy")
    staging.add_argument("--dry-run", action="store_true")
    production = sub.add_parser("production-deploy")
    production.add_argument("--dry-run", action="store_true")
    rb = sub.add_parser("rollback")
    rb.add_argument("--dry-run", action="store_true")
    rb.add_argument("--simulate", action="store_true")
    args = parser.parse_args()

    if args.cmd == "inspect":
        payload = inspect_environment()
    elif args.cmd == "health-check":
        payload = health_check(args.scope)
    elif args.cmd == "smoke-test":
        payload = smoke_test(args.scope)
    elif args.cmd == "staging-deploy":
        payload = staging_deploy(args.dry_run)
    elif args.cmd == "production-deploy":
        payload = production_deploy(args.dry_run)
    elif args.cmd == "rollback":
        payload = rollback(args.dry_run or args.simulate)
    else:
        payload = {"ok": False, "status": "UNKNOWN_COMMAND"}
    print_and_exit(payload, args.json)


if __name__ == "__main__":
    main()
