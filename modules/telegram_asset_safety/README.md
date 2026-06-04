# Telegram Asset Safety Contracts

This module defines the first non-mutating safety contract for Telegram asset handling.
It validates manifest shape, file limits, MIME/extension consistency, checksum matching,
secret redaction, simulator-only Telegram send behavior and dashboard-safe snapshots.

The module does not download files, call the real Telegram API, read secrets, mutate
runtime state or perform production deploy actions.
