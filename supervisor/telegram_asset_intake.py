#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import re
from typing import Any

DEFAULT_ALLOWED_DOCUMENT_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/plain",
    }
)
DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024
DEFAULT_CAPTION_MAX_CHARS = 1024
DEFAULT_FILE_NAME_MAX_CHARS = 120

MESSAGE_KEYS = ("message", "edited_message", "channel_post", "edited_channel_post")
UNSUPPORTED_MEDIA_FIELDS = (
    "animation",
    "audio",
    "sticker",
    "video",
    "video_note",
    "voice",
)

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
UNSAFE_FILE_NAME_CHARS = re.compile(r'[<>:"|?*]+')
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(token|api[_-]?key|password|passwd|secret|private[_-]?key)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
)


def stable_hash(value: Any, length: int = 16) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:length]


def safe_ref(value: Any, prefix: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return f"{prefix}_{stable_hash(raw, 16)}"


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def sanitize_text(value: Any, max_chars: int = DEFAULT_CAPTION_MAX_CHARS, *, escape_html: bool = True) -> str:
    text = CONTROL_CHARS.sub(" ", str(value or ""))
    for pattern in SENSITIVE_TEXT_PATTERNS:
        text = pattern.sub("[REDACTED_SECRET]", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) > max_chars:
        text = text[: max(0, max_chars - 14)].rstrip() + " [truncated]"
    return html.escape(text, quote=False) if escape_html else text


def sanitize_file_name(value: Any, max_chars: int = DEFAULT_FILE_NAME_MAX_CHARS) -> str:
    raw = CONTROL_CHARS.sub(" ", str(value or "")).replace("\\", "/")
    name = raw.rsplit("/", 1)[-1]
    name = UNSAFE_FILE_NAME_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" ._")
    if not name:
        name = "telegram_document"
    if len(name) <= max_chars:
        return name

    base, dot, ext = name.rpartition(".")
    if dot and 1 <= len(ext) <= 12:
        keep = max_chars - len(ext) - 1
        return (base[:keep].rstrip(" ._") or "telegram_document") + "." + ext
    return name[:max_chars].rstrip(" ._") or "telegram_document"


def policy_value(policy: dict[str, Any] | None, key: str, default: Any) -> Any:
    if not isinstance(policy, dict):
        return default
    return policy.get(key, default)


def base_event(update_id: Any, update_key: str, message: dict[str, Any]) -> dict[str, Any]:
    chat = message.get("chat", {}) if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from", {}) if isinstance(message.get("from"), dict) else {}
    return {
        "source": "telegram",
        "update_id": update_id,
        "update_key": update_key,
        "message_id": message.get("message_id"),
        "chat_id_hash": stable_hash(chat.get("id")) if chat.get("id") is not None else "",
        "from_user_hash": stable_hash(sender.get("id") or sender.get("username") or sender.get("first_name")),
        "raw_payload_logged": False,
        "download_deferred": True,
        "should_enqueue_asset": False,
    }


def reject_event(
    update_id: Any,
    update_key: str,
    message: dict[str, Any],
    reason: str,
    *,
    message_type: str = "rejected",
    asset_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = base_event(update_id, update_key, message)
    event.update(
        {
            "status": "rejected",
            "message_type": message_type,
            "asset_type": asset_type,
            "reject_reason": reason,
        }
    )
    if extra:
        event.update(extra)
    return event


def select_photo_variant(photos: Any) -> dict[str, Any] | None:
    if not isinstance(photos, list):
        return None
    variants = [item for item in photos if isinstance(item, dict)]
    if not variants:
        return None
    return max(
        variants,
        key=lambda item: (
            _positive_int(item.get("file_size")) or 0,
            (_positive_int(item.get("width")) or 0) * (_positive_int(item.get("height")) or 0),
        ),
    )


def _caption_metadata(message: dict[str, Any], policy: dict[str, Any] | None) -> dict[str, Any]:
    caption = message.get("caption", "")
    limit = int(policy_value(policy, "caption_max_chars", DEFAULT_CAPTION_MAX_CHARS))
    sanitized = sanitize_text(caption, max_chars=limit)
    return {
        "caption_present": bool(str(caption or "").strip()),
        "caption_sanitized": sanitized,
        "caption_length": len(str(caption or "")),
        "caption_truncated": len(str(caption or "")) > limit,
    }


def _file_size_ok(file_size: int | None, policy: dict[str, Any] | None) -> bool:
    max_bytes = int(policy_value(policy, "max_file_bytes", DEFAULT_MAX_FILE_BYTES))
    return file_size is None or file_size <= max_bytes


def classify_photo_message(
    update_id: Any,
    update_key: str,
    message: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    photo = select_photo_variant(message.get("photo"))
    if not photo:
        return reject_event(update_id, update_key, message, "photo_payload_invalid", message_type="photo", asset_type="photo")

    file_id = str(photo.get("file_id") or "").strip()
    file_unique_id = str(photo.get("file_unique_id") or "").strip()
    file_size = _positive_int(photo.get("file_size"))
    common = {
        "file_id_ref": safe_ref(file_id, "tg_file"),
        "file_unique_id": file_unique_id,
        "file_size": file_size,
        "mime_type": "image/jpeg",
        "file_name_sanitized": "",
        **_caption_metadata(message, policy),
    }
    if not file_id:
        return reject_event(update_id, update_key, message, "missing_file_id", message_type="photo", asset_type="photo", extra=common)
    if not file_unique_id:
        return reject_event(update_id, update_key, message, "missing_file_unique_id", message_type="photo", asset_type="photo", extra=common)
    if not _file_size_ok(file_size, policy):
        return reject_event(update_id, update_key, message, "file_size_limit_exceeded", message_type="photo", asset_type="photo", extra=common)

    event = base_event(update_id, update_key, message)
    event.update(
        {
            "status": "classified",
            "message_type": "media_with_caption" if common["caption_present"] else "photo",
            "asset_type": "photo",
            "should_enqueue_asset": True,
            "idempotency_key": f"{update_id}:{file_unique_id}",
            **common,
        }
    )
    return event


def classify_document_message(
    update_id: Any,
    update_key: str,
    message: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = message.get("document")
    if not isinstance(document, dict):
        return reject_event(update_id, update_key, message, "document_payload_invalid", message_type="document", asset_type="document")

    file_id = str(document.get("file_id") or "").strip()
    file_unique_id = str(document.get("file_unique_id") or "").strip()
    file_size = _positive_int(document.get("file_size"))
    mime_type = sanitize_text(document.get("mime_type", ""), max_chars=160, escape_html=False).lower()
    allowed_mimes = set(policy_value(policy, "allowed_document_mime_types", DEFAULT_ALLOWED_DOCUMENT_MIME_TYPES))
    common = {
        "file_id_ref": safe_ref(file_id, "tg_file"),
        "file_unique_id": file_unique_id,
        "file_size": file_size,
        "mime_type": mime_type,
        "file_name_sanitized": sanitize_file_name(document.get("file_name", "")),
        **_caption_metadata(message, policy),
    }
    if not file_id:
        return reject_event(update_id, update_key, message, "missing_file_id", message_type="document", asset_type="document", extra=common)
    if not file_unique_id:
        return reject_event(update_id, update_key, message, "missing_file_unique_id", message_type="document", asset_type="document", extra=common)
    if not _file_size_ok(file_size, policy):
        return reject_event(update_id, update_key, message, "file_size_limit_exceeded", message_type="document", asset_type="document", extra=common)
    if mime_type and mime_type not in allowed_mimes:
        return reject_event(update_id, update_key, message, "mime_type_not_allowed", message_type="document", asset_type="document", extra=common)

    event = base_event(update_id, update_key, message)
    event.update(
        {
            "status": "classified",
            "message_type": "media_with_caption" if common["caption_present"] else "document",
            "asset_type": "document",
            "should_enqueue_asset": True,
            "idempotency_key": f"{update_id}:{file_unique_id}",
            **common,
        }
    )
    return event


def classify_telegram_message(
    message: dict[str, Any],
    *,
    update_id: Any = None,
    update_key: str = "message",
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(message, dict):
        return reject_event(update_id, update_key, {}, "message_payload_invalid")

    if "photo" in message:
        return classify_photo_message(update_id, update_key, message, policy)
    if "document" in message:
        return classify_document_message(update_id, update_key, message, policy)

    for field in UNSUPPORTED_MEDIA_FIELDS:
        if field in message:
            return reject_event(
                update_id,
                update_key,
                message,
                "unsupported_media_type",
                message_type="unsupported",
                extra={"unsupported_media_type": field},
            )

    text = str(message.get("text") or "").strip()
    event = base_event(update_id, update_key, message)
    if text:
        event.update(
            {
                "status": "classified",
                "message_type": "text",
                "asset_type": None,
                "download_deferred": False,
                "text_length": len(text),
            }
        )
        return event

    return reject_event(update_id, update_key, message, "unsupported_message")


def classify_telegram_update(update: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(update, dict):
        return reject_event(None, "missing", {}, "update_payload_invalid")

    update_id = update.get("update_id")
    for key in MESSAGE_KEYS:
        message = update.get(key)
        if isinstance(message, dict):
            return classify_telegram_message(message, update_id=update_id, update_key=key, policy=policy)
    return reject_event(update_id, "missing", {}, "missing_message")


def is_media_intake_event(event: dict[str, Any]) -> bool:
    if not isinstance(event, dict):
        return False
    if event.get("should_enqueue_asset") is True:
        return True
    if event.get("asset_type") in {"photo", "document"}:
        return True
    return bool(event.get("unsupported_media_type"))


def asset_event_to_task_message(event: dict[str, Any]) -> str:
    keys = [
        "status",
        "message_type",
        "asset_type",
        "reject_reason",
        "update_id",
        "update_key",
        "message_id",
        "chat_id_hash",
        "file_id_ref",
        "file_unique_id",
        "file_size",
        "mime_type",
        "file_name_sanitized",
        "caption_present",
        "caption_sanitized",
        "idempotency_key",
        "download_deferred",
        "raw_payload_logged",
    ]
    lines = [
        "Telegram asset intake event",
        "File download, persistent storage, checksum and malware scan are deferred to the dedicated asset processing stage.",
    ]
    for key in keys:
        value = event.get(key)
        if value is None or value == "":
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines)
