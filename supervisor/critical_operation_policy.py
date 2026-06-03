from __future__ import annotations

import re
from typing import Any


CRITICAL_OPERATION_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "secret_value_view_or_change": [
        re.compile(r"\bsecret\b.*\b(read|view|show|print|write|set|change|rotate|delete)\b", re.I),
        re.compile(r"\b(secret oku|secret göster|secret goster|secret yaz|secret değiştir|secret degistir)\b", re.I),
    ],
    "token_private_key_env_value_change": [
        re.compile(r"\b(token|private[_ -]?key|env)\b.*\b(rotate|rotation|write|set|change|update|delete|print|show|view)\b", re.I),
        re.compile(r"\b(token|private key|env içeriği|env icerigi).*\b(değiş|degis|göster|goster|yaz|rotate)\b", re.I),
    ],
    "credential_rotation": [
        re.compile(r"\bcredential\b.*\b(rotate|rotation|change|update|reset)\b", re.I),
        re.compile(r"\b(credential rotation|kimlik bilgisi rotasyonu|kimlik bilgisi değişimi)\b", re.I),
    ],
    "iam_owner_editor_change": [
        re.compile(r"\biam\b.*\b(grant|set|add|remove|change|update|policy|role|yetki|ver|owner|editor)\b", re.I),
        re.compile(r"\b(owner|editor)\b.*\b(grant|role|yetki|ver)\b", re.I),
    ],
    "billing_change": [
        re.compile(r"\bbilling\b.*\b(change|update|set|enable|disable)\b", re.I),
        re.compile(r"\bbilling\b.*(değiş|degis)", re.I),
        re.compile(r"\b(ödeme|odeme|fatura|billing).*\b(update|change)\b", re.I),
        re.compile(r"\b(ödeme|odeme|fatura|billing).*(değiş|degis)", re.I),
    ],
    "firewall_change": [
        re.compile(r"\bfirewall\b.*\b(open|allow|add|change|update|delete|aç|ac|değiş|degis|sil)\b", re.I),
    ],
    "dns_change": [
        re.compile(r"\bdns\b.*\b(add|change|update|delete|set|route|record|değiş|degis|sil)\b", re.I),
    ],
    "database_destructive_operation": [
        re.compile(r"\b(drop\s+table|truncate\s+table|delete\s+from)\b", re.I),
        re.compile(r"\b(database|veritabanı|veritabani|db)\b.*\b(delete|drop|truncate|wipe|destroy|sil)\b", re.I),
        re.compile(r"\b(database destructive|destructive database|destructive db)\b", re.I),
    ],
    "irreversible_migration": [
        re.compile(r"\b(irreversible|geri döndürülemez|geri dondurulemez)\b.*\bmigration\b", re.I),
        re.compile(r"\bmigration\b.*\b(production|canlı|canli)\b", re.I),
    ],
    "google_ads_live_mutate": [
        re.compile(r"\bgoogle ads\b.*\b(mutate|live|canlı|canli)\b", re.I),
    ],
    "live_customer_or_data_loss_risk": [
        re.compile(r"\b(customer|müşteri|musteri|live data|canlı veri|canli veri)\b.*\b(delete|loss|sil|kayb)\b", re.I),
    ],
}


def critical_operation_findings(text: Any) -> list[str]:
    value = str(text or "")
    findings: list[str] = []
    for name, patterns in CRITICAL_OPERATION_PATTERNS.items():
        if any(pattern.search(value) for pattern in patterns):
            findings.append(name)
    return sorted(set(findings))


def is_critical_operation(text: Any) -> bool:
    return bool(critical_operation_findings(text))


def approval_required_payload(text: Any) -> dict[str, Any]:
    findings = critical_operation_findings(text)
    return {
        "approval_required": bool(findings),
        "critical_operation_findings": findings,
        "status": "APPROVAL_REQUIRED" if findings else "ALLOWED_WITH_GATES",
    }
