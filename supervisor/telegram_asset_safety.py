#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

try:
    from .task_status_constants import redact_sensitive_text
except ImportError:
    from task_status_constants import redact_sensitive_text


MANIFEST_VERSION = 1
ALLOWED_MIME_EXTENSIONS = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "application/pdf": {".pdf"},
    "text/plain": {".txt"},
}
SENSITIVE_KEY_PARTS = ("token", "secret", "password", "passwd", "api_key", "private_key")
MANIFEST_KEYS = {"version", "assets"}
MANIFEST_ASSET_KEYS = {"id", "path", "mime_type", "size_bytes", "sha256"}


@dataclass(frozen=True)
class TelegramAssetPolicy:
    max_asset_count: int = 10
    max_manifest_entries: int = 10
    max_single_asset_bytes: int = 10 * 1024 * 1024
    max_total_package_bytes: int = 25 * 1024 * 1024
    max_caption_chars: int = 1024


DEFAULT_POLICY = TelegramAssetPolicy()


def _error(code: str, message: str, asset_id: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": redact_sensitive_text(message)}
    if asset_id:
        item["asset_id"] = asset_id
    return item


def _asset_id(asset: dict[str, Any]) -> str:
    return str(asset.get("id") or "").strip()


def is_safe_asset_path(path_value: Any) -> bool:
    raw = str(path_value or "").strip()
    if not raw or "\x00" in raw or "\\" in raw or raw.startswith("/"):
        return False
    path = PurePosixPath(raw)
    return ".." not in path.parts and all(part not in {"", "."} for part in path.parts)


def _extension_matches_mime(path_value: Any, mime_type: Any) -> bool:
    suffix = PurePosixPath(str(path_value or "")).suffix.lower()
    return suffix in ALLOWED_MIME_EXTENSIONS.get(str(mime_type or "").lower(), set())


def _valid_sha256(value: Any) -> bool:
    raw = str(value or "").strip().lower()
    return len(raw) == 64 and all(char in "0123456789abcdef" for char in raw)


def _coerce_size(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _validate_assets(assets: list[dict[str, Any]], policy: TelegramAssetPolicy) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total_size = 0

    if len(assets) > policy.max_asset_count:
        errors.append(_error("asset_count_limit_exceeded", "Asset count exceeds configured package limit."))

    for asset in assets:
        asset_id = _asset_id(asset)
        if not asset_id:
            errors.append(_error("asset_id_missing", "Asset id is required."))
        elif asset_id in seen_ids:
            errors.append(_error("duplicate_asset_id", "Asset id is duplicated.", asset_id))
        seen_ids.add(asset_id)

        path = asset.get("path")
        if not is_safe_asset_path(path):
            errors.append(_error("unsafe_asset_path", "Asset path must be a safe relative path.", asset_id or None))

        mime_type = str(asset.get("mime_type") or "").lower()
        if mime_type not in ALLOWED_MIME_EXTENSIONS:
            errors.append(_error("unsupported_mime_type", "Asset MIME type is not allowed.", asset_id or None))
        elif not _extension_matches_mime(path, mime_type):
            errors.append(_error("mime_extension_mismatch", "Asset extension does not match MIME type.", asset_id or None))

        size_bytes = _coerce_size(asset.get("size_bytes"))
        if size_bytes <= 0:
            errors.append(_error("asset_empty_or_invalid_size", "Asset size must be positive.", asset_id or None))
        elif size_bytes > policy.max_single_asset_bytes:
            errors.append(_error("asset_size_limit_exceeded", "Asset size exceeds configured single-file limit.", asset_id or None))
        total_size += max(0, size_bytes)

        if len(str(asset.get("caption") or "")) > policy.max_caption_chars:
            errors.append(_error("caption_limit_exceeded", "Asset caption exceeds configured caption limit.", asset_id or None))

        checksum = asset.get("sha256")
        if checksum is not None and not _valid_sha256(checksum):
            errors.append(_error("asset_checksum_invalid", "Asset checksum must be a SHA-256 hex digest.", asset_id or None))

    if total_size > policy.max_total_package_bytes:
        errors.append(_error("package_size_limit_exceeded", "Total asset package size exceeds configured limit."))

    return errors


def _validate_manifest(
    manifest: dict[str, Any],
    assets_by_id: dict[str, dict[str, Any]],
    policy: TelegramAssetPolicy,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    unknown_keys = set(manifest) - MANIFEST_KEYS
    for key in sorted(unknown_keys):
        errors.append(_error("manifest_unknown_field", f"Manifest field is not allowed: {key}"))

    if manifest.get("version") != MANIFEST_VERSION:
        errors.append(_error("manifest_version_unsupported", "Manifest version is unsupported."))

    entries = manifest.get("assets")
    if not isinstance(entries, list):
        return errors + [_error("manifest_assets_invalid", "Manifest assets must be a list.")]
    if len(entries) > policy.max_manifest_entries:
        errors.append(_error("manifest_entry_limit_exceeded", "Manifest entry count exceeds configured limit."))

    seen_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(_error("manifest_entry_invalid", "Manifest entry must be an object."))
            continue
        asset_id = _asset_id(entry)
        if not asset_id:
            errors.append(_error("manifest_asset_id_missing", "Manifest asset id is required."))
            continue
        if asset_id in seen_ids:
            errors.append(_error("manifest_duplicate_asset_id", "Manifest asset id is duplicated.", asset_id))
        seen_ids.add(asset_id)

        unknown_entry_keys = set(entry) - MANIFEST_ASSET_KEYS
        for key in sorted(unknown_entry_keys):
            errors.append(_error("manifest_entry_unknown_field", f"Manifest asset field is not allowed: {key}", asset_id))

        asset = assets_by_id.get(asset_id)
        if not asset:
            errors.append(_error("manifest_asset_missing", "Manifest references an unknown asset.", asset_id))
            continue
        for key in ("path", "mime_type", "size_bytes", "sha256"):
            if key in entry and str(entry.get(key)) != str(asset.get(key)):
                errors.append(_error(f"manifest_{key}_mismatch", "Manifest asset metadata does not match intake metadata.", asset_id))

    missing_manifest_ids = set(assets_by_id) - seen_ids
    for asset_id in sorted(missing_manifest_ids):
        errors.append(_error("manifest_asset_omitted", "Asset is missing from manifest.", asset_id))

    return errors


def validate_asset_package(
    assets: list[dict[str, Any]],
    manifest: dict[str, Any],
    policy: TelegramAssetPolicy = DEFAULT_POLICY,
) -> dict[str, Any]:
    asset_copies = [copy.deepcopy(asset) for asset in assets if isinstance(asset, dict)]
    assets_by_id = {_asset_id(asset): asset for asset in asset_copies if _asset_id(asset)}
    errors = _validate_assets(asset_copies, policy)
    errors.extend(_validate_manifest(copy.deepcopy(manifest), assets_by_id, policy))
    total_size = sum(max(0, _coerce_size(asset.get("size_bytes"), 0)) for asset in asset_copies)
    return {
        "ok": not errors,
        "asset_count": len(asset_copies),
        "manifest_entry_count": len(manifest.get("assets") or []) if isinstance(manifest.get("assets"), list) else 0,
        "total_size_bytes": total_size,
        "errors": errors,
        "external_call_performed": False,
    }


def redact_asset_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower().replace("-", "_")
            if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
                redacted[key] = "[REDACTED_SECRET]"
            else:
                redacted[key] = redact_asset_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_asset_payload(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def simulate_telegram_asset_send(validation: dict[str, Any], scenario: str = "success") -> dict[str, Any]:
    base = {
        "external_call_performed": False,
        "scenario": scenario,
        "asset_count": validation.get("asset_count", 0),
    }
    if not validation.get("ok"):
        return {
            **base,
            "ok": False,
            "status": "rejected",
            "retryable": False,
            "user_message": "Asset package rejected by safety policy.",
            "log_payload": redact_asset_payload({"errors": validation.get("errors", [])}),
        }
    if scenario == "success":
        return {**base, "ok": True, "status": "sent", "retryable": False, "user_message": "Asset package accepted."}
    if scenario == "rate_limit":
        return {**base, "ok": False, "status": "rate_limited", "retryable": True, "retry_after_seconds": 30}
    if scenario == "timeout":
        return {**base, "ok": False, "status": "timeout", "retryable": True, "retry_after_seconds": 10}
    if scenario == "unauthorized":
        return {**base, "ok": False, "status": "unauthorized", "retryable": False}
    return {**base, "ok": False, "status": "unknown_simulation", "retryable": False}


def dashboard_asset_summary(
    assets: list[dict[str, Any]],
    validation: dict[str, Any],
    max_caption_preview_chars: int = 80,
) -> dict[str, Any]:
    rows = []
    for asset in assets:
        checksum = str(asset.get("sha256") or "")
        caption = redact_sensitive_text(str(asset.get("caption") or ""))[:max_caption_preview_chars]
        rows.append(
            {
                "id": _asset_id(asset),
                "path": str(asset.get("path") or ""),
                "mime_type": str(asset.get("mime_type") or ""),
                "size_bytes": max(0, _coerce_size(asset.get("size_bytes"), 0)),
                "sha256_prefix": checksum[:12],
                "caption_preview": caption,
            }
        )
    return redact_asset_payload(
        {
            "read_only": True,
            "ok": bool(validation.get("ok")),
            "asset_count": validation.get("asset_count", len(assets)),
            "total_size_bytes": validation.get("total_size_bytes", 0),
            "assets": rows,
            "errors": validation.get("errors", []),
            "raw_file_content_included": False,
            "external_call_performed": False,
            "summary_id": hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()[:16],
        }
    )
