#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CODEX_DEV_CENTER_HOME:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PY="${CODEX_PYTHON:-python}"
SCOPE="${CODEX_SMOKE_SCOPE:-production}"

cd "$ROOT"
exec "$PY" supervisor/production_environment_manager.py smoke-test --scope "$SCOPE" "$@"
