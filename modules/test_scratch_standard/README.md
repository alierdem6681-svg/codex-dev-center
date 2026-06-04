# Test Scratch Standard

This module defines the repo-side contract for deterministic, isolated test scratch directories.

Scope:
- Resolve test scratch root from `TEST_SCRATCH_ROOT`, `RUNNER_TEMP`, then `TMPDIR`.
- Reject scratch roots inside the repo checkout.
- Create per-test atomically unique scratch directories.
- Redirect runtime temp/home/cache/config/output env variables while a test context is active.
- Provide a repo write guard for detecting unintended checkout mutations.

Out of scope:
- Production deploy.
- Runtime state/log/report mutation.
- Secret/env/token/private key access.
- IAM, billing, DNS, firewall, destructive database or advertising live-write operations.
