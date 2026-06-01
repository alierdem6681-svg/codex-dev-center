#!/usr/bin/env bash
set -euo pipefail
cd /opt/codex-dev-center
TITLE="${1:-Yeni görev}"
DESCRIPTION="${2:-$TITLE}"
RISK="${3:-low}"
python3 supervisor/supervisor_cli.py add-task --title "$TITLE" --description "$DESCRIPTION" --risk "$RISK"
