# Safe Test Scratch Standard

## Purpose

Tests must not write runtime state, cache, config, logs or output files into the repo checkout. Each test should use an isolated scratch directory outside the repo, then clean it up unless explicit debug retention is enabled.

## Scratch Root Resolution

The shared scratch root is resolved in this order:

1. `TEST_SCRATCH_ROOT`
2. `$RUNNER_TEMP/test-scratch`
3. `$TMPDIR/test-scratch`
4. `tempfile.gettempdir()/test-scratch`

The resolved scratch root is rejected if it is inside the repository.

## Per-Test Directory Format

`tests.safe_test_scratch.make_test_scratch_dir()` creates directories with this shape:

`{suite}/{worker_id}/{test_name_hash}-{pid}-{counter}`

The final directory is created atomically with `mkdir(exist_ok=False)` retry behavior, so parallel test workers do not collide.

## Runtime Environment Redirects

`tests.safe_test_scratch.test_scratch()` redirects these variables into the active scratch directory for the context lifetime:

- `TMPDIR`
- `TEMP`
- `TMP`
- `HOME`
- `XDG_CACHE_HOME`
- `XDG_CONFIG_HOME`
- `CODEX_TEST_OUTPUT_DIR`
- `TEST_SCRATCH_ACTIVE_DIR`

The helper also redirects Python `tempfile` resolution during the context, then restores the previous environment.

## Repo Write Guard

`tests.safe_test_scratch.guard_repo_clean()` captures file metadata before and after a test block and fails if files are created, deleted or modified outside an explicit allowlist.

The guard does not read file contents. It skips transient development directories such as `.git`, `__pycache__`, `.pytest_cache`, virtualenv folders and `node_modules`.

## Debug Retention

Scratch directories are deleted on context exit by default. Set `TEST_SCRATCH_KEEP=1` or `KEEP_TEST_SCRATCH=1` only during local debugging to retain the active scratch directory.

## Out Of Scope

- Production deploy.
- Staging deploy.
- Runtime `state/`, `logs/`, `reports/` mutation.
- Secret/env/token/private key access or changes.
- IAM, billing, DNS, firewall, destructive database or advertising platform live-write operations.
