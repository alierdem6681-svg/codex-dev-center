from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPROVAL_LOG = ROOT / "logs" / "deploy_approval_required.log"

HIGH_RISK_TERMS = [
    "production",
    "prod deploy",
    "migration",
    "delete data",
    "drop table",
    "secret",
    "dns",
    "cloud cost",
    "billing",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def evaluate_deploy_action(description: str) -> dict:
    normalized = description.lower()
    matched = [term for term in HIGH_RISK_TERMS if term in normalized]
    result = {
        "description": description,
        "risk_level": "high" if matched else "low",
        "approval_required": bool(matched),
        "matched_terms": matched,
        "evaluated_at": utc_now(),
        "production_deploy_enabled": False,
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
