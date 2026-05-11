#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/root/OCR_annotation_Atlas}"
UPLOADER_SCRIPT="${APP_DIR}/upload_outputs_to_drive.sh"
SERVICE_FILE="/etc/systemd/system/atlas-drive-uploader.service"
TIMER_FILE="/etc/systemd/system/atlas-drive-uploader.timer"

# You can override these before running this installer:
# export RCLONE_REMOTE=gdrive
# export RCLONE_PATH=OCR_annotation_Atlas/vps_outputs
# export GDRIVE_ROOT_FOLDER_ID=1kLe9Ai7swxh9Nx2NifD9Fcodf85AfyAG
# export MIN_AGE=30m
# export EPISODE_LAYOUT_MIN_AGE=30m

RCLONE_REMOTE="${RCLONE_REMOTE:-gdrive}"
RCLONE_PATH="${RCLONE_PATH:-OCR_annotation_Atlas/vps_outputs}"
GDRIVE_ROOT_FOLDER_ID="${GDRIVE_ROOT_FOLDER_ID:-1kLe9Ai7swxh9Nx2NifD9Fcodf85AfyAG}"
MIN_AGE="${MIN_AGE:-30m}"
EPISODE_LAYOUT_MIN_AGE="${EPISODE_LAYOUT_MIN_AGE:-${MIN_AGE}}"

if [[ ! -f "$UPLOADER_SCRIPT" ]]; then
  echo "[install] uploader script not found: $UPLOADER_SCRIPT" >&2
  exit 1
fi

chmod +x "$UPLOADER_SCRIPT"

cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=Upload Atlas outputs to Google Drive
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
Environment=APP_DIR=${APP_DIR}
Environment=RCLONE_REMOTE=${RCLONE_REMOTE}
Environment=RCLONE_PATH=${RCLONE_PATH}
Environment=GDRIVE_ROOT_FOLDER_ID=${GDRIVE_ROOT_FOLDER_ID}
Environment=MIN_AGE=${MIN_AGE}
Environment=EPISODE_LAYOUT_MIN_AGE=${EPISODE_LAYOUT_MIN_AGE}
ExecStart=${UPLOADER_SCRIPT}
EOF

cat >"$TIMER_FILE" <<'EOF'
[Unit]
Description=Run Atlas Drive uploader every 10 minutes

[Timer]
OnBootSec=4m
OnUnitActiveSec=10m
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now atlas-drive-uploader.timer
systemctl start atlas-drive-uploader.service || true

echo "[install] timer status:"
systemctl status atlas-drive-uploader.timer --no-pager -l || true
echo "[install] last service log:"
journalctl -u atlas-drive-uploader.service -n 30 --no-pager || true
