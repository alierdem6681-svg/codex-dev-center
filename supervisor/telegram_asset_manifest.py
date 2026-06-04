#!/usr/bin/env python3
"""Network-free Telegram asset manifest contract validation."""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any


SCHEMA_VERSION = 1
MAX_TELEGRAM_DOWNLOAD_BYTES = 20 * 1024 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_KEY_FRAGMENTS = (
    "token",
    "secret",
    "credential",
    "api_key",
    "access_key",
    "password",
    "private_key",
    "authorization",
    "file_url",
    "download_url",
    "raw",
    "payload",
)

_REQUIRED_TOP_LEVEL = (
    "schema_version",
    "asset_id",
    "source",
    "received_at",
    "telegram",
    "original",
    "storage",
    "policy",
)

_REQUIRED_NESTED = {
    "telegram": ("chat_id_hash", "message_id", "file_id_hash", "file_unique_id", "file_size"),
    "original": ("filename", "declared_mime", "detected_mime", "size_bytes", "sha256"),
    "storage": ("backend", "bucket", "object_key", "sha256"),
    "policy": ("max_bytes", "download_allowed", "retention"),
}


class ManifestValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("Telegram asset manifest validation failed")
        self.errors = errors


def validate_manifest(manifest: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest: must be an object"]

    _reject_forbidden_keys(manifest, "manifest", errors)
    _require_fields(manifest, "manifest", _REQUIRED_TOP_LEVEL, errors)

    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("manifest.schema_version: must be 1")
    if manifest.get("source") != "telegram":
        errors.append("manifest.source: must be telegram")
    _expect_non_empty_string(manifest.get("asset_id"), "manifest.asset_id", errors)
    _expect_timestamp(manifest.get("received_at"), "manifest.received_at", errors)

    telegram = _expect_object(manifest.get("telegram"), "manifest.telegram", errors)
    original = _expect_object(manifest.get("original"), "manifest.original", errors)
    storage = _expect_object(manifest.get("storage"), "manifest.storage", errors)
    policy = _expect_object(manifest.get("policy"), "manifest.policy", errors)

    for path, value in (
        ("manifest.telegram", telegram),
        ("manifest.original", original),
        ("manifest.storage", storage),
        ("manifest.policy", policy),
    ):
        if value is not None:
            _require_fields(value, path, _REQUIRED_NESTED[path.rsplit(".", 1)[1]], errors)

    if telegram is not None:
        _expect_sha256(telegram.get("chat_id_hash"), "manifest.telegram.chat_id_hash", errors)
        _expect_int(telegram.get("message_id"), "manifest.telegram.message_id", errors, minimum=1)
        _expect_sha256(telegram.get("file_id_hash"), "manifest.telegram.file_id_hash", errors)
        _expect_non_empty_string(telegram.get("file_unique_id"), "manifest.telegram.file_unique_id", errors)
        _expect_int(
            telegram.get("file_size"),
            "manifest.telegram.file_size",
            errors,
            minimum=0,
            maximum=MAX_TELEGRAM_DOWNLOAD_BYTES,
        )

    if original is not None:
        _expect_non_empty_string(original.get("filename"), "manifest.original.filename", errors)
        _expect_non_empty_string(original.get("declared_mime"), "manifest.original.declared_mime", errors)
        _expect_non_empty_string(original.get("detected_mime"), "manifest.original.detected_mime", errors)
        _expect_int(
            original.get("size_bytes"),
            "manifest.original.size_bytes",
            errors,
            minimum=0,
            maximum=MAX_TELEGRAM_DOWNLOAD_BYTES,
        )
        _expect_sha256(original.get("sha256"), "manifest.original.sha256", errors)

    if storage is not None:
        _expect_non_empty_string(storage.get("backend"), "manifest.storage.backend", errors)
        bucket = storage.get("bucket")
        if bucket is not None:
            _expect_non_empty_string(bucket, "manifest.storage.bucket", errors)
        _expect_non_empty_string(storage.get("object_key"), "manifest.storage.object_key", errors)
        _expect_sha256(storage.get("sha256"), "manifest.storage.sha256", errors)

    if policy is not None:
        _expect_int(
            policy.get("max_bytes"),
            "manifest.policy.max_bytes",
            errors,
            minimum=1,
            maximum=MAX_TELEGRAM_DOWNLOAD_BYTES,
        )
        if not isinstance(policy.get("download_allowed"), bool):
            errors.append("manifest.policy.download_allowed: must be a boolean")
        _expect_non_empty_string(policy.get("retention"), "manifest.policy.retention", errors)

    _check_cross_field_consistency(telegram, original, storage, policy, errors)
    return errors


def assert_valid_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    errors = validate_manifest(manifest)
    if errors:
        raise ManifestValidationError(errors)
    return copy.deepcopy(manifest)


def _reject_forbidden_keys(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(fragment in key_text for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                errors.append(f"{path}.{key}: forbidden manifest key")
            _reject_forbidden_keys(child, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{path}[{index}]", errors)


def _require_fields(container: dict[str, Any], path: str, fields: tuple[str, ...], errors: list[str]) -> None:
    for field in fields:
        if field not in container:
            errors.append(f"{path}.{field}: required")


def _expect_object(value: Any, path: str, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return None
    return value


def _expect_non_empty_string(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: must be a non-empty string")


def _expect_int(
    value: Any,
    path: str,
    errors: list[str],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{path}: must be an integer")
        return
    if minimum is not None and value < minimum:
        errors.append(f"{path}: must be >= {minimum}")
    if maximum is not None and value > maximum:
        errors.append(f"{path}: must be <= {maximum}")


def _expect_sha256(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        errors.append(f"{path}: must be a lowercase sha256 hex digest")


def _expect_timestamp(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: must be an ISO-8601 timestamp")
        return
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{path}: must be an ISO-8601 timestamp")
        return
    if parsed.tzinfo is None:
        errors.append(f"{path}: timezone is required")


def _check_cross_field_consistency(
    telegram: dict[str, Any] | None,
    original: dict[str, Any] | None,
    storage: dict[str, Any] | None,
    policy: dict[str, Any] | None,
    errors: list[str],
) -> None:
    if original is not None and storage is not None:
        original_sha = original.get("sha256")
        storage_sha = storage.get("sha256")
        if isinstance(original_sha, str) and isinstance(storage_sha, str) and original_sha != storage_sha:
            errors.append("manifest.storage.sha256: must match manifest.original.sha256")

    if policy is None:
        return
    max_bytes = policy.get("max_bytes")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
        return

    if telegram is not None:
        file_size = telegram.get("file_size")
        if isinstance(file_size, int) and not isinstance(file_size, bool) and file_size > max_bytes:
            errors.append("manifest.telegram.file_size: must be <= manifest.policy.max_bytes")

    if original is not None:
        size_bytes = original.get("size_bytes")
        if isinstance(size_bytes, int) and not isinstance(size_bytes, bool) and size_bytes > max_bytes:
            errors.append("manifest.original.size_bytes: must be <= manifest.policy.max_bytes")
