from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()
STATE = ROOT / "state"
AUTH_FILE = STATE / "panel_auth.json"
SESSION_SECRET_FILE = STATE / "panel_session_secret.txt"
COOKIE_NAME = "codex_panel_session"
PBKDF2_ITERATIONS = 260000
SESSION_TTL_SECONDS = int(os.environ.get("CODEX_PANEL_SESSION_TTL_SECONDS", str(12 * 60 * 60)))


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    return default


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def unb64url(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def session_secret() -> bytes:
    SESSION_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SESSION_SECRET_FILE.exists():
        value = SESSION_SECRET_FILE.read_text(encoding="utf-8", errors="replace").strip()
        if value:
            return bytes.fromhex(value)
    secret = secrets.token_bytes(32)
    SESSION_SECRET_FILE.write_text(secret.hex() + "\n", encoding="utf-8")
    return secret


def hash_password(password: str, salt: str | None = None) -> dict[str, Any]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return {
        "algorithm": "pbkdf2_sha256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": salt,
        "hash": digest.hex(),
    }


def verify_password(password: str, password_record: dict[str, Any]) -> bool:
    if password_record.get("algorithm") != "pbkdf2_sha256":
        return False
    salt = str(password_record.get("salt", ""))
    expected = str(password_record.get("hash", ""))
    iterations = int(password_record.get("iterations", PBKDF2_ITERATIONS))
    try:
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    except Exception:
        return False
    return hmac.compare_digest(digest.hex(), expected)


def auth_config() -> dict[str, Any]:
    ensure_env_user()
    return read_json(AUTH_FILE, {})


def auth_configured() -> bool:
    config = auth_config()
    return bool(config.get("username") and config.get("password"))


def safe_username(value: str) -> str:
    username = value.strip()
    if not username:
        raise ValueError("username_required")
    if len(username) > 64:
        raise ValueError("username_too_long")
    return username


def validate_password(value: str) -> str:
    password = value or ""
    if len(password) < 8:
        raise ValueError("password_min_8")
    if len(password) > 256:
        raise ValueError("password_too_long")
    return password


def setup_user(username: str, password: str) -> dict[str, Any]:
    if AUTH_FILE.exists():
        raise ValueError("auth_already_configured")
    username = safe_username(username)
    password = validate_password(password)
    payload = {
        "auth_mode": "username_password",
        "username": username,
        "password": hash_password(password),
        "created_at": now(),
        "password_source": "setup",
    }
    atomic_write_json(AUTH_FILE, payload)
    return public_auth_state(username=username)


def ensure_env_user() -> None:
    if AUTH_FILE.exists():
        return
    username = os.environ.get("CODEX_PANEL_USERNAME", "").strip()
    password = os.environ.get("CODEX_PANEL_PASSWORD", "")
    if not username or not password:
        return
    username = safe_username(username)
    password = validate_password(password)
    atomic_write_json(
        AUTH_FILE,
        {
            "auth_mode": "username_password",
            "username": username,
            "password": hash_password(password),
            "created_at": now(),
            "password_source": "environment",
        },
    )


def verify_credentials(username: str, password: str) -> bool:
    config = auth_config()
    expected_user = str(config.get("username", ""))
    if not expected_user:
        return False
    if not hmac.compare_digest(username.strip(), expected_user):
        return False
    return verify_password(password, config.get("password", {}))


def sign_payload(payload: dict[str, Any]) -> str:
    body = b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    sig = hmac.new(session_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{b64url(sig)}"


def verify_session(value: str) -> dict[str, Any] | None:
    if not value or "." not in value:
        return None
    body, sig = value.rsplit(".", 1)
    expected = b64url(hmac.new(session_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(unb64url(body).decode("utf-8"))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def make_session(username: str) -> str:
    current = int(time.time())
    return sign_payload(
        {
            "sub": username,
            "iat": current,
            "exp": current + SESSION_TTL_SECONDS,
            "nonce": secrets.token_hex(8),
        }
    )


def automation_cookie_header() -> str:
    return f"{COOKIE_NAME}={make_session('__automation__')}"


def parse_cookie(header: str) -> dict[str, str]:
    cookie = SimpleCookie()
    try:
        cookie.load(header or "")
    except Exception:
        return {}
    return {key: morsel.value for key, morsel in cookie.items()}


def user_from_cookie(header: str) -> str | None:
    session = session_from_cookie(header)
    if not session:
        return None
    return str(session.get("sub") or "") or None


def session_from_cookie(header: str) -> dict[str, Any] | None:
    value = parse_cookie(header).get(COOKIE_NAME, "")
    return verify_session(value)


def session_cookie_header(username: str) -> str:
    return f"{COOKIE_NAME}={make_session(username)}; Path=/; HttpOnly; SameSite=Lax"


def clear_cookie_header() -> str:
    return f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


def timestamp_iso(value: Any) -> str | None:
    try:
        timestamp = int(value)
    except Exception:
        return None
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(microsecond=0).isoformat()


def public_auth_state(username: str | None = None) -> dict[str, Any]:
    config = read_json(AUTH_FILE, {})
    configured = bool(config.get("username") and config.get("password"))
    return {
        "auth_mode": "username_password",
        "configured": configured,
        "username": username or config.get("username"),
        "token_login_enabled": False,
        "remote_setup_allowed": os.environ.get("CODEX_PANEL_ALLOW_REMOTE_SETUP", "") == "1",
    }


def public_account_state(
    username: str | None = None,
    session: dict[str, Any] | None = None,
    current_time: int | None = None,
) -> dict[str, Any]:
    session = session or {}
    subject = username or str(session.get("sub") or "") or None
    current = int(current_time if current_time is not None else time.time())
    expires_at = int(session.get("exp", 0) or 0)
    role = "automation" if subject == "__automation__" else "operator"
    role_label = "Automation" if role == "automation" else "Operator"
    auth_state = public_auth_state(username=subject)
    return {
        "ok": True,
        "auth": auth_state,
        "account": {
            "username": subject,
            "display_name": subject or "Unknown",
            "role": role,
            "role_label": role_label,
            "auth_mode": auth_state["auth_mode"],
            "session": {
                "ttl_seconds": SESSION_TTL_SECONDS,
                "issued_at": timestamp_iso(session.get("iat")),
                "expires_at": timestamp_iso(expires_at),
                "seconds_remaining": max(0, expires_at - current) if expires_at else None,
            },
            "menu": [
                {"id": "account_settings", "label": "Account settings", "enabled": False},
                {"id": "logout", "label": "Logout", "enabled": True},
            ],
        },
    }
