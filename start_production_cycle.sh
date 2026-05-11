#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/atlas/OCR_annotation_Atlas}"
SOLVER_SERVICE="${SOLVER_SERVICE:-atlas-solver.service}"
BOT_SERVICE="${BOT_SERVICE:-atlas-discord-bot.service}"
START_SOLVER="${START_SOLVER:-1}"
START_BOT="${START_BOT:-1}"
START_SOLVER_HEALTH_TIMER="${START_SOLVER_HEALTH_TIMER:-1}"
START_REVIEW_TIMER="${START_REVIEW_TIMER:-1}"
START_DRIVE_TIMER="${START_DRIVE_TIMER:-1}"
START_FEEDBACK_TIMER="${START_FEEDBACK_TIMER:-1}"
START_MONITOR_TIMER="${START_MONITOR_TIMER:-1}"
PRODUCTION_FLAG_PATH="${PRODUCTION_FLAG_PATH:-$APP_DIR/.state/production_enabled.flag}"
ROTATE_LOGS_ON_START="${ROTATE_LOGS_ON_START:-1}"
OUTPUTS_DIR="${OUTPUTS_DIR:-$APP_DIR/outputs}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-solver)
      START_SOLVER=0
      ;;
    --with-solver)
      START_SOLVER=1
      ;;
    --no-bot)
      START_BOT=0
      ;;
    --with-bot)
      START_BOT=1
      ;;
    *)
      echo "[prod-start] unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

TIMERS=(
  "atlas-solver-health.timer:${START_SOLVER_HEALTH_TIMER}"
  "atlas-episode-review-refresh.timer:${START_REVIEW_TIMER}"
  "atlas-drive-uploader.timer:${START_DRIVE_TIMER}"
  "atlas-feedback-collector.timer:${START_FEEDBACK_TIMER}"
  "atlas-production-monitor.timer:${START_MONITOR_TIMER}"
)

cd "$APP_DIR"

if [[ ! -f ".env" ]]; then
  echo "[prod-start] missing .env at ${APP_DIR}/.env" >&2
  exit 1
fi

if [[ ! -x "run_solver_hetzner.sh" ]]; then
  echo "[prod-start] missing executable runner: ${APP_DIR}/run_solver_hetzner.sh" >&2
  exit 1
fi

echo "[prod-start] app_dir=${APP_DIR}"
echo "[prod-start] commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "[prod-start] accounts_index=${ATLAS_ACCOUNTS_INDEX:-configs/accounts/index.yaml}"

systemctl daemon-reload || true

restart_or_start() {
  local unit="$1"
  if systemctl is-active --quiet "$unit"; then
    systemctl restart "$unit"
  else
    systemctl start "$unit"
  fi
}

rotate_log_if_present() {
  local file_path="$1"
  if [[ ! -f "$file_path" ]]; then
    return 0
  fi
  if [[ ! -s "$file_path" ]]; then
    : >"$file_path"
    return 0
  fi
  local archive_dir="$OUTPUTS_DIR/archive"
  local base_name
  local stamp
  base_name="$(basename "$file_path")"
  stamp="$(date -u '+%Y%m%dT%H%M%SZ')"
  mkdir -p "$archive_dir"
  mv "$file_path" "$archive_dir/${base_name}.${stamp}"
}

if [[ "$ROTATE_LOGS_ON_START" == "1" ]]; then
  rotate_log_if_present "$OUTPUTS_DIR/solver_service.log"
  rotate_log_if_present "$OUTPUTS_DIR/production_monitor.log"
  rotate_log_if_present "$OUTPUTS_DIR/discord_bot_service.log"
fi

for item in "${TIMERS[@]}"; do
  unit="${item%%:*}"
  enabled="${item##*:}"
  if [[ "$enabled" != "1" ]]; then
    continue
  fi
  if systemctl list-unit-files "$unit" >/dev/null 2>&1; then
    systemctl enable --now "$unit" >/dev/null 2>&1 || systemctl start "$unit" || true
    echo "[prod-start] timer active: $unit"
  else
    echo "[prod-start] timer missing, skipped: $unit"
  fi
done

if [[ "$START_BOT" == "1" ]]; then
  restart_or_start "$BOT_SERVICE"
  echo "[prod-start] bot active: $BOT_SERVICE"
fi

if [[ "$START_SOLVER" == "1" ]]; then
  mkdir -p "$(dirname "$PRODUCTION_FLAG_PATH")"
  date -u '+%Y-%m-%dT%H:%M:%SZ' >"$PRODUCTION_FLAG_PATH"
  restart_or_start "$SOLVER_SERVICE"
  echo "[prod-start] solver active: $SOLVER_SERVICE"
else
  rm -f "$PRODUCTION_FLAG_PATH"
  if systemctl is-active --quiet "$SOLVER_SERVICE"; then
    systemctl stop "$SOLVER_SERVICE" || true
    echo "[prod-start] solver stopped because START_SOLVER=0"
  else
    echo "[prod-start] solver start skipped by START_SOLVER=0"
  fi
fi

echo
echo "[prod-start] status snapshot:"
echo "[prod-start] production_flag=$([[ -f "$PRODUCTION_FLAG_PATH" ]] && echo enabled || echo disabled)"
systemctl status "$SOLVER_SERVICE" --no-pager -l || true
systemctl status "$BOT_SERVICE" --no-pager -l || true
for item in "${TIMERS[@]}"; do
  unit="${item%%:*}"
  systemctl status "$unit" --no-pager -l || true
done

echo
echo "[prod-start] follow logs:"
echo "  journalctl -u ${SOLVER_SERVICE} -f"
echo "  journalctl -u ${BOT_SERVICE} -f"
