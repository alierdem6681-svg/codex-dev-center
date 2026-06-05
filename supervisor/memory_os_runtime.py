#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from .task_status_constants import append_audit, atomic_write_json, read_json, redact_sensitive_text, utc_now
except ImportError:
    from task_status_constants import append_audit, atomic_write_json, read_json, redact_sensitive_text, utc_now


ROOT = Path(__file__).resolve().parents[1]
MODULE_SETTINGS = ROOT / "modules" / "memory_os_runtime" / "settings.json"

DEFAULT_CONTRACT: dict[str, Any] = {
    "state_schema_version": "memory_os_runtime_state_v1",
    "record_schema_version": "memory_os_record_v1",
    "summary_schema_version": "memory_os_summary_v1",
    "runtime_state_file": "state/memory_os_runtime.json",
    "max_records": 200,
    "max_title_chars": 160,
    "max_content_chars": 4000,
    "max_summary_chars": 500,
    "max_tag_count": 12,
    "max_recall_key_count": 24,
    "safe_metadata_keys": [
        "actor",
        "intent_domain",
        "module",
        "parent_task_id",
        "pipeline_lane",
        "risk",
        "root_task_id",
        "source",
        "status",
        "task_id",
        "worker_id",
    ],
    "raw_payload_storage_allowed": False,
    "credential_value_storage_allowed": False,
    "environment_value_storage_allowed": False,
    "private_material_storage_allowed": False,
}

SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(token|api[_-]?key|password|passwd|secret|private[_-]?key|credential|authorization|header|env)"
)
ENV_ASSIGNMENT_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\s*=\s*[^,\s;]+")
ADDITIONAL_SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
]
WORD_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}")


def _merge_contract(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            nested = copy.deepcopy(result[key])
            nested.update(value)
            result[key] = nested
        else:
            result[key] = copy.deepcopy(value)
    return result


def memory_contract(settings_path: Path | None = None) -> dict[str, Any]:
    path = settings_path or MODULE_SETTINGS
    contract = copy.deepcopy(DEFAULT_CONTRACT)
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return contract
    configured = settings.get("contract", {}) if isinstance(settings, dict) else {}
    if isinstance(configured, dict):
        return _merge_contract(contract, configured)
    return contract


def runtime_state_path(root: Path | str | None = None, contract: dict[str, Any] | None = None) -> Path:
    active_contract = contract or memory_contract()
    base = Path(root).resolve() if root else ROOT
    return base / str(active_contract["runtime_state_file"])


def redact_memory_text(value: Any) -> str:
    text = redact_sensitive_text(value)
    text = ENV_ASSIGNMENT_PATTERN.sub("[REDACTED_ENV]", text)
    for pattern in ADDITIONAL_SECRET_VALUE_PATTERNS:
        text = pattern.sub("[REDACTED_SECRET]", text)
    return text


def _limited_text(value: Any, limit: int) -> tuple[str, bool]:
    raw = str(value or "").strip()
    safe = redact_memory_text(raw).strip()
    redacted = safe != raw
    if len(safe) > limit:
        safe = safe[: max(0, limit - 3)].rstrip() + "..."
    return safe, redacted


def _safe_identifier(value: Any, limit: int = 96) -> tuple[str, bool]:
    safe, redacted = _limited_text(value, limit)
    safe = re.sub(r"[^A-Za-z0-9_.:@/-]+", "-", safe).strip("-")
    return safe[:limit], redacted


def _safe_list(value: Any, *, limit: int, item_limit: int = 64) -> tuple[list[str], bool]:
    items = value if isinstance(value, list) else [value] if value not in (None, "") else []
    result: list[str] = []
    redacted = False
    for item in items:
        safe, item_redacted = _safe_identifier(item, item_limit)
        redacted = redacted or item_redacted
        if safe and safe not in result:
            result.append(safe)
        if len(result) >= limit:
            break
    return result, redacted


def _safe_metadata(metadata: Any, contract: dict[str, Any]) -> tuple[dict[str, Any], bool, list[str]]:
    if not isinstance(metadata, dict):
        return {}, False, []
    allowed_keys = {str(item) for item in contract.get("safe_metadata_keys", [])}
    result: dict[str, Any] = {}
    redacted = False
    redacted_fields: list[str] = []
    for raw_key, raw_value in metadata.items():
        key, key_redacted = _safe_identifier(raw_key, 80)
        redacted = redacted or key_redacted
        if not key:
            continue
        if key not in allowed_keys or SENSITIVE_KEY_PATTERN.search(key):
            redacted = True
            redacted_fields.append(f"metadata.{key}")
            continue
        if isinstance(raw_value, (dict, list, tuple)):
            safe_value, value_redacted = _limited_text(json.dumps(raw_value, sort_keys=True), 240)
        else:
            safe_value, value_redacted = _limited_text(raw_value, 240)
        redacted = redacted or value_redacted
        if value_redacted:
            redacted_fields.append(f"metadata.{key}")
        result[key] = safe_value
    return result, redacted, sorted(set(redacted_fields))


def _tokenize(value: Any) -> list[str]:
    return [match.group(0).lower() for match in WORD_PATTERN.finditer(str(value or ""))]


def _derive_recall_keys(record: dict[str, Any], provided: list[str], contract: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for candidate in provided:
        for token in _tokenize(candidate):
            if token not in keys:
                keys.append(token)
    for field in ("record_id", "task_id", "root_task_id", "source", "title", "summary"):
        for token in _tokenize(record.get(field, "")):
            if token not in keys:
                keys.append(token)
    for tag in record.get("tags", []):
        for token in _tokenize(tag):
            if token not in keys:
                keys.append(token)
    return keys[: int(contract["max_recall_key_count"])]


def _record_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"mem-{digest}"


def sanitize_memory_record(record: dict[str, Any], contract: dict[str, Any] | None = None) -> dict[str, Any]:
    active_contract = contract or memory_contract()
    redacted_fields: list[str] = []
    redaction_applied = False

    title, redacted = _limited_text(record.get("title") or record.get("summary") or "Memory OS Record", int(active_contract["max_title_chars"]))
    redaction_applied = redaction_applied or redacted
    if redacted:
        redacted_fields.append("title")

    content_source = record.get("content", record.get("text", ""))
    content, redacted = _limited_text(content_source, int(active_contract["max_content_chars"]))
    redaction_applied = redaction_applied or redacted
    if redacted:
        redacted_fields.append("content")

    summary_source = record.get("summary") or content
    summary, redacted = _limited_text(summary_source, int(active_contract["max_summary_chars"]))
    redaction_applied = redaction_applied or redacted
    if redacted:
        redacted_fields.append("summary")

    tags, redacted = _safe_list(record.get("tags", []), limit=int(active_contract["max_tag_count"]))
    redaction_applied = redaction_applied or redacted
    if redacted:
        redacted_fields.append("tags")

    provided_recall_keys, redacted = _safe_list(
        record.get("recall_keys", []),
        limit=int(active_contract["max_recall_key_count"]),
    )
    redaction_applied = redaction_applied or redacted
    if redacted:
        redacted_fields.append("recall_keys")

    metadata, metadata_redacted, metadata_fields = _safe_metadata(record.get("metadata", {}), active_contract)
    redaction_applied = redaction_applied or metadata_redacted
    redacted_fields.extend(metadata_fields)

    created_at, redacted = _limited_text(record.get("created_at") or utc_now(), 40)
    redaction_applied = redaction_applied or redacted
    source, redacted = _safe_identifier(record.get("source") or metadata.get("source") or "memory_os", 80)
    redaction_applied = redaction_applied or redacted
    task_id, redacted = _safe_identifier(record.get("task_id") or metadata.get("task_id") or "", 120)
    redaction_applied = redaction_applied or redacted
    root_task_id, redacted = _safe_identifier(record.get("root_task_id") or metadata.get("root_task_id") or task_id, 120)
    redaction_applied = redaction_applied or redacted

    seed = "|".join([created_at, source, task_id, root_task_id, title, summary])
    record_id, redacted = _safe_identifier(record.get("record_id") or _record_id(seed), 120)
    redaction_applied = redaction_applied or redacted

    safe_record = {
        "schema_version": active_contract["record_schema_version"],
        "record_id": record_id,
        "created_at": created_at,
        "source": source,
        "task_id": task_id,
        "root_task_id": root_task_id,
        "title": title,
        "summary": summary,
        "content": content,
        "tags": tags,
        "metadata": metadata,
        "redaction": {
            "applied": bool(redaction_applied),
            "redacted_fields": sorted(set(redacted_fields)),
            "raw_payload_stored": False,
            "credential_values_stored": False,
            "environment_values_stored": False,
            "private_material_stored": False,
        },
    }
    safe_record["recall_keys"] = _derive_recall_keys(safe_record, provided_recall_keys, active_contract)
    return safe_record


def _empty_state(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": contract["state_schema_version"],
        "records": [],
        "record_count": 0,
        "raw_payload_storage_allowed": False,
        "credential_value_storage_allowed": False,
        "environment_value_storage_allowed": False,
        "private_material_storage_allowed": False,
    }


def load_memory_state(root: Path | str | None = None, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    active_contract = contract or memory_contract()
    path = runtime_state_path(root, active_contract)
    state = read_json(path, _empty_state(active_contract))
    if not isinstance(state, dict):
        return _empty_state(active_contract)
    state.setdefault("schema_version", active_contract["state_schema_version"])
    records = state.get("records", [])
    if not isinstance(records, list):
        records = []
    state["records"] = [item for item in records if isinstance(item, dict)]
    state["record_count"] = len(state["records"])
    state["raw_payload_storage_allowed"] = False
    state["credential_value_storage_allowed"] = False
    state["environment_value_storage_allowed"] = False
    state["private_material_storage_allowed"] = False
    return state


def append_memory_record(
    root: Path | str | None,
    record: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
    write_audit: bool = True,
) -> dict[str, Any]:
    active_contract = contract or memory_contract()
    path = runtime_state_path(root, active_contract)
    state = load_memory_state(root, active_contract)
    safe_record = sanitize_memory_record(record, active_contract)
    records = state.setdefault("records", [])
    records.append(safe_record)
    state["records"] = records[-int(active_contract["max_records"]) :]
    state["record_count"] = len(state["records"])
    state["last_record_id"] = safe_record["record_id"]
    state["last_record_at"] = safe_record["created_at"]
    atomic_write_json(path, state)

    if write_audit:
        append_audit(
            Path(root).resolve() if root else ROOT,
            "memory_os_record_stored",
            {
                "record_id": safe_record["record_id"],
                "source": safe_record["source"],
                "task_id": safe_record["task_id"],
                "root_task_id": safe_record["root_task_id"],
                "tag_count": len(safe_record["tags"]),
                "redaction_applied": safe_record["redaction"]["applied"],
                "raw_content_logged": False,
                "credential_values_logged": False,
            },
        )
    return safe_record


def build_memory_summary(
    records: list[dict[str, Any]],
    *,
    query: str = "",
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_contract = contract or memory_contract()
    safe_query, query_redacted = _limited_text(query, 240)
    items = []
    for record in records:
        if not isinstance(record, dict):
            continue
        items.append(
            {
                "record_id": record.get("record_id", ""),
                "created_at": record.get("created_at", ""),
                "source": record.get("source", ""),
                "task_id": record.get("task_id", ""),
                "root_task_id": record.get("root_task_id", ""),
                "title": record.get("title", ""),
                "summary": record.get("summary", ""),
                "tags": record.get("tags", []),
                "recall_keys": record.get("recall_keys", []),
                "redaction_applied": bool(record.get("redaction", {}).get("applied")),
            }
        )
    return {
        "schema_version": active_contract["summary_schema_version"],
        "generated_at": utc_now(),
        "query": safe_query,
        "record_count": len(items),
        "items": items,
        "query_redaction_applied": query_redacted,
        "raw_content_included": False,
        "raw_payload_included": False,
        "credential_values_included": False,
        "environment_values_included": False,
        "private_material_included": False,
    }


def recall_memory_records(
    records: list[dict[str, Any]],
    query: str,
    *,
    limit: int = 5,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_contract = contract or memory_contract()
    safe_query = redact_memory_text(query)
    terms = _tokenize(safe_query)
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for record in records:
        haystack = " ".join(
            [
                str(record.get("title", "")),
                str(record.get("summary", "")),
                str(record.get("content", "")),
                " ".join(str(item) for item in record.get("tags", [])),
                " ".join(str(item) for item in record.get("recall_keys", [])),
            ]
        ).lower()
        score = sum(2 if term in record.get("recall_keys", []) else 1 for term in terms if term in haystack)
        if score or not terms:
            scored.append((score, str(record.get("created_at", "")), record))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = [record for _score, _created_at, record in scored[: max(0, int(limit))]]
    return build_memory_summary(selected, query=query, contract=active_contract)


def recall_memory(
    root: Path | str | None,
    query: str,
    *,
    limit: int = 5,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_contract = contract or memory_contract()
    state = load_memory_state(root, active_contract)
    return recall_memory_records(state.get("records", []), query, limit=limit, contract=active_contract)


def build_memory_health_snapshot(root: Path | str | None = None, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    active_contract = contract or memory_contract()
    state = load_memory_state(root, active_contract)
    records = state.get("records", [])
    last = records[-1] if records else {}
    return {
        "module": "memory_os_runtime",
        "status": "active" if records else "empty",
        "schema_version": state.get("schema_version", active_contract["state_schema_version"]),
        "record_count": len(records),
        "last_record": {
            "record_id": last.get("record_id", ""),
            "created_at": last.get("created_at", ""),
            "title": last.get("title", ""),
            "summary": last.get("summary", ""),
            "tags": last.get("tags", []),
        },
        "runtime_state_file": str(active_contract["runtime_state_file"]),
        "raw_content_included": False,
        "credential_values_included": False,
        "environment_values_included": False,
        "private_material_included": False,
    }


def validate_contract(settings_path: Path | None = None) -> dict[str, Any]:
    contract = memory_contract(settings_path)
    required = [
        "state_schema_version",
        "record_schema_version",
        "summary_schema_version",
        "runtime_state_file",
        "max_records",
        "safe_metadata_keys",
    ]
    missing = [field for field in required if field not in contract]
    return {
        "ok": not missing
        and not contract.get("raw_payload_storage_allowed")
        and not contract.get("credential_value_storage_allowed")
        and not contract.get("environment_value_storage_allowed")
        and not contract.get("private_material_storage_allowed"),
        "missing_fields": missing,
        "runtime_state_file": contract.get("runtime_state_file"),
        "raw_payload_storage_allowed": bool(contract.get("raw_payload_storage_allowed")),
        "credential_value_storage_allowed": bool(contract.get("credential_value_storage_allowed")),
        "environment_value_storage_allowed": bool(contract.get("environment_value_storage_allowed")),
        "private_material_storage_allowed": bool(contract.get("private_material_storage_allowed")),
        "summary_schema_version": contract.get("summary_schema_version"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Memory OS runtime state helper")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-contract")
    validate.add_argument("--settings", default="")
    recall = sub.add_parser("recall")
    recall.add_argument("--root", default="")
    recall.add_argument("--query", default="")
    recall.add_argument("--limit", type=int, default=5)
    health = sub.add_parser("health")
    health.add_argument("--root", default="")
    args = parser.parse_args()

    if args.command == "validate-contract":
        settings = Path(args.settings) if args.settings else None
        result = validate_contract(settings)
    elif args.command == "recall":
        result = recall_memory(Path(args.root).resolve() if args.root else ROOT, args.query, limit=args.limit)
    else:
        result = build_memory_health_snapshot(Path(args.root).resolve() if args.root else ROOT)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
