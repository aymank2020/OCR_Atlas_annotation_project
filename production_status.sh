#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/atlas/OCR_annotation_Atlas}"
SOLVER_SERVICE="${SOLVER_SERVICE:-atlas-solver.service}"
BOT_SERVICE="${BOT_SERVICE:-atlas-discord-bot.service}"
PRODUCTION_FLAG_PATH="${PRODUCTION_FLAG_PATH:-$APP_DIR/.state/production_enabled.flag}"

cd "$APP_DIR"

echo "[prod-status] app_dir=${APP_DIR}"
echo "[prod-status] commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "[prod-status] accounts_index=${ATLAS_ACCOUNTS_INDEX:-configs/accounts/index.yaml}"
echo "[prod-status] production_flag=$([[ -f "$PRODUCTION_FLAG_PATH" ]] && echo enabled || echo disabled)"
echo

for unit in \
  "$SOLVER_SERVICE" \
  "$BOT_SERVICE" \
  atlas-solver-health.timer \
  atlas-episode-review-refresh.timer \
  atlas-drive-uploader.timer \
  atlas-feedback-collector.timer \
  atlas-production-monitor.timer
do
  systemctl status "$unit" --no-pager -l || true
  echo
done

echo "[prod-status] recent solver log:"
journalctl -u "$SOLVER_SERVICE" -n 40 --no-pager || true
echo
echo "[prod-status] recent production monitor log:"
journalctl -u atlas-production-monitor.service -n 30 --no-pager || true
