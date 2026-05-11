#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/atlas/OCR_annotation_Atlas}"
HEALTH_SCRIPT="${APP_DIR}/check_solver_health.sh"
SERVICE_FILE="/etc/systemd/system/atlas-solver-health.service"
TIMER_FILE="/etc/systemd/system/atlas-solver-health.timer"

# Tunables (can be exported before install):
# export SOLVER_SERVICE=atlas-solver.service
# export MAX_IDLE_SEC=1800
# export MIN_ACTIVE_SEC=120
# export HEARTBEAT_EVERY=6
# export ON_BOOT_SEC=6m
# export ON_ACTIVE_SEC=5m

SOLVER_SERVICE="${SOLVER_SERVICE:-atlas-solver.service}"
MAX_IDLE_SEC="${MAX_IDLE_SEC:-1800}"
MIN_ACTIVE_SEC="${MIN_ACTIVE_SEC:-120}"
HEARTBEAT_EVERY="${HEARTBEAT_EVERY:-6}"
ON_BOOT_SEC="${ON_BOOT_SEC:-6m}"
ON_ACTIVE_SEC="${ON_ACTIVE_SEC:-5m}"

if [[ ! -f "$HEALTH_SCRIPT" ]]; then
  echo "[install] health script not found: $HEALTH_SCRIPT" >&2
  exit 1
fi

chmod +x "$HEALTH_SCRIPT"

cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=Atlas solver health check
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
Environment=APP_DIR=${APP_DIR}
Environment=SOLVER_SERVICE=${SOLVER_SERVICE}
Environment=MAX_IDLE_SEC=${MAX_IDLE_SEC}
Environment=MIN_ACTIVE_SEC=${MIN_ACTIVE_SEC}
Environment=HEARTBEAT_EVERY=${HEARTBEAT_EVERY}
ExecStart=${HEALTH_SCRIPT}
EOF

cat >"$TIMER_FILE" <<EOF
[Unit]
Description=Run Atlas solver health check periodically

[Timer]
OnBootSec=${ON_BOOT_SEC}
OnUnitActiveSec=${ON_ACTIVE_SEC}
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now atlas-solver-health.timer
systemctl start atlas-solver-health.service || true

echo "[install] timer status:"
systemctl status atlas-solver-health.timer --no-pager -l || true
echo "[install] recent service logs:"
journalctl -u atlas-solver-health.service -n 30 --no-pager || true

