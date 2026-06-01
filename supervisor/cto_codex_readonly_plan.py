#!/usr/bin/env python3
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

APP = Path("/opt/codex-dev-center")
LOGS = APP / "logs"
REPORTS = APP / "reports"

def now_id():
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

def main():
    prompt = " ".join(sys.argv[1:]).strip()
    if not prompt:
        prompt = sys.stdin.read().strip()

    if not prompt:
        print("CODEX_PLAN=FAIL")
        print("ERROR=empty_prompt")
        return 1

    LOGS.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)

    run_id = now_id()
    prompt_file = LOGS / f"cto_codex_readonly_prompt_{run_id}.txt"
    out_file = LOGS / f"cto_codex_readonly_out_{run_id}.txt"
    err_file = LOGS / f"cto_codex_readonly_err_{run_id}.txt"
    report_file = REPORTS / f"CTO_CODEX_READONLY_PLAN_{run_id}.md"

    final_prompt = f"""
Sen Codex Dev Center içindeki CTO'nun read-only planlama yardımcısısın.

Kurallar:
- Dosya değiştirme.
- Komutla değişiklik yapma.
- Sadece oku, analiz et, kısa Türkçe plan ver.
- Production, IAM, Secret, GCloud mutate, database migration, DNS, firewall işlemi yapma.
- Teknik çıktı dökme.
- Kullanıcıya yönetici seviyesinde özet ver.

Okunacak ana dosyalar:
- AGENTS.md
- docs/AGENT_ONBOARDING_MAP.md
- docs/HANDOVER.md
- docs/ROADMAP.md
- docs/LIVING_DOCUMENTATION_POLICY.md
- memory/project_memory.md
- state/system_state.json
- state/module_registry.json
- state/action_catalog.json

Kullanıcı/CTO isteği:
{prompt}

Cevap formatı:
1. Kısa değerlendirme
2. Önerilen plan
3. Risk seviyesi
4. Worker dağılımı önerisi
5. Onay gerekir mi?
""".strip()

    prompt_file.write_text(final_prompt, encoding="utf-8")

    cmd = [
        "timeout", "180",
        "codex", "exec",
        "--sandbox", "read-only",
        "--cd", str(APP),
        "-"
    ]

    with prompt_file.open("rb") as stdin, out_file.open("wb") as stdout, err_file.open("wb") as stderr:
        proc = subprocess.run(cmd, cwd=str(APP), stdin=stdin, stdout=stdout, stderr=stderr)

    out_text = out_file.read_text(errors="replace")
    err_text = err_file.read_text(errors="replace")

    report_file.write_text(
        "# CTO CODEX READONLY PLAN\n\n"
        f"Run ID: {run_id}\n\n"
        f"Return code: {proc.returncode}\n\n"
        "## Prompt\n\n"
        "```text\n" + final_prompt[:4000] + "\n```\n\n"
        "## Output\n\n"
        "```text\n" + out_text[:6000] + "\n```\n\n"
        "## Error / Runtime Log\n\n"
        "```text\n" + err_text[:3000] + "\n```\n",
        encoding="utf-8"
    )

    print("CODEX_PLAN=" + ("OK" if proc.returncode == 0 else "FAIL"))
    print("CODEX_RC=" + str(proc.returncode))
    print("OUT_LINES=" + str(len(out_text.splitlines())))
    print("ERR_LINES=" + str(len(err_text.splitlines())))
    print("REPORT_FILE=" + str(report_file))
    print("OUT_HEAD=" + " ".join(out_text.splitlines()[:8])[:700])

    return proc.returncode

if __name__ == "__main__":
    raise SystemExit(main())
