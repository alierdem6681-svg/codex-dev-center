#!/usr/bin/env bash
set -euo pipefail
cd /opt/codex-dev-center
python3 supervisor/supervisor_cli.py status
