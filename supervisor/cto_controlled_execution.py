#!/usr/bin/env python3
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

APP = Path("/opt/codex-dev-center")
STATE = APP / "state"
LOGS = APP / "logs"
REPORTS = APP / "reports"
WORKSPACES = APP / "workspaces"

def now():
    return datetime.now(timezone.utc).isoformat()

def safe_name(s):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:120]

def read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

def latest_cto_task():
    q = read_json(STATE / "task_queue.json", {"tasks": []})
    tasks = [t for t in q.get("tasks", []) if t.get("source") == "cto"]
    return tasks[-1] if tasks else None

def main():
    task = latest_cto_task()
    if not task:
        print("CONTROLLED_EXECUTION=FAIL")
        print("ERROR=no_cto_task")
        return 1

    task_id = task.get("id", "no-id")
    title = task.get("title", "Yeni görev")
    desc = task.get("description", title)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ws = WORKSPACES / f"controlled_{safe_name(task_id)}_{run_id}"
    ws.mkdir(parents=True, exist_ok=True)

    prompt = f"""
Sen Codex Dev Center controlled execution yardımcısısın.

Bu aşamada ana repo dosyalarını değiştirme.
Sadece bu izole workspace içinde dosyalar oluştur.

Görev:
{title}

Açıklama:
{desc}

Kurallar:
- Production deploy yok.
- IAM yok.
- Secret okuma yok.
- Database migration yok.
- DNS/firewall/GCloud mutate yok.
- Ana repo dosyalarını değiştirme.
- Sadece workspace içine plan ve öneri dosyaları yaz.

Workspace içinde şu dosyaları oluştur:
1. PLAN.md
2. CHANGE_PROPOSAL.md
3. TEST_PLAN.md
4. RISK_REVIEW.md
5. LIVING_DOCS_CHECKLIST.md

Kısa ve Türkçe yaz.
""".strip()

    prompt_file = ws / "PROMPT.txt"
    out_file = LOGS / f"controlled_exec_{run_id}.out"
    err_file = LOGS / f"controlled_exec_{run_id}.err"
    report_file = REPORTS / f"CONTROLLED_EXECUTION_{run_id}.md"

    prompt_file.write_text(prompt, encoding="utf-8")

    cmd = [
        "timeout", "180",
        "codex", "exec",
        "--sandbox", "workspace-write",
        "--skip-git-repo-check",
        "--cd", str(ws),
        prompt
    ]

    with out_file.open("wb") as out, err_file.open("wb") as err:
        proc = subprocess.run(
            cmd,
            cwd=str(APP),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            timeout=200
        )

    expected = ["PLAN.md", "CHANGE_PROPOSAL.md", "TEST_PLAN.md", "RISK_REVIEW.md", "LIVING_DOCS_CHECKLIST.md"]
    created = [name for name in expected if (ws / name).exists()]

    report_file.write_text(
        f"# CONTROLLED EXECUTION REPORT\n\n"
        f"Tarih: {now()}\n\n"
        f"Task: {task_id}\n\n"
        f"Return code: {proc.returncode}\n\n"
        f"Workspace: {ws}\n\n"
        f"Created files: {', '.join(created)}\n\n"
        f"Not: Bu adım ana repo dosyalarını değiştirmedi. Sadece izole workspace içinde proposal üretti.\n",
        encoding="utf-8"
    )

    state = read_json(STATE / "system_state.json", {})
    state.update({
        "phase": "step_19c2_controlled_execution_proposal_ready",
        "controlled_execution_proposal_ready": True,
        "last_controlled_execution_workspace": str(ws),
        "last_controlled_execution_task": task_id
    })
    write_json(STATE / "system_state.json", state)

    with (LOGS / "system.log").open("a", encoding="utf-8") as f:
        f.write(now() + f" STEP_19C2 controlled execution proposal task={task_id} rc={proc.returncode}\n")

    print("CONTROLLED_EXECUTION=" + ("OK" if proc.returncode == 0 else "FAIL"))
    print("RC=" + str(proc.returncode))
    print("WORKSPACE=" + str(ws))
    print("CREATED_COUNT=" + str(len(created)))
    print("CREATED_FILES=" + ",".join(created))
    print("REPORT_FILE=" + str(report_file))
    return proc.returncode

if __name__ == "__main__":
    raise SystemExit(main())
