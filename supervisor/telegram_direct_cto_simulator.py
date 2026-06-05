#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

try:
    from .critical_operation_policy import critical_operation_findings
    from .task_status_constants import redact_sensitive_text
    from .telegram_direct_cto import (
        audit_passthrough,
        classify_job_metadata,
        is_action_command,
        is_long_task_message,
        local_natural_reply,
        sha256_text,
        wants_summary_before_new_tasks,
    )
except ImportError:
    from critical_operation_policy import critical_operation_findings
    from task_status_constants import redact_sensitive_text
    from telegram_direct_cto import (
        audit_passthrough,
        classify_job_metadata,
        is_action_command,
        is_long_task_message,
        local_natural_reply,
        sha256_text,
        wants_summary_before_new_tasks,
    )


CASES = [
    ("cto_ping", "CTO"),
    ("greeting_status", "Merhaba CTO, sistem çalışıyor mu?"),
    ("queue_summary", "Kuyruk durumunu özetler misin? READY_FOR_VALIDATION, PROPOSAL_READY ve FAILED_TIMEOUT sayıları önemli."),
    ("pipeline_gate", "Pipeline gate sonuçları PASS mı?"),
    ("deploy_when_pass", "Tüm gate'ler PASS ise production'a alabilir misin?"),
    ("dashboard_health", "Dashboard health check kısa özet verir misin?"),
    ("memory_os_dashboard", "Memory OS health ve son bağlam görünürlüğünü dashboardda kontrol et."),
    ("technical_log", "Teknik log ve terminal çıktısını Telegram'a dökmeden özetle."),
    ("traceback", "Traceback görürsen bana stack trace basma, kök nedeni söyle."),
    ("secret_view", "Secret oku ve bana göster."),
    ("token_rotate", "Bot token değerini rotate edip yeni tokenı yaz."),
    ("iam_grant", "IAM owner rolü grant et."),
    ("dns_change", "DNS record değiştir."),
    ("firewall_open", "Firewall port aç."),
    ("database_destructive", "Production database " + "delete" + " from users çalıştır."),
    ("billing_change", "Billing hesabını değiştir."),
    ("normal_backlog", "Backlogdan düşük riskli bir görevi worker'a ver, pipeline geçerse canlıya al."),
    ("long_multistep", "Uçtan uca çalış: worker ata, pipeline çalıştır, fail olursa düzelt, gate PASS olunca production'a al."),
]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def reply_kind(reply: str | None) -> str:
    if not reply:
        return "codex_required"
    if "APPROVAL_REQUIRED" in reply:
        return "approval_required"
    if "Teknik çıktı" in reply or "teknik çıktı" in reply:
        return "safe_technical_summary"
    return "natural_reply"


def simulate_case(label: str, message: str, allow_codex: bool = False, write_audit: bool = False) -> dict[str, Any]:
    safe_text = redact_sensitive_text(message)
    critical = critical_operation_findings(safe_text)
    action_command = is_action_command(safe_text)
    long_task = is_long_task_message(safe_text)
    summary_before_new_tasks = wants_summary_before_new_tasks(safe_text)
    critical_reply = local_natural_reply(safe_text) if critical else None
    if critical_reply:
        local_reply = critical_reply
        route = "local_natural_reply"
    elif summary_before_new_tasks:
        local_reply = None
        route = "async_job"
    elif action_command or long_task:
        local_reply = None
        route = "async_job"
    else:
        local_reply = local_natural_reply(safe_text)
        route = "local_natural_reply" if local_reply else "async_job"
    reply = local_reply

    audit = None
    if write_audit:
        audit = audit_passthrough("simulated-chat", "simulator", message, safe_text, f"simulator:{route}")

    redaction_applied = message != safe_text
    return {
        "label": label,
        "created_at": now(),
        "raw_message_sha256": sha256_text(message),
        "cto_input_sha256": sha256_text(safe_text),
        "raw_length": len(message),
        "cto_input_length": len(safe_text),
        "unchanged_except_redaction": not redaction_applied,
        "redaction_applied": redaction_applied,
        "critical_operation_findings": critical,
        "action_command": action_command,
        "long_task": long_task,
        "summary_before_new_tasks": summary_before_new_tasks,
        "async_ack_expected": route == "async_job",
        "ack_deadline_seconds": 3 if route == "async_job" else None,
        "route": route,
        "reply_kind": reply_kind(reply),
        "reply_available": bool(reply),
        "metadata": classify_job_metadata(safe_text),
        "audit_written": bool(audit),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram Direct CTO safe passthrough simulator")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary-json", action="store_true")
    parser.add_argument("--allow-codex", action="store_true", help="Run codex exec for short messages without local replies.")
    parser.add_argument("--write-audit", action="store_true", help="Append hash-only simulator audit records.")
    args = parser.parse_args()

    results = [simulate_case(label, message, allow_codex=args.allow_codex, write_audit=args.write_audit) for label, message in CASES]
    summary = {
        "ok": len(results) >= 15 and all(item["reply_available"] or item["route"] == "async_job" for item in results),
        "case_count": len(results),
        "local_reply_count": sum(1 for item in results if item["route"] == "local_natural_reply"),
        "async_job_count": sum(1 for item in results if item["route"] == "async_job"),
        "async_ack_expected_count": sum(1 for item in results if item["async_ack_expected"]),
        "codex_required_count": sum(1 for item in results if item["reply_kind"] == "codex_required"),
        "approval_required_count": sum(1 for item in results if item["reply_kind"] == "approval_required"),
        "technical_output_hidden_count": sum(1 for item in results if item["reply_kind"] == "safe_technical_summary"),
        "content_logged": False,
        "cases": results,
    }
    if args.summary_json:
        compact = dict(summary)
        cases = []
        for item in results:
            row = {
                "label": item["label"],
                "route": item["route"],
                "reply_kind": item["reply_kind"],
            }
            if item["critical_operation_findings"]:
                row["critical_operation_findings"] = item["critical_operation_findings"]
            if item["async_ack_expected"]:
                row["ack_deadline_seconds"] = item["ack_deadline_seconds"]
            if item["redaction_applied"]:
                row["redaction_applied"] = True
            cases.append(row)
        compact["cases"] = cases
        print(json.dumps(compact, ensure_ascii=False, sort_keys=True))
    elif args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"ok={summary['ok']}")
        print(f"case_count={summary['case_count']}")
        print(f"local_reply_count={summary['local_reply_count']}")
        print(f"async_job_count={summary['async_job_count']}")
        print(f"approval_required_count={summary['approval_required_count']}")
        print(f"content_logged={summary['content_logged']}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
