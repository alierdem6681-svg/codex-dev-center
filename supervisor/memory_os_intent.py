#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Any

MEMORY_OS_INTENT_DOMAIN = "memory_os"
MEMORY_OS_PIPELINE_LANE = "Memory OS Delivery"

MEMORY_OS_MARKERS = [
    "memory os",
    "memory-os",
    "cto-memory-os",
    "cto memory os",
    "memoryos",
    "hafiza os",
    "hafiza sistemi",
    "hafiza modulu",
]

MEMORY_OS_REFERENCE_RE = re.compile(
    r"\bCTO[-_\s]?MEMORY[-_\s]?OS(?:[-_][A-Z0-9]+)*\b",
    re.IGNORECASE,
)


def normalize_turkish(value: str) -> str:
    return (
        str(value or "").lower()
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )


def is_memory_os_request(text: str) -> bool:
    normalized = normalize_turkish(text)
    return any(marker in normalized for marker in MEMORY_OS_MARKERS)


def extract_memory_os_reference(text: str) -> str:
    match = MEMORY_OS_REFERENCE_RE.search(str(text or ""))
    if not match:
        return ""
    return re.sub(r"[-_\s]+", "-", match.group(0).upper()).strip("-")


def is_memory_os_deploy_target(text: str) -> bool:
    normalized = normalize_turkish(text)
    return any(
        term in normalized
        for term in [
            "canliya al",
            "canliya alma",
            "production'a al",
            "productiona al",
            "deploy et",
            "yayina al",
            "yayina alma",
        ]
    )


def is_memory_os_followup_command(text: str) -> bool:
    normalized = " ".join(normalize_turkish(text).split())
    if not normalized:
        return False
    exact = {
        "devam",
        "tamam devam",
        "onayliyorum devam",
        "onay verdim devam",
        "basla",
        "baslat",
        "baslayalim",
        "hadi baslayalim",
        "gelistirmeye baslayalim",
        "gelistirmeye basla",
        "canliya al",
        "productiona al",
        "production'a al",
        "deploy et",
    }
    if normalized in exact:
        return True
    followup_signal = any(
        term in normalized
        for term in [
            "devam",
            "basla",
            "baslat",
            "onayliyorum",
            "onay verdim",
            "uygula",
            "tamamla",
        ]
    )
    if is_memory_os_request(text) and followup_signal:
        return True
    if is_memory_os_deploy_target(text):
        return len(normalized) <= 180 or is_memory_os_request(text)
    return False


def build_memory_os_followup_text(context: str, followup: str) -> str:
    parts = []
    if str(context or "").strip():
        parts.extend(["Önceki Memory OS bağlamı:", str(context).strip(), ""])
    parts.extend(
        [
            "Kullanıcı takip komutu:",
            str(followup or "").strip(),
            "",
            "Domain intent: memory_os.",
            (
                "Aynı root task zincirini koru; CTO-MEMORY-OS referansını, "
                "devam/başlat/onay ve canlıya alma hedefini Production Readiness "
                "veya genel görev dağıtımına düşürmeden Memory OS Delivery olarak işle."
            ),
        ]
    )
    return "\n".join(parts).strip()


def task_memory_os_reference(task: dict[str, Any]) -> str:
    explicit = str(task.get("memory_os_reference") or task.get("intent_reference") or "").strip()
    if explicit:
        return explicit
    return extract_memory_os_reference(
        "\n".join(
            str(task.get(key) or "")
            for key in ("title", "description", "raw_message")
        )
    )


def task_is_memory_os(task: dict[str, Any]) -> bool:
    if str(task.get("intent_domain") or "") == MEMORY_OS_INTENT_DOMAIN:
        return True
    text = "\n".join(
        str(task.get(key) or "")
        for key in ("title", "description", "raw_message", "pipeline_lane")
    )
    return is_memory_os_request(text)


def find_memory_os_root_task_id(tasks: list[dict[str, Any]], reference: str = "") -> str:
    for task in reversed(tasks or []):
        if not task_is_memory_os(task):
            continue
        task_reference = task_memory_os_reference(task)
        if reference and task_reference and task_reference != reference:
            continue
        root_id = str(task.get("root_task_id") or task.get("id") or "").strip()
        if root_id:
            return root_id
    return ""
