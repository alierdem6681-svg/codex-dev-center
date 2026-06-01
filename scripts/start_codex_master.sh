#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/codex-dev-center"
cd "${APP_DIR}"

echo "=========================================="
echo "CODEX MASTER BASLATMA"
echo "=========================================="
echo ""
echo "Codex acilinca asagidaki dosyayi ona gorev olarak verin:"
echo ""
echo "${APP_DIR}/docs/CODEX_MASTER_PROMPT.md"
echo ""
echo "Not: Ilk calistirmada Codex sizden ChatGPT hesabi veya API key ile giris isteyebilir."
echo ""
echo "=========================================="
echo ""

codex
