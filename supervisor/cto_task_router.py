#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .critical_operation_policy import critical_operation_findings
    from .memory_os_context import (
        bind_existing_scope_in_queue,
        bind_task_to_scope,
        conversation_key as memory_os_conversation_key,
        find_latest_scope_in_queue,
        is_memory_os_followup_text,
        is_memory_os_request as memory_os_request,
        record_scope,
    )
    from .state_file_lock import state_file_lock
    from .task_status_constants import (
        TASK_STATUS_DONE,
        TASK_STATUS_FAILED,
        TASK_STATUS_QUEUED,
        TASK_STATUS_ROUTED,
        TASK_STATUS_RUNNING,
        append_audit,
        atomic_write_json,
        normalize_queue_payload,
        normalize_risk,
        redact_sensitive_text,
        read_json,
        utc_now,
        worker_block_reason,
    )
except ImportError:
    from critical_operation_policy import critical_operation_findings
    from memory_os_context import (
        bind_existing_scope_in_queue,
        bind_task_to_scope,
        conversation_key as memory_os_conversation_key,
        find_latest_scope_in_queue,
        is_memory_os_followup_text,
        is_memory_os_request as memory_os_request,
        record_scope,
    )
    from state_file_lock import state_file_lock
    from task_status_constants import (
        TASK_STATUS_DONE,
        TASK_STATUS_FAILED,
        TASK_STATUS_QUEUED,
        TASK_STATUS_ROUTED,
        TASK_STATUS_RUNNING,
        append_audit,
        atomic_write_json,
        normalize_queue_payload,
        normalize_risk,
        redact_sensitive_text,
        read_json,
        utc_now,
        worker_block_reason,
    )

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
WORKERS = ["worker-1", "worker-2", "worker-3", "worker-4"]


def runtime_root(value: str | None = None) -> Path:
    return Path(value).resolve() if value else DEFAULT_ROOT


def queue_path(root: Path) -> Path:
    return root / "state" / "task_queue.json"


def router_state_path(root: Path) -> Path:
    return root / "state" / "cto_router_state.json"


def safe_slug(text: str, limit: int = 52) -> str:
    cleaned = "".join(c if c.isalnum() else "-" for c in text.upper())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:limit] or "TASK"


def next_id(prefix: str, title: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return f"{prefix}-{stamp}-{safe_slug(title)}"


def classify_risk(text: str, requested: str | None = None) -> str:
    if requested:
        return normalize_risk(requested)
    lowered = (text or "").lower()
    if critical_operation_findings(text):
        return "critical"
    high_words = ["database", "migration"]
    normal_delivery_words = ["production", "canlı", "canli", "deploy", "rollback", "yayına al", "yayina al"]
    if any(word in lowered for word in high_words):
        return "high"
    if any(word in lowered for word in normal_delivery_words):
        return "medium"
    if any(word in lowered for word in ["pipeline", "worker", "queue", "telegram", "dashboard", "test"]):
        return "medium"
    return "low"


def normalize_turkish(value: str) -> str:
    return (
        str(value or "").lower()
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )


def is_memory_os_request(text: str) -> bool:
    return memory_os_request(text)


def is_infrastructure_access_change(text: str) -> bool:
    normalized = normalize_turkish(text)
    return any(
        term in normalized
        for term in [
            "ssl",
            "https",
            "tls",
            "sertifika",
            "certificate",
            "domain",
            "dns",
            "firewall",
            "port",
            "nginx",
            "load balancer",
            "reverse proxy",
            "proxy",
        ]
    )


def is_dashboard_cleanup_request(text: str) -> bool:
    lowered = (text or "").lower()
    dashboard_terms = ["dashboard", "navbar", "panel", "menü", "menu", "ui"]
    cleanup_terms = ["kaldır", "kaldiralim", "kaldıralım", "gizle", "çıkar", "cikar", "temizle"]
    return (
        any(term in lowered for term in dashboard_terms)
        and any(term in lowered for term in cleanup_terms)
        and not is_infrastructure_access_change(text)
    )


CONTROL_SIGNAL_MAP = [
    ("production_readiness", ["production readiness", "readiness analysis", "readiness analizi", "go/no-go", "preflight"]),
    ("risk_review", ["risk review", "risk incelemesi"]),
    ("audit", ["audit", "denetim"]),
    ("test_plan", ["test plan", "test planı", "test plani"]),
    ("docs_check", ["checklist", "docs check", "living docs"]),
]

DELIVERY_SIGNALS = [
    "implement",
    "uygula",
    "ship",
    "build",
    "fix code",
    "change service",
    "open pr",
    "deploy",
    "canlıya al",
    "canliya al",
]


def classify_task_route(text: str) -> dict[str, Any]:
    lowered = (text or "").lower()
    if is_memory_os_request(text):
        return {
            "task_class": "feature_task",
            "control_type": "",
            "delivery_mode": "feature_delivery",
            "pipeline_lane": "Memory OS Delivery",
            "explicit_delivery_signal": True,
            "intent_domain": "memory_os",
        }
    if is_infrastructure_access_change(text):
        return {
            "task_class": "control_task",
            "control_type": "infrastructure_access_readiness",
            "delivery_mode": "proposal_only",
            "pipeline_lane": "Controls / Infrastructure Access",
            "explicit_delivery_signal": any(signal in lowered for signal in DELIVERY_SIGNALS),
            "intent_domain": "infrastructure_access",
        }
    control_type = ""
    for candidate, signals in CONTROL_SIGNAL_MAP:
        if any(signal in lowered for signal in signals):
            control_type = candidate
            break
    proposal_only = any(
        signal in lowered
        for signal in [
            "proposal only",
            "review only",
            "do not deploy",
            "do not modify main repo",
            "production deploy yapma",
            "ana repo dosyalarini dogrudan degistirme",
            "ana repo dosyalarını doğrudan değiştirme",
        ]
    )
    if control_type or proposal_only:
        return {
            "task_class": "control_task",
            "control_type": control_type or "review_only",
            "delivery_mode": "proposal_only",
            "pipeline_lane": "Controls / Readiness",
            "explicit_delivery_signal": any(signal in lowered for signal in DELIVERY_SIGNALS),
            "intent_domain": control_type or "review_only",
        }
    return {
        "task_class": "feature_task" if any(signal in lowered for signal in DELIVERY_SIGNALS) else "triage_task",
        "control_type": "",
        "delivery_mode": "feature_delivery",
        "pipeline_lane": "Feature Delivery",
        "explicit_delivery_signal": any(signal in lowered for signal in DELIVERY_SIGNALS),
        "intent_domain": "feature_delivery" if any(signal in lowered for signal in DELIVERY_SIGNALS) else "triage",
    }


def should_split(text: str) -> bool:
    if is_dashboard_cleanup_request(text):
        return False
    if is_memory_os_request(text):
        return False
    route = classify_task_route(text)
    if route["task_class"] == "control_task":
        return False
    lowered = (text or "").lower()
    return any(
        word in lowered
        for word in [
            "uçtan uca",
            "uctan uca",
            "pipeline",
            "worker",
            "queue",
            "telegram",
            "deploy",
            "rollback",
            "production",
            "stabilize",
            "stabilizasyon",
        ]
    )


def choose_worker(index: int) -> str:
    return WORKERS[index % len(WORKERS)]


def planning_subtasks(parent: dict[str, Any], message: str) -> list[dict[str, Any]]:
    if not should_split(message):
        return []
    parent_id = parent["id"]
    stored_message = redact_sensitive_text(message)
    base = [
        (
            "Runtime Queue And Status Normalization",
            "Queue status enumlarini normalize et, stale veya case mismatch durumlarini raporla. Ana repo dosyalarini dogrudan degistirme; proposal ve test plani uret.",
        ),
        (
            "CTO Router And Worker Dispatch Review",
            "Telegram, SSH ve dashboard kaynakli gorevlerin merkezi router uzerinden worker-eligible alt gorevlere ayrilmasini denetle. Production deploy yapma.",
        ),
        (
            "Pipeline Gate And Rollback Readiness Review",
            "Quality gate, smoke test, health check ve rollback zinciri icin kontrollu proposal uret. Canli deploy yapma.",
        ),
    ]
    tasks: list[dict[str, Any]] = []
    for idx, (title, description) in enumerate(base, 1):
        tasks.append(
            {
                "id": f"{parent_id}-SUB{idx}",
                "parent_task_id": parent_id,
                "parent_source": parent.get("source"),
                "title": title,
                "description": description,
                "raw_message": stored_message,
                "source": "cto",
                "priority": parent.get("priority", "normal"),
                "status": TASK_STATUS_QUEUED,
                "risk": "medium",
                "risk_level": "medium",
                "assigned_worker": choose_worker(idx - 1),
                "worker_eligible": True,
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "repo_applied": False,
                "staging_deployed": False,
                "production_deployed": False,
                "delivery_level": "PLAN_REQUESTED",
            }
        )
    return tasks


def normalize_queue(root: Path, fix: bool = False) -> dict[str, Any]:
    path = queue_path(root)
    with state_file_lock(path):
        payload = read_json(path, {"tasks": []})
        normalized, changes = normalize_queue_payload(payload)
        if fix and changes:
            atomic_write_json(path, normalized)
            append_audit(root, "queue_normalized", {"changes": len(changes)})
    return {
        "ok": True,
        "changes": changes,
        "task_count": len(normalized.get("tasks", [])),
    }


def submit_task(
    root: Path,
    source: str,
    title: str,
    message: str,
    priority: str = "normal",
    risk: str | None = None,
    requested_by: str = "",
    conversation_id: str = "",
    split: bool | None = None,
    worker_eligible: bool | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    qpath = queue_path(root)
    source = str(source or "local").strip().lower()
    effective_risk = classify_risk(f"{title}\n{message}", risk)
    stored_message = redact_sensitive_text(message)
    route = classify_task_route(f"{title}\n{message}")
    memory_conversation_id = memory_os_conversation_key(
        source=source,
        requested_by=requested_by,
        conversation_id=conversation_id,
    )
    memory_text = f"{title}\n{message}"
    memory_intent = is_memory_os_request(memory_text)
    memory_followup = is_memory_os_followup_text(message) or is_memory_os_followup_text(title)
    if worker_eligible is None:
        worker_eligible = source != "telegram" and effective_risk not in {"high", "critical"}
    if effective_risk in {"high", "critical"}:
        worker_eligible = False

    bound_existing_memory_scope = False
    memory_scope: dict[str, Any] = {}
    with state_file_lock(qpath):
        queue = read_json(qpath, {"tasks": []})
        tasks = queue.setdefault("tasks", [])
        existing_memory_scope = (
            find_latest_scope_in_queue(queue, conversation_id=memory_conversation_id)
            if (memory_intent or memory_followup)
            else {}
        )
        if existing_memory_scope and (memory_intent or memory_followup):
            bound = bind_existing_scope_in_queue(
                queue,
                existing_memory_scope,
                stored_message,
                event_type="explicit_request" if memory_intent else "followup_or_approval",
                source=source,
            )
            if bound:
                parent = bound
                created_subtasks: list[dict[str, Any]] = []
                bound_existing_memory_scope = True
                memory_scope = dict(existing_memory_scope)
                normalized, changes = normalize_queue_payload(queue)
                atomic_write_json(qpath, normalized)
            else:
                existing_memory_scope = {}

        if not bound_existing_memory_scope:
            parent_status = TASK_STATUS_QUEUED if worker_eligible else TASK_STATUS_ROUTED
            parent = {
                "id": next_id("CTO-TASK", title),
                "title": title,
                "description": stored_message,
                "raw_message": stored_message,
                "source": source,
                "priority": priority,
                "status": parent_status,
                "risk": effective_risk,
                "risk_level": effective_risk,
                "assigned_worker": None,
                "worker_eligible": worker_eligible,
                "requested_by": requested_by,
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "repo_applied": False,
                "staging_deployed": False,
                "production_deployed": False,
                "delivery_level": "ROUTED" if not worker_eligible else "QUEUED",
                "task_class": route["task_class"],
                "control_type": route["control_type"],
                "delivery_mode": route["delivery_mode"],
                "pipeline_lane": route["pipeline_lane"],
                "intent_domain": route.get("intent_domain", ""),
            }
            if memory_intent:
                memory_scope = {
                    "schema_version": 1,
                    "scope_id": f"memory-os:{parent['id']}",
                    "root_task_id": parent["id"],
                    "conversation_id": memory_conversation_id,
                    "title": title,
                    "last_user_text": stored_message,
                    "active": True,
                    "has_worker_apply_tasks": False,
                }
                bind_task_to_scope(parent, memory_scope, root_task_id=parent["id"])
            if route["task_class"] == "control_task":
                parent["repo_apply_allowed"] = False
                parent["production_deployed"] = False
                parent["proposal_only"] = True
            if worker_eligible:
                parent["assigned_worker"] = choose_worker(len(tasks))
            tasks.append(parent)

            should_create_subtasks = should_split(message) if split is None else split
            created_subtasks = planning_subtasks(parent, message) if should_create_subtasks else []
            if memory_scope and created_subtasks:
                for subtask in created_subtasks:
                    bind_task_to_scope(subtask, memory_scope, root_task_id=parent["id"])
            tasks.extend(created_subtasks)

            normalized, changes = normalize_queue_payload(queue)
            atomic_write_json(qpath, normalized)

    if memory_intent or bound_existing_memory_scope:
        task_ids = None if bound_existing_memory_scope else [
            str(parent.get("id") or ""),
            *[str(item.get("id") or "") for item in created_subtasks],
        ]
        if not memory_scope:
            memory_scope = {
                "scope_id": f"memory-os:{parent.get('root_task_id') or parent.get('id')}",
                "root_task_id": str(parent.get("root_task_id") or parent.get("id") or ""),
                "conversation_id": memory_conversation_id,
                "title": str(parent.get("title") or title),
            }
        record_scope(
            root,
            memory_scope,
            user_text=stored_message,
            task_ids=task_ids,
            event_type="bound_existing_scope" if bound_existing_memory_scope else "scope_created",
        )

    state = read_json(router_state_path(root), {})
    state.update(
        {
            "enabled": True,
            "last_task_id": parent["id"],
            "last_source": source,
            "last_priority": priority,
            "last_risk": effective_risk,
            "last_worker_block_reason": worker_block_reason(parent),
            "last_subtask_count": len(created_subtasks),
            "last_task_class": route["task_class"],
            "last_control_type": route["control_type"],
            "last_memory_os_scope_root_task_id": memory_scope.get("root_task_id", ""),
            "last_memory_os_bound_to_existing_scope": bound_existing_memory_scope,
            "queue_normalization_changes": len(changes),
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(router_state_path(root), state)
    append_audit(
        root,
        "cto_task_submitted",
        {
            "task_id": parent["id"],
            "source": source,
            "risk": effective_risk,
            "priority": priority,
            "worker_eligible": worker_eligible,
            "subtasks": len(created_subtasks),
            "memory_os_scope_root_task_id": memory_scope.get("root_task_id", ""),
            "memory_os_bound_to_existing_scope": bound_existing_memory_scope,
        },
    )
    return {
        "ok": True,
        "task": parent,
        "subtasks": created_subtasks,
        "normalization_changes": changes,
        "memory_os_scope": memory_scope,
        "memory_os_bound_to_existing_scope": bound_existing_memory_scope,
    }


def mark_task_status(root: Path, task_id: str, status: str, result: str = "") -> dict[str, Any]:
    qpath = queue_path(root)
    with state_file_lock(qpath):
        queue = read_json(qpath, {"tasks": []})
        found = None
        for task in queue.get("tasks", []):
            if task.get("id") == task_id:
                task["status"] = status
                task["result"] = result
                task["updated_at"] = utc_now()
                found = task
                break
        if not found:
            return {"ok": False, "error": "task_not_found", "task_id": task_id}
        normalized, changes = normalize_queue_payload(queue)
        atomic_write_json(qpath, normalized)
    append_audit(root, "cto_task_status", {"task_id": task_id, "status": status, "result": result})
    return {"ok": True, "task": found, "normalization_changes": changes}


def trigger_lifecycle(root: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["python3", "supervisor/lifecycle_manager.py", "dispatch"],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        return {"ok": proc.returncode == 0, "returncode": proc.returncode}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="CTO task router")
    parser.add_argument("--runtime", default=str(DEFAULT_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit")
    submit.add_argument("--source", required=True)
    submit.add_argument("--priority", default="normal")
    submit.add_argument("--title", required=True)
    submit.add_argument("--message", required=True)
    submit.add_argument("--risk", default=None)
    submit.add_argument("--requested-by", default="")
    submit.add_argument("--conversation-id", default="")
    submit.add_argument("--split", action="store_true")
    submit.add_argument("--no-split", action="store_true")
    submit.add_argument("--worker-eligible", action="store_true")
    submit.add_argument("--no-worker-eligible", action="store_true")

    normalize = sub.add_parser("normalize")
    normalize.add_argument("--fix", action="store_true")

    trace = sub.add_parser("mark")
    trace.add_argument("--task-id", required=True)
    trace.add_argument("--status", required=True)
    trace.add_argument("--result", default="")

    args = parser.parse_args()
    root = runtime_root(args.runtime)
    if args.command == "normalize":
        print(json.dumps(normalize_queue(root, fix=args.fix), indent=2, ensure_ascii=False))
        return 0
    if args.command == "mark":
        result = mark_task_status(root, args.task_id, args.status, args.result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    split = None
    if args.split:
        split = True
    if args.no_split:
        split = False
    worker_eligible = None
    if args.worker_eligible:
        worker_eligible = True
    if args.no_worker_eligible:
        worker_eligible = False
    result = submit_task(
        root=root,
        source=args.source,
        title=args.title,
        message=args.message,
        priority=args.priority,
        risk=args.risk,
        requested_by=args.requested_by,
        conversation_id=args.conversation_id,
        split=split,
        worker_eligible=worker_eligible,
    )
    if any(t.get("worker_eligible") for t in [result["task"], *result["subtasks"]]):
        result["lifecycle"] = trigger_lifecycle(root)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
