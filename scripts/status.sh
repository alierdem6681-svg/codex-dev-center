#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/codex-dev-center"
cd "${APP_DIR}"

echo "=========================================="
echo "CODEX DEV CENTER STATUS"
echo "=========================================="
echo "Date: $(date -Is)"
echo "User: $(id -un)"
echo "Directory: ${APP_DIR}"
echo ""

echo "Codex:"
if command -v codex >/dev/null 2>&1; then
  echo "  path: $(command -v codex)"
  echo "  version: $(codex --version 2>/dev/null || true)"
else
  echo "  NOT FOUND"
fi

echo ""
echo "Docker:"
systemctl is-active docker || true

echo ""
echo "Project tree:"
tree -L 2 "${APP_DIR}" | head -120

echo ""
echo "System state:"
cat "${APP_DIR}/state/system_state.json" 2>/dev/null || true
