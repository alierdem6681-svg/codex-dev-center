#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

APP = Path(os.environ.get("CODEX_DEV_CENTER_HOME", "/opt/codex-dev-center"))
DEFAULT_INBOX_ROOT = APP / "state" / "telegram_assets" / "inbox"
TELEGRAM_BOT_API_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_CHUNK_SIZE = 1024 * 1024
MIME_SAMPLE_BYTES = 512


class TelegramAssetError(Exception):
    def __init__(self, reason: str, detail: Any | None = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = sanitize_telegram_asset_error(detail) if detail is not None else ""

    def __str__(self) -> str:
        return self.reason


class AssetRejected(TelegramAssetError):
    pass


@dataclass(frozen=True)
class TelegramAssetMetadata:
    kind: str
    file_id: str
    file_unique_id: str | None = None
    file_name: str | None = None
    declared_mime: str | None = None
    file_size: int | None = None
    chat_id: str | None = None
    message_id: int | None = None


@dataclass(frozen=True)
class StoredTelegramAsset:
    asset_id: str
    asset_dir: Path
    blob_path: Path
    manifest_path: Path
    manifest: dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _positive_int(value: Any, default: int | None = None) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _env_max_bytes(env: dict[str, str] | os._Environ[str]) -> int:
    requested = _positive_int(env.get("TELEGRAM_ASSET_MAX_BYTES"), TELEGRAM_BOT_API_MAX_DOWNLOAD_BYTES)
    if requested is None or requested <= 0:
        return TELEGRAM_BOT_API_MAX_DOWNLOAD_BYTES
    return min(requested, TELEGRAM_BOT_API_MAX_DOWNLOAD_BYTES)


def _env_allowed_mime(env: dict[str, str] | os._Environ[str]) -> frozenset[str] | None:
    raw = str(env.get("TELEGRAM_ASSET_ALLOWED_MIME", "") or "").strip()
    if not raw:
        return None
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return frozenset(values) or None


@dataclass(frozen=True)
class AssetLimitPolicy:
    max_bytes: int = TELEGRAM_BOT_API_MAX_DOWNLOAD_BYTES
    allowed_mime_types: frozenset[str] | None = None

    def __post_init__(self) -> None:
        max_bytes = max(1, min(int(self.max_bytes), TELEGRAM_BOT_API_MAX_DOWNLOAD_BYTES))
        object.__setattr__(self, "max_bytes", max_bytes)
        if self.allowed_mime_types is not None:
            allowed = frozenset(str(item).strip().lower() for item in self.allowed_mime_types if str(item).strip())
            object.__setattr__(self, "allowed_mime_types", allowed or None)

    @classmethod
    def from_env(cls, env: dict[str, str] | os._Environ[str] | None = None) -> "AssetLimitPolicy":
        source = os.environ if env is None else env
        return cls(max_bytes=_env_max_bytes(source), allowed_mime_types=_env_allowed_mime(source))

    def check_declared_size(self, size: int | None) -> None:
        if size is not None and size > self.max_bytes:
            raise AssetRejected("file_size_limit_exceeded")

    def check_content_length(self, content_length: int | None) -> None:
        if content_length is not None and content_length > self.max_bytes:
            raise AssetRejected("content_length_limit_exceeded")

    def check_stream_total(self, total: int) -> None:
        if total > self.max_bytes:
            raise AssetRejected("stream_size_limit_exceeded")

    def check_mime(self, declared_mime: str | None, detected_mime: str | None) -> None:
        if not self.allowed_mime_types:
            return
        effective = (detected_mime or declared_mime or "").lower()
        if effective == "application/octet-stream" and declared_mime:
            effective = declared_mime.lower()
        if effective not in self.allowed_mime_types:
            raise AssetRejected("mime_not_allowed")


def safe_display_filename(value: Any, limit: int = 240) -> str | None:
    raw = str(value or "")
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", raw)
    cleaned = cleaned.replace("/", "_").replace("\\", "_").strip()
    if not cleaned:
        return None
    return cleaned[:limit]


def hash_chat_id(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sanitize_telegram_asset_error(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"https://api\.telegram\.org/file/bot[^\s\"')]+", "[TELEGRAM_FILE_URL_REDACTED]", text)
    text = re.sub(r"https://api\.telegram\.org/bot[^\s\"')/]+", "[TELEGRAM_BOT_API_REDACTED]", text)
    text = re.sub(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b", "[TELEGRAM_BOT_TOKEN_REDACTED]", text)
    return text


def detect_mime(sample: bytes, fallback: str | None = None) -> str:
    data = sample or b""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"PK\x03\x04"):
        return "application/zip"
    if data and all(byte in b"\t\n\r" or 32 <= byte <= 126 for byte in data[:128]):
        return "text/plain"
    return fallback or "application/octet-stream"


def _message_chat_id(message: dict[str, Any]) -> str | None:
    chat = message.get("chat") if isinstance(message, dict) else None
    if not isinstance(chat, dict):
        return None
    value = chat.get("id")
    return str(value) if value is not None else None


def _message_id(message: dict[str, Any]) -> int | None:
    parsed = _positive_int(message.get("message_id"))
    return int(parsed) if parsed is not None else None


def _metadata_from_payload(kind: str, payload: dict[str, Any], message: dict[str, Any]) -> TelegramAssetMetadata | None:
    file_id = str(payload.get("file_id") or "").strip()
    if not file_id:
        return None
    return TelegramAssetMetadata(
        kind=kind,
        file_id=file_id,
        file_unique_id=str(payload.get("file_unique_id") or "").strip() or None,
        file_name=safe_display_filename(payload.get("file_name")),
        declared_mime=str(payload.get("mime_type") or "").strip() or None,
        file_size=_positive_int(payload.get("file_size")),
        chat_id=_message_chat_id(message),
        message_id=_message_id(message),
    )


def _photo_metadata(message: dict[str, Any]) -> TelegramAssetMetadata | None:
    photos = message.get("photo")
    if not isinstance(photos, list) or not photos:
        return None
    candidates = [item for item in photos if isinstance(item, dict) and item.get("file_id")]
    if not candidates:
        return None
    selected = max(
        candidates,
        key=lambda item: (
            _positive_int(item.get("file_size"), 0) or 0,
            (_positive_int(item.get("width"), 0) or 0) * (_positive_int(item.get("height"), 0) or 0),
        ),
    )
    return TelegramAssetMetadata(
        kind="photo",
        file_id=str(selected.get("file_id") or ""),
        file_unique_id=str(selected.get("file_unique_id") or "").strip() or None,
        declared_mime="image/jpeg",
        file_size=_positive_int(selected.get("file_size")),
        chat_id=_message_chat_id(message),
        message_id=_message_id(message),
    )


def extract_telegram_asset(message: dict[str, Any]) -> TelegramAssetMetadata | None:
    if not isinstance(message, dict):
        return None
    for kind in ("document", "audio", "video", "voice", "animation", "sticker", "video_note"):
        payload = message.get(kind)
        if isinstance(payload, dict):
            metadata = _metadata_from_payload(kind, payload, message)
            if metadata:
                return metadata
    return _photo_metadata(message)


def _iso_date_parts(value: str) -> tuple[str, str, str]:
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value or "")
    if not match:
        current = utc_now()
        match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", current)
    if not match:
        raise TelegramAssetError("invalid_received_at")
    return match.group(1), match.group(2), match.group(3)


def _header_value(response: Any, name: str) -> str | None:
    if hasattr(response, "getheader"):
        value = response.getheader(name)
        if value is not None:
            return str(value)
    headers = getattr(response, "headers", None) or {}
    if hasattr(headers, "get"):
        value = headers.get(name) or headers.get(name.lower())
        if value is not None:
            return str(value)
    return None


def _content_length(response: Any) -> int | None:
    return _positive_int(_header_value(response, "Content-Length"))


def _read_chunks(stream: Any, chunk_size: int) -> Iterable[bytes]:
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        yield chunk


def runtime_inbox_root(env: dict[str, str] | os._Environ[str] | None = None) -> Path:
    source = os.environ if env is None else env
    configured = str(source.get("RUNTIME_ASSET_INBOX_DIR", "") or "").strip()
    return Path(configured) if configured else DEFAULT_INBOX_ROOT


class RuntimeAssetStore:
    def __init__(
        self,
        inbox_root: Path | str | None = None,
        policy: AssetLimitPolicy | None = None,
        clock: Callable[[], str] | None = None,
        asset_id_factory: Callable[[], str] | None = None,
    ):
        self.inbox_root = Path(inbox_root) if inbox_root is not None else runtime_inbox_root()
        self.policy = policy or AssetLimitPolicy.from_env()
        self.clock = clock or utc_now
        self.asset_id_factory = asset_id_factory or (lambda: uuid.uuid4().hex)

    def store_stream(
        self,
        metadata: TelegramAssetMetadata,
        stream: Any,
        *,
        file_path_present: bool,
        content_length: int | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> StoredTelegramAsset:
        self.policy.check_declared_size(metadata.file_size)
        if content_length is None:
            content_length = _content_length(stream)
        self.policy.check_content_length(content_length)

        received_at = self.clock()
        year, month, day = _iso_date_parts(received_at)
        asset_id = str(self.asset_id_factory()).strip() or uuid.uuid4().hex
        asset_dir = self.inbox_root / "telegram" / year / month / day / asset_id
        blob_path = asset_dir / "blob"
        manifest_path = asset_dir / "manifest.json"
        part_path = asset_dir / "blob.part"
        manifest_part_path = asset_dir / "manifest.json.part"

        hasher = hashlib.sha256()
        sample = bytearray()
        total = 0
        manifest: dict[str, Any] | None = None

        try:
            asset_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
            with part_path.open("wb") as output:
                for chunk in _read_chunks(stream, chunk_size):
                    total += len(chunk)
                    self.policy.check_stream_total(total)
                    hasher.update(chunk)
                    if len(sample) < MIME_SAMPLE_BYTES:
                        sample.extend(chunk[: MIME_SAMPLE_BYTES - len(sample)])
                    output.write(chunk)

            detected_mime = detect_mime(bytes(sample))
            self.policy.check_mime(metadata.declared_mime, detected_mime)
            blob_path.unlink(missing_ok=True)
            part_path.replace(blob_path)
            manifest = build_manifest(
                asset_id=asset_id,
                received_at=received_at,
                metadata=metadata,
                size_bytes=total,
                sha256=hasher.hexdigest(),
                detected_mime=detected_mime,
                max_bytes=self.policy.max_bytes,
                file_path_present=file_path_present,
            )
            errors = manifest_schema_errors(manifest)
            if errors:
                raise TelegramAssetError("manifest_schema_invalid", ", ".join(errors))
            manifest_part_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            manifest_part_path.replace(manifest_path)
        except Exception:
            for path in (part_path, manifest_part_path, manifest_path, blob_path):
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
            try:
                shutil.rmtree(asset_dir)
            except Exception:
                pass
            raise

        return StoredTelegramAsset(
            asset_id=asset_id,
            asset_dir=asset_dir,
            blob_path=blob_path,
            manifest_path=manifest_path,
            manifest=manifest,
        )


def build_manifest(
    *,
    asset_id: str,
    received_at: str,
    metadata: TelegramAssetMetadata,
    size_bytes: int,
    sha256: str,
    detected_mime: str,
    max_bytes: int,
    file_path_present: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "asset_id": asset_id,
        "source": "telegram",
        "received_at": received_at,
        "telegram": {
            "file_id": metadata.file_id,
            "file_unique_id": metadata.file_unique_id,
            "chat_id": hash_chat_id(metadata.chat_id),
            "message_id": metadata.message_id,
            "file_path_present": bool(file_path_present),
        },
        "original": {
            "file_name": safe_display_filename(metadata.file_name),
            "declared_mime": metadata.declared_mime,
            "detected_mime": detected_mime,
            "size_bytes": size_bytes,
            "sha256": sha256,
        },
        "storage": {
            "relative_blob_path": "blob",
            "manifest_path": "manifest.json",
        },
        "policy": {
            "max_bytes": max_bytes,
            "accepted": True,
            "rejection_reason": None,
        },
    }


def manifest_schema_errors(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {"schema_version", "asset_id", "source", "received_at", "telegram", "original", "storage", "policy"}
    missing = sorted(required - set(manifest))
    errors.extend(f"missing:{name}" for name in missing)
    if manifest.get("schema_version") != 1:
        errors.append("schema_version")
    if manifest.get("source") != "telegram":
        errors.append("source")
    telegram = manifest.get("telegram") if isinstance(manifest.get("telegram"), dict) else {}
    original = manifest.get("original") if isinstance(manifest.get("original"), dict) else {}
    storage = manifest.get("storage") if isinstance(manifest.get("storage"), dict) else {}
    policy = manifest.get("policy") if isinstance(manifest.get("policy"), dict) else {}
    if not telegram.get("file_id"):
        errors.append("telegram.file_id")
    if "file_path" in telegram:
        errors.append("telegram.file_path_forbidden")
    if telegram.get("chat_id") and not str(telegram.get("chat_id")).startswith("sha256:"):
        errors.append("telegram.chat_id_not_hashed")
    if storage.get("relative_blob_path") != "blob":
        errors.append("storage.relative_blob_path")
    if storage.get("manifest_path") != "manifest.json":
        errors.append("storage.manifest_path")
    if not isinstance(original.get("size_bytes"), int) or original.get("size_bytes") < 0:
        errors.append("original.size_bytes")
    if not re.match(r"^[a-f0-9]{64}$", str(original.get("sha256") or "")):
        errors.append("original.sha256")
    if not isinstance(policy.get("max_bytes"), int) or policy.get("max_bytes") > TELEGRAM_BOT_API_MAX_DOWNLOAD_BYTES:
        errors.append("policy.max_bytes")
    if policy.get("accepted") is not True or policy.get("rejection_reason") is not None:
        errors.append("policy.accepted")
    return errors


def telegram_file_download_url(bot_token: str, file_path: str) -> str:
    clean_path = str(file_path or "").lstrip("/")
    if not clean_path:
        raise AssetRejected("telegram_file_path_missing")
    quoted_path = urllib.parse.quote(clean_path, safe="/")
    return "https://api.telegram.org/file/bot" + bot_token + "/" + quoted_path


def default_get_file_call(bot_token: str, file_id: str, timeout: int = 35) -> dict[str, Any]:
    data = urllib.parse.urlencode({"file_id": file_id}).encode("utf-8")
    req = urllib.request.Request("https://api.telegram.org/bot" + bot_token + "/getFile", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise TelegramAssetError("telegram_get_file_failed", exc) from exc


def open_telegram_file(
    bot_token: str,
    file_path: str,
    *,
    opener: Callable[..., Any] | None = None,
    timeout: int = 60,
) -> Any:
    url = telegram_file_download_url(bot_token, file_path)
    req = urllib.request.Request(url, method="GET")
    try:
        return (opener or urllib.request.urlopen)(req, timeout=timeout)
    except Exception as exc:
        raise TelegramAssetError("telegram_download_open_failed", exc) from exc


def ingest_telegram_asset(
    message: dict[str, Any],
    bot_token: str,
    *,
    inbox_root: Path | str | None = None,
    policy: AssetLimitPolicy | None = None,
    get_file_call: Callable[[str, str], dict[str, Any]] | None = None,
    opener: Callable[..., Any] | None = None,
    clock: Callable[[], str] | None = None,
    asset_id_factory: Callable[[], str] | None = None,
) -> StoredTelegramAsset:
    metadata = extract_telegram_asset(message)
    if metadata is None:
        raise AssetRejected("no_supported_asset")
    resolved_policy = policy or AssetLimitPolicy.from_env()
    resolved_policy.check_declared_size(metadata.file_size)
    get_file = get_file_call or default_get_file_call
    response_payload = get_file(bot_token, metadata.file_id)
    result = response_payload.get("result") if isinstance(response_payload, dict) else None
    if not isinstance(result, dict):
        raise TelegramAssetError("telegram_get_file_invalid_response")
    file_path = str(result.get("file_path") or "").strip()
    if not file_path:
        raise AssetRejected("telegram_file_path_missing")

    store = RuntimeAssetStore(
        inbox_root=inbox_root,
        policy=resolved_policy,
        clock=clock,
        asset_id_factory=asset_id_factory,
    )
    response = open_telegram_file(bot_token, file_path, opener=opener)
    try:
        with response:
            return store.store_stream(metadata, response, file_path_present=True)
    except AttributeError:
        return store.store_stream(metadata, response, file_path_present=True)
