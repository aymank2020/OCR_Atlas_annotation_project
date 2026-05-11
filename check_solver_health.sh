#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/atlas/OCR_annotation_Atlas}"
SOLVER_SERVICE="${SOLVER_SERVICE:-atlas-solver.service}"
SOLVER_LOG_FILE="${SOLVER_LOG_FILE:-$APP_DIR/outputs/solver_service.log}"
HEALTH_LOG_FILE="${HEALTH_LOG_FILE:-$APP_DIR/outputs/solver_health.log}"

# Restart if solver log is stale for too long.
MAX_IDLE_SEC="${MAX_IDLE_SEC:-1800}"
# Skip stale check just after service start to avoid false positives.
MIN_ACTIVE_SEC="${MIN_ACTIVE_SEC:-120}"
# If service is not active, auto-restart it.
RESTART_ON_INACTIVE="${RESTART_ON_INACTIVE:-1}"
# Write a heartbeat line every N runs (0 disables heartbeat lines).
HEARTBEAT_EVERY="${HEARTBEAT_EVERY:-6}"
STATE_FILE="${STATE_FILE:-$APP_DIR/.state/solver_health_state}"

mkdir -p "$(dirname "$HEALTH_LOG_FILE")"
mkdir -p "$(dirname "$STATE_FILE")"

_now_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

_log() {
  printf "%s [solver-health] %s\n" "$(_now_utc)" "$*" >>"$HEALTH_LOG_FILE"
}

_to_int() {
  local v="${1:-0}"
  if [[ "$v" =~ ^[0-9]+$ ]]; then
    echo "$v"
  else
    echo "0"
  fi
}

_restart_solver() {
  _log "action=restart reason=$1 service=$SOLVER_SERVICE"
  if systemctl restart "$SOLVER_SERVICE"; then
    _log "result=restart_ok service=$SOLVER_SERVICE"
  else
    _log "result=restart_failed service=$SOLVER_SERVICE"
    return 1
  fi
}

service_state="$(systemctl is-active "$SOLVER_SERVICE" 2>/dev/null || true)"
if [[ "$service_state" != "active" ]]; then
  if [[ "$RESTART_ON_INACTIVE" == "1" ]]; then
    _restart_solver "inactive:${service_state}"
  else
    _log "status=inactive skip_restart state=${service_state}"
  fi
  exit 0
fi

active_enter_us="$(systemctl show "$SOLVER_SERVICE" -p ActiveEnterTimestampMonotonic --value 2>/dev/null || echo 0)"
active_enter_us="$(_to_int "$active_enter_us")"
uptime_sec_total="$(awk '{print int($1)}' /proc/uptime 2>/dev/null || echo 0)"
uptime_sec_total="$(_to_int "$uptime_sec_total")"
now_us=$((uptime_sec_total * 1000000))
active_for_sec=0
if (( now_us > active_enter_us )); then
  active_for_sec=$(((now_us - active_enter_us) / 1000000))
fi

if (( active_for_sec < MIN_ACTIVE_SEC )); then
  _log "status=grace active_for_sec=${active_for_sec} min_active_sec=${MIN_ACTIVE_SEC}"
  exit 0
fi

if [[ ! -f "$SOLVER_LOG_FILE" ]]; then
  _restart_solver "missing_log_file"
  exit 0
fi

now_epoch="$(date +%s)"
log_mtime="$(stat -c %Y "$SOLVER_LOG_FILE" 2>/dev/null || echo 0)"
log_mtime="$(_to_int "$log_mtime")"
idle_sec=0
if (( now_epoch > log_mtime )); then
  idle_sec=$((now_epoch - log_mtime))
fi

if (( idle_sec > MAX_IDLE_SEC )); then
  _restart_solver "stale_log idle_sec=${idle_sec} max_idle_sec=${MAX_IDLE_SEC}"
  exit 0
fi

run_count=0
if [[ -f "$STATE_FILE" ]]; then
  run_count="$(_to_int "$(cat "$STATE_FILE" 2>/dev/null || echo 0)")"
fi
run_count=$((run_count + 1))
echo "$run_count" >"$STATE_FILE"

if (( HEARTBEAT_EVERY > 0 )) && (( run_count % HEARTBEAT_EVERY == 0 )); then
  _log "status=ok idle_sec=${idle_sec} active_for_sec=${active_for_sec}"
fi

