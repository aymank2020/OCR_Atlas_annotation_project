#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/atlas/OCR_annotation_Atlas}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

for unit in atlas-solver.service atlas-discord-bot.service atlas-command-hub.service; do
  src="${APP_DIR}/${unit}"
  dst="${SYSTEMD_DIR}/${unit}"
  if [[ ! -f "$src" ]]; then
    echo "[install-services] missing unit file: $src" >&2
    exit 1
  fi
  install -m 0644 "$src" "$dst"
done

systemctl daemon-reload
systemctl enable atlas-solver.service
systemctl enable atlas-discord-bot.service

echo "[install-services] installed units to ${SYSTEMD_DIR}"
echo "[install-services] enabled: atlas-solver.service atlas-discord-bot.service"
echo "[install-services] atlas-command-hub.service is installed but intentionally left disabled."
