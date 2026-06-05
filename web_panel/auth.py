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
AUTH_MODE = "disabled"


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
    return {}


def auth_configured() -> bool:
    return False


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
    return public_auth_state()


def ensure_env_user() -> None:
    return None


def verify_credentials(username: str, password: str) -> bool:
    return False


def sign_payload(payload: dict[str, Any]) -> str:
    body = b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    sig = hmac.new(session_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{b64url(sig)}"


def verify_session(value: str) -> dict[str, Any] | None:
    if AUTH_MODE == "disabled":
        return None
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
    if AUTH_MODE == "disabled":
        return ""
    return f"{COOKIE_NAME}={make_session('__automation__')}"


def parse_cookie(header: str) -> dict[str, str]:
    cookie = SimpleCookie()
    try:
        cookie.load(header or "")
    except Exception:
        return {}
    return {key: morsel.value for key, morsel in cookie.items()}


def user_from_cookie(header: str) -> str | None:
    if AUTH_MODE == "disabled":
        return "__public_dashboard__"
    value = parse_cookie(header).get(COOKIE_NAME, "")
    session = verify_session(value)
    if not session:
        return None
    return str(session.get("sub") or "") or None


def session_cookie_header(username: str) -> str:
    if AUTH_MODE == "disabled":
        return clear_cookie_header()
    return f"{COOKIE_NAME}={make_session(username)}; Path=/; HttpOnly; SameSite=Lax"


def clear_cookie_header() -> str:
    return f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


def public_auth_state(username: str | None = None) -> dict[str, Any]:
    return {
        "auth_mode": AUTH_MODE,
        "configured": False,
        "username": None,
        "token_login_enabled": False,
        "direct_access_enabled": True,
        "user_setup_required": False,
        "remote_setup_allowed": os.environ.get("CODEX_PANEL_ALLOW_REMOTE_SETUP", "") == "1",
    }
