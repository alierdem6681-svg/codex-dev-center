#!/usr/bin/env python3
import argparse
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path("/opt/codex-dev-center")
STATE_DIR = APP_DIR / "state"
LOG_DIR = APP_DIR / "logs"
APPROVALS = STATE_DIR / "approval_requests.json"

def now():
    return datetime.now(timezone.utc).isoformat()

def read_json(path, default):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text())
    except Exception:
        return default

def write_json(path, data):
    data["updated_at"] = now()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

def audit(action, detail):
    LOG_DIR.mkdir(exist_ok=True)
    with (LOG_DIR / "audit.log").open("a", encoding="utf-8") as f:
        f.write(f"{now()} approval_gate action={action} detail={detail}\n")

def create(args):
    data = read_json(APPROVALS, {"approvals": []})
    approval_id = "APR-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    words = [secrets.choice(["MAVI", "KALE", "DENIZ", "YOL", "KAPI", "GUNES", "TAS", "KOD", "BULUT"]) for _ in range(3)]
    item = {
        "id": approval_id,
        "title": args.title,
        "description": args.description,
        "risk": args.risk,
        "action": args.action,
        "status": "PENDING",
        "required_words": words,
        "created_at": now(),
        "updated_at": now()
    }
    data.setdefault("approvals", []).append(item)
    write_json(APPROVALS, data)
    audit("create", approval_id)
    print(json.dumps({"ok": True, "approval": item}, indent=2, ensure_ascii=False))

def list_items(_args):
    data = read_json(APPROVALS, {"approvals": []})
    print(json.dumps(data, indent=2, ensure_ascii=False))

def respond(args):
    data = read_json(APPROVALS, {"approvals": []})
    found = None
    for item in data.get("approvals", []):
        if item.get("id") == args.id:
            found = item
            break

    if not found:
        print(json.dumps({"ok": False, "error": "approval_not_found"}, indent=2, ensure_ascii=False))
        return

    if args.decision == "approve":
        supplied = [w.strip().upper() for w in (args.words or "").split()]
        required = [w.strip().upper() for w in found.get("required_words", [])]
        if supplied != required:
            found["status"] = "APPROVAL_FAILED_WORDS"
            found["updated_at"] = now()
            write_json(APPROVALS, data)
            audit("approve_failed_words", args.id)
            print(json.dumps({"ok": False, "error": "approval_words_mismatch", "required_words": required}, indent=2, ensure_ascii=False))
            return
        found["status"] = "APPROVED"
    else:
        found["status"] = "REJECTED"

    found["decision_at"] = now()
    found["updated_at"] = now()
    write_json(APPROVALS, data)
    audit(args.decision, args.id)
    print(json.dumps({"ok": True, "approval": found}, indent=2, ensure_ascii=False))

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create")
    p.add_argument("--title", required=True)
    p.add_argument("--description", default="")
    p.add_argument("--risk", default="high", choices=["high", "critical"])
    p.add_argument("--action", required=True)
    p.set_defaults(func=create)

    p = sub.add_parser("list")
    p.set_defaults(func=list_items)

    p = sub.add_parser("respond")
    p.add_argument("--id", required=True)
    p.add_argument("--decision", required=True, choices=["approve", "reject"])
    p.add_argument("--words", default="")
    p.set_defaults(func=respond)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
