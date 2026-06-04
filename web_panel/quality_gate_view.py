from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


CONTRACT_VERSION = 1
STALE_AFTER_SECONDS = 24 * 60 * 60

VIEW_STATUS_SEVERITY = {
    "READY": "success",
    "DEGRADED": "warning",
    "NOT_READY": "error",
    "UNKNOWN": "neutral",
}

VIEW_STATUS_LABEL = {
    "READY": "Hazir",
    "DEGRADED": "Kisitli",
    "NOT_READY": "Hazir degil",
    "UNKNOWN": "Bilinmiyor",
}

READY_VALUES = {"PASS", "PASSED", "READY", "OK", "SUCCESS", "HEALTHY"}
NOT_READY_VALUES = {"FAIL", "FAILED", "NOT_READY", "ERROR", "UNHEALTHY"}
BLOCKED_VALUES = {"BLOCKED", "APPROVAL_REQUIRED"}
DEGRADED_VALUES = {"DEGRADED", "WARN", "WARNING"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def normalized_status_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("status") or payload.get("result") or "").strip().upper()


def updated_at(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    return first_text(
        payload.get("checked_at"),
        payload.get("updated_at"),
        payload.get("generated_at"),
        payload.get("finished_at"),
        payload.get("created_at"),
    )


def is_stale(timestamp: str | None, computed_at: str) -> bool:
    observed = parse_time(timestamp)
    computed = parse_time(computed_at)
    if observed is None or computed is None:
        return bool(timestamp)
    if observed > computed:
        return False
    return (computed - observed).total_seconds() > STALE_AFTER_SECONDS


def normalize_readiness(payload: Any, computed_at: str) -> dict[str, Any]:
    timestamp = updated_at(payload)
    missing = not isinstance(payload, dict) or not payload
    timestamp_missing = not missing and not timestamp
    stale = is_stale(timestamp, computed_at)
    status_text = normalized_status_text(payload)

    if missing:
        status = "unknown"
    elif timestamp_missing:
        status = "unknown"
    elif stale:
        status = "unknown"
    elif status_text in BLOCKED_VALUES:
        status = "blocked"
    elif status_text in READY_VALUES or payload.get("ok") is True:
        status = "ready"
    elif status_text in NOT_READY_VALUES or payload.get("ok") is False:
        status = "not_ready"
    else:
        status = "unknown"

    return {
        "status": status,
        "updated_at": timestamp,
        "stale": stale,
        "missing": missing,
        "timestamp_missing": timestamp_missing,
    }


def normalize_health(payload: Any, computed_at: str) -> dict[str, Any]:
    timestamp = updated_at(payload)
    missing = not isinstance(payload, dict) or not payload
    timestamp_missing = not missing and not timestamp
    stale = is_stale(timestamp, computed_at)
    status_text = normalized_status_text(payload)

    if missing:
        status = "unknown"
    elif timestamp_missing:
        status = "unknown"
    elif stale:
        status = "unknown"
    elif status_text in DEGRADED_VALUES:
        status = "degraded"
    elif status_text in NOT_READY_VALUES or payload.get("ok") is False:
        status = "unhealthy"
    elif status_text in READY_VALUES or payload.get("ok") is True:
        status = "healthy"
    else:
        status = "unknown"

    return {
        "status": status,
        "updated_at": timestamp,
        "stale": stale,
        "missing": missing,
        "timestamp_missing": timestamp_missing,
    }


def legacy_quality_status(payload: Any) -> str | None:
    if not isinstance(payload, dict) or not payload:
        return None
    status = normalized_status_text(payload)
    if status:
        return status
    if payload.get("ok") is True:
        return "PASS"
    if payload.get("ok") is False:
        return "FAIL"
    return None


def legacy_conflicts(view_status: str, legacy_status: str | None) -> bool:
    if not legacy_status or view_status == "UNKNOWN":
        return False
    legacy_ready = legacy_status in READY_VALUES
    legacy_not_ready = legacy_status in NOT_READY_VALUES or legacy_status in BLOCKED_VALUES
    if view_status == "READY" and legacy_not_ready:
        return True
    if view_status == "NOT_READY" and legacy_ready:
        return True
    return False


def resolve_view_status(readiness: dict[str, Any], health: dict[str, Any]) -> tuple[str, list[str], str]:
    reasons: list[str] = []

    if readiness["missing"]:
        reasons.append("readiness_missing")
    if health["missing"]:
        reasons.append("health_missing")
    if readiness["timestamp_missing"]:
        reasons.append("readiness_timestamp_missing")
    if health["timestamp_missing"]:
        reasons.append("health_timestamp_missing")
    if readiness["stale"]:
        reasons.append("readiness_stale")
    if health["stale"]:
        reasons.append("health_stale")

    if reasons:
        return "UNKNOWN", reasons, "unknown"

    readiness_status = readiness["status"]
    health_status = health["status"]

    if readiness_status == "blocked":
        return "NOT_READY", ["readiness_blocked"], "readiness_health"
    if readiness_status == "not_ready":
        return "NOT_READY", ["readiness_not_ready"], "readiness_health"
    if health_status == "unhealthy":
        return "NOT_READY", ["health_unhealthy"], "readiness_health"
    if readiness_status == "ready" and health_status == "degraded":
        return "DEGRADED", ["health_degraded"], "readiness_health"
    if readiness_status == "ready" and health_status == "healthy":
        return "READY", ["readiness_ready", "health_healthy"], "readiness_health"

    reasons.append(f"unmapped_combination:{readiness_status}:{health_status}")
    return "UNKNOWN", reasons, "unknown"


def build_quality_gate_view(
    readiness_payload: Any,
    health_payload: Any,
    legacy_payload: Any | None = None,
    computed_at: str | None = None,
) -> dict[str, Any]:
    computed = computed_at or utc_now_iso()
    readiness = normalize_readiness(readiness_payload, computed)
    health = normalize_health(health_payload, computed)
    legacy_status = legacy_quality_status(legacy_payload)

    status, reasons, source = resolve_view_status(readiness, health)
    if status == "UNKNOWN" and source == "unknown" and legacy_status:
        source = "legacy_fallback"
        if "legacy_fallback_non_authoritative" not in reasons:
            reasons.append("legacy_fallback_non_authoritative")
    if legacy_conflicts(status, legacy_status):
        reasons.append("legacy_conflict")

    return {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "severity": VIEW_STATUS_SEVERITY[status],
        "label": VIEW_STATUS_LABEL[status],
        "reason_codes": reasons,
        "computed_at": computed,
        "source": source,
        "readiness": {
            "status": readiness["status"],
            "updated_at": readiness["updated_at"],
        },
        "health": {
            "status": health["status"],
            "updated_at": health["updated_at"],
        },
        "legacy_quality_gate_status": legacy_status,
    }
