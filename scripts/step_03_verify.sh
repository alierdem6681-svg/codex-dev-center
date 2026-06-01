#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/codex-dev-center"
TASK_ID="TASK-20260601-0001"
LOG_FILE="${APP_DIR}/logs/${TASK_ID}.log"

cd "${APP_DIR}"

{
  echo "=========================================="
  echo "STEP 03 VERIFY"
  echo "Date: $(date -Is)"
  echo "Task: ${TASK_ID}"
  echo "=========================================="
  echo ""

  echo "[1/7] JSON kontrolu"
  python3 -m json.tool state/system_state.json >/dev/null
  python3 -m json.tool state/workers.json >/dev/null
  python3 -m json.tool state/task_queue.json >/dev/null
  python3 -m json.tool supervisor/roles.json >/dev/null
  echo "OK"
  echo ""

  echo "[2/7] Python derleme kontrolu"
  python3 -m compileall -q supervisor web_panel
  echo "OK"
  echo ""

  echo "[3/7] Supervisor init"
  python3 -m supervisor.supervisor init
  echo ""

  echo "[4/7] Supervisor status"
  python3 -m supervisor.supervisor status >/dev/null
  echo "OK"
  echo ""

  echo "[5/7] Telegram normal cevap guard"
  NORMAL_OUTPUT="$(python3 -m supervisor.supervisor guard-output 'Normal kısa cevap aynen geçmeli.')"
  test "${NORMAL_OUTPUT}" = "Normal kısa cevap aynen geçmeli."
  echo "OK"
  echo ""

  echo "[6/7] Telegram teknik çıktı guard"
  TECH_OUTPUT="$(python3 -m supervisor.supervisor guard-output --task-id "${TASK_ID}" 'Traceback (most recent call last): example stack trace')"
  case "${TECH_OUTPUT}" in
    Teknik\ çıktı\ Telegram*) echo "OK" ;;
    *) echo "Beklenmeyen output guard sonucu: ${TECH_OUTPUT}" && exit 1 ;;
  esac
  echo ""

  echo "[7/7] Deploy risk kapısı"
  python3 -m supervisor.supervisor check-deploy 'production deploy isteği' | python3 -m json.tool >/dev/null
  echo "OK"
  echo ""

  echo "STEP 03 doğrulama tamamlandı."
} | tee "${LOG_FILE}"

echo "$(date -Is) ${TASK_ID} STEP_03 verification completed" >> "${APP_DIR}/logs/system.log"
