from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from .critical_operation_policy import critical_operation_findings
except ImportError:
    from critical_operation_policy import critical_operation_findings

ROOT = Path(__file__).resolve().parents[1]
APPROVAL_LOG = ROOT / "logs" / "deploy_approval_required.log"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def evaluate_deploy_action(description: str) -> dict:
    matched = critical_operation_findings(description)
    result = {
        "description": description,
        "risk_level": "high" if matched else "low",
        "approval_required": False,
        "matched_terms": matched,
        "evaluated_at": utc_now(),
        "production_deploy_enabled": True,
        "automatic_if_all_gates_pass": True,
        "status": "ALLOWED_WITH_GATES",
        "approval_gate_disabled": True,
        "gate_rule": "pipeline_pass_only",
    }
    if result["approval_required"]:
        APPROVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with APPROVAL_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy risk gate")
    parser.add_argument("description")
    args = parser.parse_args()
    print(json.dumps(evaluate_deploy_action(args.description), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
