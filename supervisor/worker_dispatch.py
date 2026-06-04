#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .task_status_constants import (
        ACTIVE_TASK_STATUSES,
        normalize_risk,
        normalize_status,
        read_json,
    )
except ImportError:
    from task_status_constants import (
        ACTIVE_TASK_STATUSES,
        normalize_risk,
        normalize_status,
        read_json,
    )

ROOT = Path(__file__).resolve().parents[1]
WORKER_IDS = ["worker-1", "worker-2", "worker-3", "worker-4"]
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
BLOCKED_WORKER_STATUSES = {"ERROR", "BLOCKED", "STOPPED"}

CAPABILITY_KEYWORDS = {
    "api": "api",
    "audit": "audit",
    "backend": "backend_services",
    "dashboard": "dashboard",
    "deploy": "staging",
    "frontend": "dashboard",
    "gate": "testing",
    "health": "staging",
    "html": "html",
    "infrastructure": "infrastructure_files",
    "javascript": "javascript",
    "lifecycle": "systemd",
    "panel": "dashboard",
    "pipeline": "testing",
    "python": "python",
    "quality": "testing",
    "queue": "backend_services",
    "rollback": "backup",
    "router": "backend_services",
    "security": "risk_review",
    "service": "systemd",
    "smoke": "testing",
    "test": "testing",
    "ui": "ux",
    "validation": "testing",
    "worker": "backend_services",
}


def normalize_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def normalize_tokens(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw_values = [values]
    else:
        try:
            raw_values = list(values)
        except TypeError:
            raw_values = [values]
    tokens: list[str] = []
    for value in raw_values:
        token = normalize_token(value)
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def default_profiles() -> list[dict[str, Any]]:
    return [
        {"id": worker_id, "enabled": True, "risk_limit": "medium", "capabilities": []}
        for worker_id in WORKER_IDS
    ]


def worker_profiles_path(root: Path) -> Path:
    runtime_path = root / "state" / "worker_profiles.json"
    if runtime_path.exists():
        return runtime_path
    return root / "state_templates" / "worker_profiles.json"


def load_worker_profiles(root: Path | None = None) -> list[dict[str, Any]]:
    root = (root or ROOT).resolve()
    payload = read_json(worker_profiles_path(root), {"profiles": default_profiles()})
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, list):
        return default_profiles()
    normalized = [normalize_profile(profile) for profile in profiles if isinstance(profile, dict)]
    return normalized or default_profiles()


def normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    capabilities = normalize_tokens(profile.get("capabilities") or profile.get("skills"))
    worker_id = str(profile.get("id") or "").strip()
    return {
        **profile,
        "id": worker_id,
        "enabled": profile.get("enabled") is not False,
        "risk_limit": normalize_risk(profile.get("risk_limit") or "medium"),
        "role": str(profile.get("role") or profile.get("name") or worker_id),
        "capabilities": capabilities,
    }


def task_required_role(task: dict[str, Any]) -> str:
    return normalize_token(task.get("required_role") or task.get("role"))


def explicit_task_capabilities(task: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("required_capabilities", "required_skills", "capabilities", "skills"):
        current = task.get(key)
        if current:
            if isinstance(current, str):
                values.append(current)
            else:
                values.extend(list(current))
    return normalize_tokens(values)


def inferred_task_capabilities(task: dict[str, Any]) -> list[str]:
    text = " ".join(str(task.get(key, "")) for key in ("title", "description", "raw_message")).lower()
    return normalize_tokens(capability for keyword, capability in CAPABILITY_KEYWORDS.items() if keyword in text)


def task_capabilities(task: dict[str, Any]) -> tuple[list[str], bool]:
    explicit = explicit_task_capabilities(task)
    if explicit:
        return explicit, False
    return inferred_task_capabilities(task), True


def risk_allows(profile: dict[str, Any], task: dict[str, Any]) -> bool:
    worker_limit = RISK_ORDER.get(normalize_risk(profile.get("risk_limit")), 1)
    task_risk = RISK_ORDER.get(normalize_risk(task.get("risk") or task.get("risk_level")), 0)
    return worker_limit >= task_risk


def role_allows(profile: dict[str, Any], required_role: str) -> bool:
    if not required_role:
        return True
    role_text = normalize_token(profile.get("role"))
    name_text = normalize_token(profile.get("name"))
    worker_id = normalize_token(profile.get("id"))
    return required_role in {worker_id, role_text, name_text} or required_role in role_text or required_role in name_text


def capabilities_allow(profile: dict[str, Any], required_capabilities: list[str]) -> bool:
    if not required_capabilities:
        return True
    available = set(normalize_tokens(profile.get("capabilities") or profile.get("skills")))
    return set(required_capabilities).issubset(available)


def worker_state_map(workers: dict[str, Any] | list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if isinstance(workers, dict):
        worker_list = workers.get("workers", [])
    else:
        worker_list = workers or []
    return {
        str(worker.get("id")): worker
        for worker in worker_list
        if isinstance(worker, dict) and worker.get("id")
    }


def worker_is_available(worker_id: str, states: dict[str, dict[str, Any]], available_worker_ids: set[str] | None) -> bool:
    if available_worker_ids is not None and worker_id not in available_worker_ids:
        return False
    state = states.get(worker_id, {})
    status = str(state.get("status") or "").strip().upper()
    return status not in BLOCKED_WORKER_STATUSES


def active_counts(queue: dict[str, Any] | None) -> dict[str, int]:
    counts = {worker_id: 0 for worker_id in WORKER_IDS}
    for task in (queue or {}).get("tasks", []):
        if not isinstance(task, dict):
            continue
        if normalize_status(task.get("status")) not in ACTIVE_TASK_STATUSES:
            continue
        worker_id = task.get("assigned_worker")
        if worker_id in counts:
            counts[worker_id] += 1
    return counts


def select_worker_for_task(
    task: dict[str, Any],
    profiles: list[dict[str, Any]] | None = None,
    queue: dict[str, Any] | None = None,
    workers: dict[str, Any] | list[dict[str, Any]] | None = None,
    available_worker_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    fallback_order: list[str] | None = None,
) -> str:
    profiles = profiles or load_worker_profiles()
    fallback_order = fallback_order or WORKER_IDS
    order = {worker_id: idx for idx, worker_id in enumerate(fallback_order)}
    available_ids = set(available_worker_ids) if available_worker_ids is not None else None
    states = worker_state_map(workers)
    counts = active_counts(queue)
    required_role = task_required_role(task)
    required_capabilities, inferred = task_capabilities(task)

    candidates = [
        profile
        for profile in profiles
        if profile.get("id") in WORKER_IDS
        and profile.get("enabled", True)
        and risk_allows(profile, task)
        and worker_is_available(str(profile.get("id")), states, available_ids)
    ]
    if not candidates:
        return ""

    exact = [
        profile
        for profile in candidates
        if role_allows(profile, required_role) and capabilities_allow(profile, required_capabilities)
    ]
    if not exact and not inferred and (required_role or required_capabilities):
        return ""
    if not exact and inferred:
        exact = [profile for profile in candidates if role_allows(profile, required_role)]
    if not exact:
        exact = candidates

    return str(
        min(
            exact,
            key=lambda profile: (
                counts.get(str(profile.get("id")), 0),
                order.get(str(profile.get("id")), len(WORKER_IDS)),
            ),
        ).get("id")
    )


def assign_tasks_to_idle_workers(
    workers: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    profiles: list[dict[str, Any]] | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    idle_by_id = {
        str(worker.get("id")): worker
        for worker in workers
        if str(worker.get("status") or "").upper() in {"IDLE", "READY"}
    }
    assignments: list[tuple[dict[str, Any], dict[str, Any]]] = []
    queue = {"tasks": tasks}

    for task in tasks:
        if not idle_by_id:
            break
        preferred = task.get("assigned_worker")
        if preferred in idle_by_id:
            worker_id = str(preferred)
        else:
            worker_id = select_worker_for_task(
                task,
                profiles=profiles,
                queue=queue,
                workers=workers,
                available_worker_ids=set(idle_by_id),
            )
        if worker_id not in idle_by_id:
            continue
        assignments.append((idle_by_id.pop(worker_id), task))

    return assignments
