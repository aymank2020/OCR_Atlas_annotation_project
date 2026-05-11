#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/atlas/OCR_annotation_Atlas}"
RUNNER_SCRIPT="${APP_DIR}/run_episode_review_refresh.sh"
SERVICE_FILE="/etc/systemd/system/atlas-episode-review-refresh.service"
TIMER_FILE="/etc/systemd/system/atlas-episode-review-refresh.timer"

ON_BOOT_SEC="${ON_BOOT_SEC:-7m}"
ON_ACTIVE_SEC="${ON_ACTIVE_SEC:-15m}"

if [[ ! -f "$RUNNER_SCRIPT" ]]; then
  echo "[install] review refresh runner not found: $RUNNER_SCRIPT" >&2
  exit 1
fi

chmod +x "$RUNNER_SCRIPT"

cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=Atlas episode review refresh
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=atlas
WorkingDirectory=${APP_DIR}
Environment=APP_DIR=${APP_DIR}
ExecStart=${RUNNER_SCRIPT}
EOF

cat >"$TIMER_FILE" <<EOF
[Unit]
Description=Run Atlas episode review refresh periodically

[Timer]
OnBootSec=${ON_BOOT_SEC}
OnUnitActiveSec=${ON_ACTIVE_SEC}
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now atlas-episode-review-refresh.timer
systemctl start atlas-episode-review-refresh.service || true

echo "[install] timer status:"
systemctl status atlas-episode-review-refresh.timer --no-pager -l || true
echo "[install] recent service logs:"
journalctl -u atlas-episode-review-refresh.service -n 30 --no-pager || true
