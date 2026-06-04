#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from .task_status_constants import ACTIVE_TASK_STATUSES, normalize_risk, normalize_status, read_json
except ImportError:
    from task_status_constants import ACTIVE_TASK_STATUSES, normalize_risk, normalize_status, read_json

WORKERS = ["worker-1", "worker-2", "worker-3", "worker-4"]

RISK_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

DEFAULT_PROFILE_PAYLOAD = {
    "profiles": [
        {
            "id": "worker-1",
            "enabled": True,
            "name": "Backend / Infrastructure Worker",
            "role": "Backend ve altyapi",
            "skills": ["python", "api", "database_schema", "backend_services", "infrastructure_files"],
            "risk_limit": "medium",
        },
        {
            "id": "worker-2",
            "enabled": True,
            "name": "Frontend / Dashboard Worker",
            "role": "Frontend ve panel",
            "skills": ["html", "css", "javascript", "dashboard", "ux"],
            "risk_limit": "medium",
        },
        {
            "id": "worker-3",
            "enabled": True,
            "name": "DevOps / Services Worker",
            "role": "DevOps, servis ve deploy iskeleti",
            "skills": ["systemd", "docker", "logs", "backup", "staging"],
            "risk_limit": "medium",
        },
        {
            "id": "worker-4",
            "enabled": True,
            "name": "QA / Security Worker",
            "role": "Test, kalite ve guvenlik denetimi",
            "skills": ["testing", "lint", "audit", "risk_review", "output_guard"],
            "risk_limit": "medium",
        },
    ]
}

ROLE_ALIASES = {
    "backend": {"backend", "infrastructure", "altyapi", "api", "python", "worker_1"},
    "infrastructure": {"backend", "infrastructure", "altyapi", "worker_1"},
    "frontend": {"frontend", "dashboard", "panel", "ui", "ux", "worker_2"},
    "dashboard": {"frontend", "dashboard", "panel", "worker_2"},
    "devops": {"devops", "service", "services", "deploy", "staging", "systemd", "worker_3"},
    "services": {"devops", "service", "services", "deploy", "staging", "systemd", "worker_3"},
    "qa": {"qa", "quality", "test", "testing", "security", "audit", "worker_4"},
    "quality": {"qa", "quality", "test", "testing", "audit", "worker_4"},
    "security": {"qa", "security", "audit", "worker_4"},
}

CAPABILITY_HINTS = (
    ("dashboard", ("dashboard", "panel", "frontend", "ui", "html", "css", "javascript")),
    ("testing", ("test", "quality", "validation", "gate", "qa", "audit")),
    ("staging", ("deploy", "rollback", "staging", "systemd", "service", "lifecycle", "backup")),
    ("python", ("python", "backend", "api", "supervisor", "queue", "router", "worker dispatch", "dispatch")),
)


def normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _tokens(value: Any) -> set[str]:
    return {normalize_key(item) for item in re.split(r"[^a-zA-Z0-9]+", str(value or "")) if item}


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [item for item in re.split(r"[,\s]+", str(value)) if item]


def iter_profiles(profiles_payload: Any) -> list[dict[str, Any]]:
    if isinstance(profiles_payload, dict):
        profiles = profiles_payload.get("profiles", [])
    else:
        profiles = profiles_payload
    if not isinstance(profiles, list):
        return DEFAULT_PROFILE_PAYLOAD["profiles"]
    return [profile for profile in profiles if isinstance(profile, dict)]


def load_worker_profiles(root: Path) -> list[dict[str, Any]]:
    for path in [root / "state" / "worker_profiles.json", root / "state_templates" / "worker_profiles.json"]:
        payload = read_json(path, {})
        profiles = iter_profiles(payload)
        if profiles:
            return profiles
    return DEFAULT_PROFILE_PAYLOAD["profiles"]


def profile_capabilities(profile: dict[str, Any]) -> set[str]:
    capabilities: set[str] = set()
    for key in ("skills", "capabilities"):
        capabilities.update(normalize_key(item) for item in _coerce_list(profile.get(key)))
    return {capability for capability in capabilities if capability}


def profile_words(profile: dict[str, Any]) -> set[str]:
    words = set()
    words.add(normalize_key(profile.get("id")))
    words.update(_tokens(profile.get("id")))
    words.update(_tokens(profile.get("name")))
    words.update(_tokens(profile.get("role")))
    words.update(profile_capabilities(profile))
    return {word for word in words if word}


def profile_enabled(profile: dict[str, Any]) -> bool:
    return profile.get("enabled") is not False and normalize_key(profile.get("status")) not in {"disabled", "stopped"}


def risk_allowed(profile: dict[str, Any], task_risk: str) -> bool:
    limit = normalize_risk(profile.get("risk_limit") or "medium")
    return RISK_ORDER[normalize_risk(task_risk)] <= RISK_ORDER[limit]


def required_role_matches(required_role: Any, profile: dict[str, Any]) -> bool:
    role = normalize_key(required_role)
    if not role:
        return True
    words = profile_words(profile)
    aliases = ROLE_ALIASES.get(role, {role})
    return bool(words & aliases) or role in words


def explicit_required_capabilities(task: dict[str, Any]) -> set[str]:
    values = _coerce_list(task.get("required_capabilities") or task.get("required_skills"))
    return {normalize_key(value) for value in values if normalize_key(value)}


def inferred_capability_preferences(task: dict[str, Any]) -> set[str]:
    text = " ".join(
        str(task.get(key, ""))
        for key in ("title", "description", "raw_message", "module", "task_type")
    ).lower()
    preferences: set[str] = set()
    for capability, hints in CAPABILITY_HINTS:
        if any(hint in text for hint in hints):
            preferences.add(capability)
    return preferences


def active_counts_from_tasks(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {worker_id: 0 for worker_id in WORKERS}
    for task in tasks:
        worker_id = task.get("assigned_worker")
        if worker_id not in counts:
            continue
        if normalize_status(task.get("status")) in ACTIVE_TASK_STATUSES:
            counts[worker_id] += 1
    return counts


def select_worker_for_task(
    task: dict[str, Any],
    profiles_payload: Any,
    active_counts: dict[str, int] | None = None,
    fallback_index: int = 0,
) -> str:
    active_counts = active_counts or {}
    task_risk = normalize_risk(task.get("risk") or task.get("risk_level") or "low")
    required_role = task.get("required_role")
    required_capabilities = explicit_required_capabilities(task)
    preferences = inferred_capability_preferences(task)

    candidates: list[dict[str, Any]] = []
    for profile in iter_profiles(profiles_payload):
        worker_id = str(profile.get("id") or "")
        if worker_id not in WORKERS:
            continue
        if not profile_enabled(profile):
            continue
        if not risk_allowed(profile, task_risk):
            continue
        if not required_role_matches(required_role, profile):
            continue
        if required_capabilities and not required_capabilities.issubset(profile_capabilities(profile)):
            continue
        candidates.append(profile)

    if not candidates:
        return WORKERS[fallback_index % len(WORKERS)]

    def sort_key(profile: dict[str, Any]) -> tuple[int, int, int]:
        worker_id = str(profile.get("id") or "")
        match_score = len(preferences & (profile_capabilities(profile) | profile_words(profile)))
        return (-match_score, int(active_counts.get(worker_id, 0) or 0), WORKERS.index(worker_id))

    return str(sorted(candidates, key=sort_key)[0].get("id"))
