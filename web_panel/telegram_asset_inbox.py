#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs


DEFAULT_LIMIT = 50
MAX_LIMIT = 100
CAPTION_FULL_LIMIT = 5000
CAPTION_PREVIEW_LIMIT = 140
SAFE_REFERENCE_PREFIX = "tgref_"

SOURCE_PATHS = (
    "state/telegram_asset_inbox.json",
    "state/telegram_assets.json",
    "state/telegram_asset_manifest.json",
    "state/telegram_assets_manifest.json",
    "state/telegram_asset_inbox/manifest.json",
    "state/telegram_assets/manifest.json",
    "state/telegram_asset_inbox.ndjson",
    "state/telegram_assets.ndjson",
)

SOURCE_TYPES = {"channel", "group", "bot", "direct", "unknown"}
MEDIA_TYPES = {"image", "video", "document", "audio", "unknown"}
STATUSES = {"received", "indexed", "rejected", "quarantined"}

SAFE_LIST_KEYS = (
    "asset_id",
    "received_at",
    "source_type",
    "media_type",
    "file_name",
    "mime_type",
    "size_bytes",
    "caption_preview",
    "status",
    "safe_reference",
)

SAFE_DETAIL_KEYS = SAFE_LIST_KEYS + (
    "caption_full",
    "telegram_message_at",
    "redaction_flags",
    "ingestion_trace_id",
    "rejection_reason",
)

RAW_TELEGRAM_KEY_PARTS = (
    "file_id",
    "chat_id",
    "raw_message",
    "raw_payload",
    "payload",
)

DOWNLOAD_OR_SECRET_KEY_PARTS = (
    "bot_token",
    "token",
    "secret",
    "private_key",
    "credential",
    "signed_url",
    "download_url",
    "file_url",
)

STORAGE_KEY_PARTS = (
    "storage_path",
    "storage_url",
    "file_path",
    "bucket",
    "object_key",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_text(value: Any, limit: int = 400) -> str:
    text = str(value or "")
    normalized: list[str] = []
    for char in unicodedata.normalize("NFKC", text):
        if char in {"\n", "\t"}:
            normalized.append(char)
        elif unicodedata.category(char).startswith("C"):
            normalized.append(" ")
        else:
            normalized.append(char)
    return "".join(normalized).strip()[:limit]


def _compact_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", _safe_text(value, CAPTION_FULL_LIMIT)).strip()
    return text[:limit]


def _safe_choice(value: Any, allowed: set[str], default: str = "unknown") -> str:
    cleaned = _safe_text(value, 40).lower()
    return cleaned if cleaned in allowed else default


def _safe_status(value: Any) -> str:
    cleaned = _safe_text(value, 40).lower()
    return cleaned if cleaned in STATUSES else "received"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _safe_iso(value: Any) -> str:
    return _safe_text(value, 80)


def _sort_time(value: str) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _nested_get(record: dict[str, Any], dotted_key: str) -> Any:
    value: Any = record
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _first(record: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = _nested_get(record, key) if "." in key else record.get(key)
        if value not in (None, ""):
            return value
    return default


def _fallback_id(record: dict[str, Any]) -> str:
    seed = "|".join(
        str(_first(record, key, default=""))
        for key in (
            "received_at",
            "telegram_message_at",
            "file_name",
            "original.filename",
            "mime_type",
            "original.detected_mime",
            "size_bytes",
            "original.size_bytes",
            "caption_text",
        )
    )
    digest = sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:14]
    return f"ast_{digest}"


def _safe_reference(record: dict[str, Any], asset_id: str, received_at: str) -> str:
    explicit = _safe_text(_first(record, "safe_reference", "safe_ref", default=""), 120)
    if explicit.startswith(SAFE_REFERENCE_PREFIX):
        return explicit
    digest = sha256(f"{asset_id}|{received_at}".encode("utf-8", errors="replace")).hexdigest()[:14].upper()
    return f"{SAFE_REFERENCE_PREFIX}{digest}"


def _all_key_names(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append(str(key).lower())
            keys.extend(_all_key_names(child))
    elif isinstance(value, list):
        for child in value:
            keys.extend(_all_key_names(child))
    return keys


def _redaction_flags(record: dict[str, Any]) -> list[str]:
    keys = _all_key_names(record)
    flags: list[str] = []
    if any(part in key for key in keys for part in RAW_TELEGRAM_KEY_PARTS):
        flags.append("raw_telegram_fields_redacted")
    if any(part in key for key in keys for part in STORAGE_KEY_PARTS):
        flags.append("storage_reference_redacted")
    if any(part in key for key in keys for part in DOWNLOAD_OR_SECRET_KEY_PARTS):
        flags.append("download_or_secret_reference_redacted")
    for value in record.get("redaction_flags") or []:
        cleaned = _safe_text(value, 80)
        if cleaned and cleaned not in flags:
            flags.append(cleaned)
    return flags


def _infer_media_type(mime_type: str) -> str:
    prefix = mime_type.split("/", 1)[0].lower()
    if prefix in {"image", "video", "audio"}:
        return prefix
    if mime_type:
        return "document"
    return "unknown"


def sanitize_asset_record(record: dict[str, Any]) -> dict[str, Any]:
    asset_id = _safe_text(_first(record, "asset_id", "id", default=""), 120) or _fallback_id(record)
    received_at = _safe_iso(_first(record, "received_at", "created_at", "ingested_at", default=""))
    caption_full = _safe_text(
        _first(record, "caption_full", "caption_text", "caption", "text", default=""),
        CAPTION_FULL_LIMIT,
    )
    mime_type = _safe_text(
        _first(record, "mime_type", "content_type", "original.detected_mime", "original.declared_mime", default=""),
        120,
    )
    media_type = _safe_choice(_first(record, "media_type", "type", default=""), MEDIA_TYPES)
    if media_type == "unknown":
        media_type = _infer_media_type(mime_type)
    sanitized = {
        "asset_id": asset_id,
        "received_at": received_at,
        "source_type": _safe_choice(_first(record, "source_type", "source_kind", default="unknown"), SOURCE_TYPES),
        "media_type": media_type,
        "file_name": _safe_text(_first(record, "file_name", "filename", "name", "original.filename", default=""), 240),
        "mime_type": mime_type,
        "size_bytes": _safe_int(_first(record, "size_bytes", "file_size", "size", "original.size_bytes", "telegram.file_size", default=0)),
        "caption_preview": _compact_text(
            _first(record, "caption_preview", "caption_full", "caption_text", "caption", "text", default=""),
            CAPTION_PREVIEW_LIMIT,
        ),
        "status": _safe_status(_first(record, "status", "ingestion_status", default="received")),
        "safe_reference": _safe_reference(record, asset_id, received_at),
        "caption_full": caption_full,
        "telegram_message_at": _safe_iso(_first(record, "telegram_message_at", "message_at", "date", default="")),
        "redaction_flags": _redaction_flags(record),
        "ingestion_trace_id": _safe_text(_first(record, "ingestion_trace_id", "trace_id", default=""), 160),
        "rejection_reason": _safe_text(_first(record, "rejection_reason", "error_code", "last_error_code", default=""), 260),
    }
    return {key: sanitized[key] for key in SAFE_DETAIL_KEYS}


def _read_json(path: Path) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return None


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                records.append(payload)
    except Exception:
        return []
    return records


def _looks_like_asset_record(payload: dict[str, Any]) -> bool:
    if "asset_id" in payload or "id" in payload:
        return True
    return all(key in payload for key in ("telegram", "original", "storage"))


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "assets", "records", "telegram_assets"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if _looks_like_asset_record(payload):
        return [payload]
    return []


def load_asset_records(root: Path) -> tuple[list[dict[str, Any]], str | None]:
    for rel_path in SOURCE_PATHS:
        path = root / rel_path
        if not path.exists():
            continue
        records = _read_ndjson(path) if path.suffix == ".ndjson" else _extract_records(_read_json(path))
        return records, rel_path
    return [], None


def _parse_query(query_string: str | dict[str, list[str]] | None) -> dict[str, list[str]]:
    if isinstance(query_string, dict):
        return query_string
    return parse_qs(str(query_string or ""), keep_blank_values=False)


def _query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or []
    return str(values[0]) if values else ""


def _parse_limit(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return min(MAX_LIMIT, max(1, value))


def _parse_cursor(raw: str) -> int:
    text = str(raw or "").strip()
    if text.startswith("offset_"):
        text = text.removeprefix("offset_")
    try:
        return max(0, int(text))
    except ValueError:
        return 0


def _matches_filters(asset: dict[str, Any], query: dict[str, list[str]]) -> bool:
    media_type = _query_value(query, "media_type").lower()
    status = _query_value(query, "status").lower()
    source_type = _query_value(query, "source_type").lower()
    mime_type = _query_value(query, "mime_type").lower()
    date_from = _query_value(query, "from")
    date_to = _query_value(query, "to")
    search = _query_value(query, "q").lower()

    if media_type and asset.get("media_type") != media_type:
        return False
    if status and asset.get("status") != status:
        return False
    if source_type and asset.get("source_type") != source_type:
        return False
    if mime_type and mime_type not in str(asset.get("mime_type", "")).lower():
        return False
    if date_from and asset.get("received_at") and _sort_time(asset["received_at"]) < _sort_time(date_from):
        return False
    if date_to and asset.get("received_at") and _sort_time(asset["received_at"]) > _sort_time(date_to):
        return False
    if search:
        haystack = " ".join(
            str(asset.get(key, ""))
            for key in ("asset_id", "safe_reference", "file_name", "mime_type", "caption_preview", "caption_full")
        ).lower()
        if search not in haystack:
            return False
    return True


def _security_payload(keys: tuple[str, ...]) -> dict[str, Any]:
    return {
        "dto_allowlist": list(keys),
        "raw_telegram_fields_returned": False,
        "storage_references_returned": False,
        "mutating_actions": [],
    }


def build_telegram_asset_list(root: Path, query_string: str | dict[str, list[str]] | None = None) -> dict[str, Any]:
    query = _parse_query(query_string)
    limit = _parse_limit(_query_value(query, "limit"))
    cursor = _parse_cursor(_query_value(query, "cursor"))
    records, source = load_asset_records(Path(root))
    sanitized = [sanitize_asset_record(record) for record in records]
    filtered = [asset for asset in sanitized if _matches_filters(asset, query)]
    filtered.sort(key=lambda asset: (_sort_time(asset.get("received_at", "")), asset.get("asset_id", "")), reverse=True)
    page = filtered[cursor:cursor + limit]
    next_offset = cursor + limit
    return {
        "ok": True,
        "generated_at": utc_now(),
        "read_only": True,
        "source": source,
        "items": [{key: asset[key] for key in SAFE_LIST_KEYS} for asset in page],
        "next_cursor": f"offset_{next_offset}" if next_offset < len(filtered) else None,
        "limit": limit,
        "total_filtered": len(filtered),
        "security": _security_payload(SAFE_LIST_KEYS),
    }


def build_telegram_asset_detail(root: Path, asset_id: str) -> tuple[dict[str, Any], int]:
    target = _safe_text(asset_id, 120)
    records, source = load_asset_records(Path(root))
    for record in records:
        asset = sanitize_asset_record(record)
        if asset["asset_id"] == target:
            return {
                "ok": True,
                "generated_at": utc_now(),
                "read_only": True,
                "source": source,
                "item": {key: asset[key] for key in SAFE_DETAIL_KEYS},
                "security": _security_payload(SAFE_DETAIL_KEYS),
            }, 200
    return {
        "ok": False,
        "error": "asset_not_found",
        "read_only": True,
    }, 404
