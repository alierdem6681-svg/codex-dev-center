#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .task_status_constants import redact_sensitive_text
except ImportError:
    from task_status_constants import redact_sensitive_text


ROOT = Path(__file__).resolve().parents[1]
MODULE_SETTINGS = ROOT / "modules" / "telegram_asset_safety" / "settings.json"

DEFAULT_CONTRACT: dict[str, Any] = {
    "manifest_schema_version": "telegram_asset_manifest_v1",
    "max_asset_count": 10,
    "max_asset_bytes": 20 * 1024 * 1024,
    "max_total_bytes": 50 * 1024 * 1024,
    "max_caption_length": 1024,
    "max_filename_length": 160,
    "unknown_manifest_fields_policy": "reject",
    "unknown_asset_fields_policy": "reject",
    "real_telegram_fallback_allowed": False,
    "allowed_manifest_fields": [
        "schema_version",
        "batch_id",
        "asset_count",
        "caption",
        "assets",
    ],
    "required_asset_fields": [
        "id",
        "filename",
        "mime_type",
        "size_bytes",
        "sha256",
    ],
    "allowed_asset_fields": [
        "id",
        "filename",
        "mime_type",
        "size_bytes",
        "sha256",
        "caption",
        "metadata",
    ],
    "allowed_mime_extensions": {
        "image/jpeg": [".jpg", ".jpeg"],
        "image/png": [".png"],
        "image/webp": [".webp"],
        "application/pdf": [".pdf"],
        "text/plain": [".txt"],
    },
    "dangerous_extensions": [
        ".bat",
        ".cmd",
        ".com",
        ".exe",
        ".js",
        ".msi",
        ".ps1",
        ".sh",
    ],
}


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


def asset_safety_contract(settings_path: Path | None = None) -> dict[str, Any]:
    path = settings_path or MODULE_SETTINGS
    contract = copy.deepcopy(DEFAULT_CONTRACT)
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return contract
    configured = settings.get("contract", {}) if isinstance(settings, dict) else {}
    if isinstance(configured, dict):
        contract = _merge_contract(contract, configured)
    return contract


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_payload(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def _error(errors: list[dict[str, Any]], code: str, message: str, asset_id: Any = "") -> None:
    item = {
        "code": code,
        "message": redact_sensitive_text(message),
    }
    if asset_id:
        item["asset_id"] = redact_sensitive_text(asset_id)
    errors.append(item)


def _safe_filename(filename: str, contract: dict[str, Any]) -> bool:
    if not filename or len(filename) > int(contract["max_filename_length"]):
        return False
    normalized = filename.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute():
        return False
    if any(part in {"", ".", ".."} for part in path.parts):
        return False
    return len(path.parts) == 1


def _suffixes(filename: str) -> list[str]:
    return [suffix.lower() for suffix in PurePosixPath(filename).suffixes]


def _positive_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _valid_sha256(value: Any) -> bool:
    return bool(re.fullmatch(r"[a-fA-F0-9]{64}", str(value or "").strip()))


def validate_asset_manifest(
    manifest: dict[str, Any],
    asset_bytes_by_id: dict[str, bytes] | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_contract = contract or asset_safety_contract()
    errors: list[dict[str, Any]] = []
    asset_bytes = asset_bytes_by_id or {}

    if not isinstance(manifest, dict):
        _error(errors, "manifest_not_object", "Manifest must be a JSON object.")
        return _validation_result(False, errors, 0, 0)

    if manifest.get("schema_version") != active_contract["manifest_schema_version"]:
        _error(errors, "unsupported_schema_version", "Manifest schema version is not supported.")

    allowed_manifest_fields = set(active_contract["allowed_manifest_fields"])
    if active_contract.get("unknown_manifest_fields_policy") == "reject":
        for field in sorted(set(manifest) - allowed_manifest_fields):
            _error(errors, "unknown_manifest_field", f"Manifest field is not allowed: {field}")

    assets = manifest.get("assets")
    if not isinstance(assets, list):
        _error(errors, "assets_not_list", "Manifest assets must be a list.")
        return _validation_result(False, errors, 0, 0)

    declared_count = manifest.get("asset_count")
    if declared_count is not None and _positive_int(declared_count) != len(assets):
        _error(errors, "manifest_asset_count_mismatch", "Manifest asset_count does not match assets length.")

    max_caption_length = int(active_contract["max_caption_length"])
    caption = str(manifest.get("caption", ""))
    if len(caption) > max_caption_length:
        _error(errors, "caption_limit_exceeded", "Manifest caption exceeds configured length limit.")

    max_asset_count = int(active_contract["max_asset_count"])
    if len(assets) > max_asset_count:
        _error(errors, "asset_count_limit_exceeded", "Manifest has too many assets.")

    seen_ids: set[str] = set()
    total_size = 0
    accepted_count = 0

    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            _error(errors, "asset_not_object", f"Asset entry {index} must be an object.")
            continue
        asset_id = str(asset.get("id", "")).strip()
        _validate_asset_entry(asset, asset_id, seen_ids, asset_bytes, active_contract, errors)
        size = _positive_int(asset.get("size_bytes"))
        if size > 0:
            total_size += size
        if asset_id and asset_id not in seen_ids:
            accepted_count += 1
        if asset_id:
            seen_ids.add(asset_id)

    if total_size > int(active_contract["max_total_bytes"]):
        _error(errors, "total_size_limit_exceeded", "Manifest total asset bytes exceed configured limit.")

    return _validation_result(not errors, errors, accepted_count if not errors else 0, total_size)


def _validate_asset_entry(
    asset: dict[str, Any],
    asset_id: str,
    seen_ids: set[str],
    asset_bytes: dict[str, bytes],
    contract: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    for field in contract["required_asset_fields"]:
        if field not in asset or asset.get(field) in (None, ""):
            _error(errors, "missing_asset_field", f"Asset required field is missing: {field}", asset_id)

    if asset_id and asset_id in seen_ids:
        _error(errors, "duplicate_asset_id", "Asset id appears more than once.", asset_id)

    allowed_asset_fields = set(contract["allowed_asset_fields"])
    if contract.get("unknown_asset_fields_policy") == "reject":
        for field in sorted(set(asset) - allowed_asset_fields):
            _error(errors, "unknown_asset_field", f"Asset field is not allowed: {field}", asset_id)

    filename = str(asset.get("filename", "")).strip()
    if not _safe_filename(filename, contract):
        _error(errors, "unsafe_filename", "Asset filename is not a safe basename.", asset_id)

    suffixes = _suffixes(filename)
    final_suffix = suffixes[-1] if suffixes else ""
    dangerous = set(contract["dangerous_extensions"])
    if any(suffix in dangerous for suffix in suffixes[:-1]) or final_suffix in dangerous:
        _error(errors, "dangerous_extension", "Asset filename contains a dangerous extension.", asset_id)

    mime_type = str(asset.get("mime_type", "")).strip().lower()
    allowed_by_mime = contract["allowed_mime_extensions"]
    if mime_type not in allowed_by_mime:
        _error(errors, "unsupported_mime_type", "Asset MIME type is not allowed.", asset_id)
    elif final_suffix not in {str(item).lower() for item in allowed_by_mime[mime_type]}:
        _error(errors, "mime_extension_mismatch", "Asset extension does not match MIME type.", asset_id)

    size = _positive_int(asset.get("size_bytes"))
    if size <= 0:
        _error(errors, "empty_asset", "Asset size must be greater than zero.", asset_id)
    elif size > int(contract["max_asset_bytes"]):
        _error(errors, "asset_size_limit_exceeded", "Asset size exceeds configured limit.", asset_id)

    expected_sha = str(asset.get("sha256", "")).strip().lower()
    if not _valid_sha256(expected_sha):
        _error(errors, "invalid_sha256", "Asset sha256 must be a 64 character hex digest.", asset_id)
    elif asset_id in asset_bytes:
        actual_sha = hashlib.sha256(asset_bytes[asset_id]).hexdigest()
        if actual_sha != expected_sha:
            _error(errors, "checksum_mismatch", "Asset checksum does not match manifest.", asset_id)


def _validation_result(ok: bool, errors: list[dict[str, Any]], accepted_count: int, total_size: int) -> dict[str, Any]:
    return {
        "ok": ok,
        "accepted_asset_count": accepted_count,
        "total_size_bytes": total_size,
        "errors": _redact_payload(errors),
        "real_telegram_fallback_allowed": False,
    }


class TelegramAssetSendSimulator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._idempotency_results: dict[str, dict[str, Any]] = {}

    def send_media_group(
        self,
        payload: dict[str, Any],
        *,
        scenario: str = "success",
        idempotency_key: str | None = None,
        retry_after_seconds: int = 3,
    ) -> dict[str, Any]:
        if idempotency_key and idempotency_key in self._idempotency_results:
            result = copy.deepcopy(self._idempotency_results[idempotency_key])
            result["duplicate_suppressed"] = True
            result["network_performed"] = False
            return result

        safe_payload = _redact_payload(payload)
        self.calls.append(
            {
                "transport": "simulator",
                "scenario": scenario,
                "payload": safe_payload,
                "network_performed": False,
            }
        )
        result = self._scenario_result(scenario, retry_after_seconds)
        if idempotency_key:
            self._idempotency_results[idempotency_key] = copy.deepcopy(result)
        return result

    def _scenario_result(self, scenario: str, retry_after_seconds: int) -> dict[str, Any]:
        base = {
            "transport": "simulator",
            "network_performed": False,
            "real_telegram_fallback_allowed": False,
            "duplicate_suppressed": False,
        }
        if scenario == "success":
            return {**base, "ok": True, "message_id": f"simulated-message-{len(self.calls)}", "retryable": False}
        if scenario == "bad_request":
            return {**base, "ok": False, "status_code": 400, "error_code": "bad_request", "retryable": False}
        if scenario == "unauthorized":
            return {**base, "ok": False, "status_code": 401, "error_code": "unauthorized", "retryable": False}
        if scenario == "forbidden":
            return {**base, "ok": False, "status_code": 403, "error_code": "forbidden", "retryable": False}
        if scenario == "rate_limit":
            return {
                **base,
                "ok": False,
                "status_code": 429,
                "error_code": "rate_limit",
                "retryable": True,
                "retry_after_seconds": retry_after_seconds,
            }
        if scenario == "server_error":
            return {**base, "ok": False, "status_code": 500, "error_code": "server_error", "retryable": True}
        if scenario == "timeout":
            return {**base, "ok": False, "error_code": "timeout", "retryable": True}
        return {**base, "ok": False, "error_code": "unknown_simulator_scenario", "retryable": False}


def build_dashboard_asset_snapshot(
    validation_result: dict[str, Any],
    simulator_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    simulator = simulator_result or {}
    errors = validation_result.get("errors", [])
    status = "accepted" if validation_result.get("ok") else "rejected"
    return {
        "status": status,
        "asset_count": int(validation_result.get("accepted_asset_count") or 0),
        "error_count": len(errors) if isinstance(errors, list) else 0,
        "errors": _redact_payload(errors),
        "telegram_transport": simulator.get("transport", "simulator"),
        "telegram_network_performed": False,
        "real_telegram_fallback_allowed": False,
        "raw_payload_included": False,
    }
