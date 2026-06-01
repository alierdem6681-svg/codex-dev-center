#!/usr/bin/env bash
set -euo pipefail
cd /opt/codex-dev-center
python3 supervisor/codex_quality_gate.py status
