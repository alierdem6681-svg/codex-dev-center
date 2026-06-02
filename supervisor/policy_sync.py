#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("CODEX_DEV_CENTER_HOME", Path(__file__).resolve().parents[1])).resolve()
STATE = ROOT / "state"
TEMPLATES = ROOT / "state_templates"

POLICY_ALLOWLIST = [
    "action_catalog.json",
    "approval_policy.json",
    "cto_authority_policy.json",
    "cto_delivery_policy.json",
    "dashboard_settings.json",
    "deploy_policy.json",
    "module_settings.json",
    "production_policy.json",
    "production_readiness_policy.json",
    "worker_lifecycle_policy.json",
]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, dict):
        data["updated_at"] = now()
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def sync(dry_run: bool = False) -> dict[str, Any]:
    copied: list[str] = []
    missing: list[str] = []
    for name in POLICY_ALLOWLIST:
        src = TEMPLATES / name
        dst = STATE / name
        if not src.exists():
            missing.append(name)
            continue
        payload = read_json(src)
        if not dry_run:
            atomic_write_json(dst, payload)
        copied.append(name)
    return {
        "ok": not missing,
        "dry_run": dry_run,
        "copied": copied,
        "missing": missing,
        "updated_at": now(),
        "secret_material_copied": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync non-secret policy templates into runtime state")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = sync(dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
