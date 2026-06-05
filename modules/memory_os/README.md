# Memory OS Dashboard

This module defines the dashboard-side contract for Memory OS visibility.

Scope:
- Read-only `/api/status` payload key: `memory_os`.
- Health marker lookup from optional runtime state files.
- Last context lookup from optional runtime state files.
- Safe DTO only: no raw context, raw payload, terminal output, storage path or secret-like values.

Out of scope:
- Production deploy.
- Runtime state mutation.
- Secret/env/token/private key access.
- IAM, billing, DNS, firewall, destructive database or advertising live-write operations.
