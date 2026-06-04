# Telegram Asset Manifest Contract

This module fixes the repo-side contract for Telegram asset manifests before any asset download or runtime storage code is connected.

Scope:
- Schema version `1`.
- Network-free validation.
- Telegram download limit fixed at `20971520` bytes.
- SHA-256, MIME and storage metadata contract checks.
- Manifest rejection for raw payloads, file URLs and sensitive credential-like fields.

Out of scope:
- Production deploy.
- Telegram API calls.
- Runtime asset storage mutation.
- Secret/env/private key access.
