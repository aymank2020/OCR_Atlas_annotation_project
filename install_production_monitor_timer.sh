#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/atlas/OCR_annotation_Atlas}"
RUNNER_SCRIPT="${APP_DIR}/run_production_monitor.sh"
SERVICE_FILE="/etc/systemd/system/atlas-production-monitor.service"
TIMER_FILE="/etc/systemd/system/atlas-production-monitor.timer"

ON_BOOT_SEC="${ON_BOOT_SEC:-5m}"
ON_ACTIVE_SEC="${ON_ACTIVE_SEC:-10m}"
AUTO_RESTART_SOLVER="${AUTO_RESTART_SOLVER:-1}"

if [[ ! -f "$RUNNER_SCRIPT" ]]; then
  echo "[install] production monitor runner not found: $RUNNER_SCRIPT" >&2
  exit 1
fi

chmod +x "$RUNNER_SCRIPT"

cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=Atlas production monitor and Telegram alerts
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory=${APP_DIR}
Environment=APP_DIR=${APP_DIR}
Environment=AUTO_RESTART_SOLVER=${AUTO_RESTART_SOLVER}
ExecStart=/bin/bash ${RUNNER_SCRIPT}
EOF

cat >"$TIMER_FILE" <<EOF
[Unit]
Description=Run Atlas production monitor periodically

[Timer]
OnBootSec=${ON_BOOT_SEC}
OnUnitActiveSec=${ON_ACTIVE_SEC}
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now atlas-production-monitor.timer
systemctl start atlas-production-monitor.service || true

echo "[install] timer status:"
systemctl status atlas-production-monitor.timer --no-pager -l || true
echo "[install] last service log:"
journalctl -u atlas-production-monitor.service -n 30 --no-pager || true
