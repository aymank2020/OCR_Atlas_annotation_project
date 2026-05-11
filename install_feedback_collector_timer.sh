#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/root/OCR_annotation_Atlas}"
RUNNER_SCRIPT="${APP_DIR}/run_feedback_collector_once.sh"
CONFIG_FILE="${CONFIG_FILE:-sample_web_auto_solver_vps.yaml}"
MAX_EPISODES="${MAX_EPISODES:-20}"
FEEDBACK_SKIP_GEMINI="${FEEDBACK_SKIP_GEMINI:-0}"
ON_BOOT_SEC="${ON_BOOT_SEC:-8m}"
ON_ACTIVE_SEC="${ON_ACTIVE_SEC:-30m}"

SERVICE_FILE="/etc/systemd/system/atlas-feedback-collector.service"
TIMER_FILE="/etc/systemd/system/atlas-feedback-collector.timer"

if [[ ! -f "$RUNNER_SCRIPT" ]]; then
  echo "[install] runner script not found: $RUNNER_SCRIPT" >&2
  exit 1
fi

chmod +x "$RUNNER_SCRIPT"

cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=Atlas Feedback/Disputes Collector (one cycle)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory=${APP_DIR}
Environment=APP_DIR=${APP_DIR}
Environment=CONFIG_FILE=${CONFIG_FILE}
Environment=MAX_EPISODES=${MAX_EPISODES}
Environment=FEEDBACK_SKIP_GEMINI=${FEEDBACK_SKIP_GEMINI}
ExecStart=${RUNNER_SCRIPT}
EOF

cat >"$TIMER_FILE" <<EOF
[Unit]
Description=Run Atlas feedback collector periodically

[Timer]
OnBootSec=${ON_BOOT_SEC}
OnUnitActiveSec=${ON_ACTIVE_SEC}
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now atlas-feedback-collector.timer
systemctl start atlas-feedback-collector.service || true

echo "[install] timer status:"
systemctl status atlas-feedback-collector.timer --no-pager -l || true
echo "[install] last service log:"
journalctl -u atlas-feedback-collector.service -n 40 --no-pager || true
