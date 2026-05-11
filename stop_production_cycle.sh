#!/usr/bin/env bash
set -euo pipefail

SOLVER_SERVICE="${SOLVER_SERVICE:-atlas-solver.service}"
BOT_SERVICE="${BOT_SERVICE:-atlas-discord-bot.service}"
STOP_BOT="${STOP_BOT:-0}"
PRODUCTION_FLAG_PATH="${PRODUCTION_FLAG_PATH:-/srv/atlas/OCR_annotation_Atlas/.state/production_enabled.flag}"

systemctl stop "$SOLVER_SERVICE" || true
rm -f "$PRODUCTION_FLAG_PATH"
echo "[prod-stop] stopped ${SOLVER_SERVICE}"

if [[ "$STOP_BOT" == "1" ]]; then
  systemctl stop "$BOT_SERVICE" || true
  echo "[prod-stop] stopped ${BOT_SERVICE}"
fi

systemctl status "$SOLVER_SERVICE" --no-pager -l || true
if [[ "$STOP_BOT" == "1" ]]; then
  systemctl status "$BOT_SERVICE" --no-pager -l || true
fi
