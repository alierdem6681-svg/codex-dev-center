#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import dataclass

TECH_PATTERNS = [
    r"^diff --git ",
    r"^\+\+\+ ",
    r"^--- ",
    r"^@@ ",
    r"Traceback \(most recent call last\):",
    r"File \".*\", line \d+",
    r"npm ERR!",
    r"SyntaxError:",
    r"Exception:",
    r"Error:",
    r"^\s*[+]\s{0,3}(def |class |import |from |const |let |var |function )",
    r"^\s*[-]\s{0,3}(def |class |import |from |const |let |var |function )",
]

@dataclass
class GuardResult:
    allow_telegram: bool
    reason: str
    telegram_text: str
    full_text: str

def looks_technical(text: str) -> tuple[bool, str]:
    if not text:
        return False, "empty"

    lines = text.splitlines()

    if len(lines) > 25:
        return True, "too_many_lines"

    if len(text) > 2500:
        return True, "too_long"

    code_fence_count = text.count("```")
    if code_fence_count >= 2:
        return True, "code_block"

    for line in lines:
        for pattern in TECH_PATTERNS:
            if re.search(pattern, line):
                return True, f"technical_pattern:{pattern}"

    return False, "normal_text"

def guard_for_telegram(text: str, task_id: str | None = None, log_path: str | None = None) -> GuardResult:
    is_technical, reason = looks_technical(text)

    if not is_technical:
        return GuardResult(
            allow_telegram=True,
            reason="normal_text",
            telegram_text=text,
            full_text=text,
        )

    task_part = f"Görev: {task_id}\n" if task_id else ""
    log_part = f"Log: {log_path}\n" if log_path else ""

    return GuardResult(
        allow_telegram=False,
        reason=reason,
        telegram_text=(
            "Teknik çıktı Telegram'a gönderilmedi.\n"
            f"{task_part}"
            f"Sebep: {reason}\n"
            f"{log_part}"
        ).strip(),
        full_text=text,
    )
