from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any


RETRY_DELAYS_SECONDS = {
    "timeout": [60, 300, 900],
    "usage_limit": [900, 3600, 10800],
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def normalize_failure_kind(value: str) -> str:
    text = str(value or "").lower()
    if "usage" in text or "rate_limit" in text or "limit" in text:
        return "usage_limit"
    return "timeout" if "timeout" in text or "stalled" in text else "other"


def failure_kind_from_reason(reason: str) -> str:
    return normalize_failure_kind(reason)


def _jitter_seconds(task_id: str, failure_kind: str, attempt_no: int, seed: str | None) -> int:
    raw = f"{seed or ''}:{task_id}:{failure_kind}:{attempt_no}".encode("utf-8", errors="replace")
    digest = hashlib.sha256(raw).hexdigest()
    return int(digest[:4], 16) % 17


def decide_retry(
    *,
    task_id: str,
    failure_kind: str,
    current_attempt: int = 1,
    max_attempts: int = 3,
    now: datetime | None = None,
    jitter_seed: str | None = None,
) -> dict[str, Any]:
    kind = normalize_failure_kind(failure_kind)
    current = max(1, int(current_attempt or 1))
    max_value = max(current, int(max_attempts or current))
    next_attempt = current + 1
    terminal = kind not in RETRY_DELAYS_SECONDS or next_attempt > max_value
    base_now = now or utc_now()

    if terminal:
        terminal_state = "terminal_usage_limited" if kind == "usage_limit" else "terminal_timeout"
        return {
            "failure_kind": kind,
            "attempt_no": current,
            "max_attempts": max_value,
            "next_retry_at": None,
            "terminal": True,
            "terminal_state": terminal_state if kind in RETRY_DELAYS_SECONDS else "terminal_failure",
            "reason": "max_attempts_reached" if kind in RETRY_DELAYS_SECONDS else "non_retryable_failure",
            "idempotency_key": f"{task_id}:{kind}:terminal:{current}",
        }

    delay_table = RETRY_DELAYS_SECONDS[kind]
    delay = delay_table[min(next_attempt - 2, len(delay_table) - 1)]
    delay += _jitter_seconds(task_id, kind, next_attempt, jitter_seed)
    next_retry = base_now + timedelta(seconds=delay)
    return {
        "failure_kind": kind,
        "attempt_no": next_attempt,
        "max_attempts": max_value,
        "next_retry_at": next_retry.replace(microsecond=0).isoformat(),
        "terminal": False,
        "terminal_state": None,
        "reason": "retry_scheduled",
        "idempotency_key": f"{task_id}:{kind}:{next_attempt}",
    }


def format_retry_event(event: str, task_id: str, run_id: str, decision: dict[str, Any]) -> str:
    return (
        "retry_policy "
        f"event={event} "
        f"task_id={task_id} "
        f"run_id={run_id} "
        f"failure={decision.get('failure_kind')} "
        f"attempt={decision.get('attempt_no')}/{decision.get('max_attempts')} "
        f"next_retry_at={decision.get('next_retry_at')} "
        f"terminal={str(bool(decision.get('terminal'))).lower()} "
        f"reason=\"{decision.get('reason')}\""
    )
