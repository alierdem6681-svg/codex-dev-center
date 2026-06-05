#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .task_status_constants import (
        TERMINAL_TASK_STATUSES,
        atomic_write_json,
        normalize_status,
        read_json,
        redact_sensitive_text,
        utc_now,
    )
except ImportError:
    from task_status_constants import (
        TERMINAL_TASK_STATUSES,
        atomic_write_json,
        normalize_status,
        read_json,
        redact_sensitive_text,
        utc_now,
    )


STATE_FILE_NAME = "memory_os_context.json"
SCHEMA_VERSION = 1
MAX_CONTEXT_TEXT_CHARS = 700
MAX_CONTINUATION_EVENTS = 12


def normalize_turkish(value: Any) -> str:
    return (
        str(value or "").lower()
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )


def compact_context_text(value: Any, limit: int = MAX_CONTEXT_TEXT_CHARS) -> str:
    text = " ".join(redact_sensitive_text(value).split())
    return text[:limit]


def is_memory_os_request(text: Any) -> bool:
    normalized = normalize_turkish(text)
    return any(
        marker in normalized
        for marker in [
            "memory os",
            "memory-os",
            "cto-memory-os",
            "cto memory os",
            "memoryos",
            "hafiza os",
            "hafiza sistemi",
            "hafiza modulu",
        ]
    )


def is_memory_os_followup_text(text: Any) -> bool:
    normalized = " ".join(normalize_turkish(text).split())
    if not normalized:
        return False
    if is_memory_os_request(normalized):
        return True
    exact = {
        "devam",
        "tamam devam",
        "devam edelim",
        "devam ettirelim",
        "basla",
        "baslat",
        "hadi baslayalim",
        "baslayalim",
        "gelistirmeye baslayalim",
        "gelistirmeye basla",
        "uygulamaya baslayalim",
        "onayliyorum",
        "onayliyorum devam",
        "tamam onayliyorum",
        "evet",
        "tamam",
        "uygula",
        "canliya al",
    }
    if normalized in exact:
        return True
    if len(normalized) > 120:
        return False
    return any(term in normalized for term in ["devam", "onay", "basla", "baslat"])


def conversation_key(source: str = "", requested_by: str = "", conversation_id: str = "") -> str:
    explicit = str(conversation_id or "").strip()
    if explicit:
        return explicit
    src = str(source or "direct_cto").strip().lower() or "direct_cto"
    actor = str(requested_by or "").strip().lower()
    return f"{src}:{actor}" if actor else f"{src}:default"


def state_path(root: Path) -> Path:
    return Path(root) / "state" / STATE_FILE_NAME


def _task_root_id(task: dict[str, Any]) -> str:
    return str(task.get("root_task_id") or task.get("parent_task_id") or task.get("id") or "").strip()


def _task_conversation(task: dict[str, Any]) -> str:
    return str(
        task.get("memory_os_conversation_id")
        or task.get("conversation_id")
        or task.get("telegram_conversation_id")
        or ""
    ).strip()


def task_is_memory_os(task: dict[str, Any]) -> bool:
    if str(task.get("intent_domain") or "").strip().lower() == "memory_os":
        return True
    if task.get("memory_os_context_id") or task.get("memory_os_scope_root_task_id"):
        return True
    return is_memory_os_request(
        "\n".join(
            [
                str(task.get("id") or ""),
                str(task.get("title") or ""),
                str(task.get("description") or ""),
                str(task.get("raw_message") or ""),
            ]
        )
    )


def _scope_group(queue: dict[str, Any], root_task_id: str) -> list[dict[str, Any]]:
    return [
        task
        for task in queue.get("tasks", [])
        if _task_root_id(task) == root_task_id or str(task.get("id") or "") == root_task_id
    ]


def scope_is_active(queue: dict[str, Any], root_task_id: str) -> bool:
    group = _scope_group(queue, root_task_id)
    if not group:
        return False
    for task in group:
        if normalize_status(task.get("status")) not in TERMINAL_TASK_STATUSES:
            return True
    return False


def scope_has_worker_apply_tasks(queue: dict[str, Any], root_task_id: str) -> bool:
    for task in _scope_group(queue, root_task_id):
        if not task_is_memory_os(task):
            continue
        if task.get("worker_eligible") or task.get("repo_apply_allowed") or task.get("execution_mode") == "repo_apply":
            return True
    return False


def _scope_from_task(queue: dict[str, Any], task: dict[str, Any], conv: str) -> dict[str, Any]:
    root_task_id = _task_root_id(task)
    root_task = next((item for item in queue.get("tasks", []) if str(item.get("id") or "") == root_task_id), task)
    scope_id = str(task.get("memory_os_context_id") or f"memory-os:{root_task_id}")
    return {
        "schema_version": SCHEMA_VERSION,
        "scope_id": scope_id,
        "root_task_id": root_task_id,
        "conversation_id": conv or _task_conversation(task),
        "title": str(root_task.get("title") or task.get("title") or "Memory OS"),
        "last_user_text": compact_context_text(root_task.get("raw_message") or root_task.get("description") or ""),
        "active": scope_is_active(queue, root_task_id),
        "has_worker_apply_tasks": scope_has_worker_apply_tasks(queue, root_task_id),
    }


def find_latest_scope_in_queue(queue: dict[str, Any], conversation_id: str = "") -> dict[str, Any]:
    conv = str(conversation_id or "").strip()
    for task in reversed(queue.get("tasks", [])):
        if not task_is_memory_os(task):
            continue
        task_conv = _task_conversation(task)
        if conv and task_conv and task_conv != conv:
            continue
        root_task_id = _task_root_id(task)
        if not scope_is_active(queue, root_task_id):
            continue
        return _scope_from_task(queue, task, conv or task_conv)
    return {}


def find_latest_scope(root: Path, conversation_id: str = "") -> dict[str, Any]:
    queue = read_json(Path(root) / "state" / "task_queue.json", {"tasks": []})
    scope = find_latest_scope_in_queue(queue, conversation_id=conversation_id)
    if scope:
        return scope
    state = read_json(state_path(Path(root)), {"conversations": {}})
    conv = str(conversation_id or "").strip()
    if conv:
        stored = state.get("conversations", {}).get(conv, {})
        if stored:
            return dict(stored)
    return dict(state.get("last_scope") or {})


def bind_task_to_scope(task: dict[str, Any], scope: dict[str, Any], root_task_id: str = "") -> dict[str, Any]:
    root_id = str(root_task_id or scope.get("root_task_id") or task.get("root_task_id") or task.get("id") or "").strip()
    scope_id = str(scope.get("scope_id") or f"memory-os:{root_id}")
    conv = str(scope.get("conversation_id") or "").strip()
    task["intent_domain"] = "memory_os"
    task["memory_os_context_id"] = scope_id
    task["memory_os_scope_root_task_id"] = root_id
    if conv:
        task["memory_os_conversation_id"] = conv
    if root_id:
        task["root_task_id"] = root_id
        if str(task.get("id") or "") != root_id:
            task.setdefault("parent_task_id", root_id)
    task["memory_os_bound"] = True
    return task


def append_continuation_to_task(
    task: dict[str, Any],
    text: Any,
    event_type: str = "followup",
    source: str = "",
) -> dict[str, Any]:
    event = {
        "at": utc_now(),
        "event_type": event_type,
        "source": str(source or ""),
        "text": compact_context_text(text, limit=360),
    }
    events = task.setdefault("memory_os_continuations", [])
    if not isinstance(events, list):
        events = []
    events.append(event)
    task["memory_os_continuations"] = events[-MAX_CONTINUATION_EVENTS:]
    task["last_memory_os_followup_at"] = event["at"]
    task["memory_os_bound_to_existing_scope"] = True
    task["updated_at"] = event["at"]
    return task


def bind_existing_scope_in_queue(
    queue: dict[str, Any],
    scope: dict[str, Any],
    text: Any,
    event_type: str = "followup",
    source: str = "",
) -> dict[str, Any]:
    root_task_id = str(scope.get("root_task_id") or "").strip()
    if not root_task_id:
        return {}
    for task in queue.get("tasks", []):
        if str(task.get("id") or "") == root_task_id:
            bind_task_to_scope(task, scope, root_task_id=root_task_id)
            append_continuation_to_task(task, text, event_type=event_type, source=source)
            return task
    return {}


def record_scope(
    root: Path,
    scope: dict[str, Any],
    user_text: Any = "",
    task_ids: list[str] | None = None,
    event_type: str = "scope_recorded",
) -> dict[str, Any]:
    path = state_path(Path(root))
    data = read_json(path, {"schema_version": SCHEMA_VERSION, "conversations": {}})
    data["schema_version"] = SCHEMA_VERSION
    conv = str(scope.get("conversation_id") or "").strip() or "direct_cto:default"
    stored = dict(data.get("conversations", {}).get(conv, {}))
    stored.update({k: v for k, v in scope.items() if v not in (None, "")})
    stored["conversation_id"] = conv
    stored["updated_at"] = utc_now()
    if user_text:
        stored["last_user_text"] = compact_context_text(user_text)
    if task_ids is not None:
        stored["task_ids"] = [str(item) for item in task_ids if item]
    events = stored.setdefault("events", [])
    if not isinstance(events, list):
        events = []
    events.append(
        {
            "at": stored["updated_at"],
            "event_type": event_type,
            "text": compact_context_text(user_text, limit=360),
        }
    )
    stored["events"] = events[-MAX_CONTINUATION_EVENTS:]
    data.setdefault("conversations", {})[conv] = stored
    data["last_scope"] = stored
    atomic_write_json(path, data)
    return stored


def prompt_context(scope: dict[str, Any]) -> str:
    if not scope:
        return ""
    return "\n".join(
        [
            "MEMORY_OS_CONTEXT_START",
            f"scope_id={scope.get('scope_id', '')}",
            f"root_task_id={scope.get('root_task_id', '')}",
            f"conversation_id={scope.get('conversation_id', '')}",
            f"title={scope.get('title', 'Memory OS')}",
            f"last_user_text={compact_context_text(scope.get('last_user_text', ''))}",
            "Use this context for same-conversation continuation or approval messages. Do not create a duplicate root task for this Memory OS scope.",
            "MEMORY_OS_CONTEXT_END",
        ]
    )


def followup_action_text(scope: dict[str, Any], text: Any) -> str:
    return "\n".join(
        [
            "Memory OS devam/onay baglami:",
            f"Root task: {scope.get('root_task_id', '')}",
            f"Scope: {scope.get('scope_id', '')}",
            f"Son kapsam: {compact_context_text(scope.get('last_user_text', ''))}",
            "",
            "Kullanici takip mesaji:",
            compact_context_text(text, limit=360),
        ]
    )
