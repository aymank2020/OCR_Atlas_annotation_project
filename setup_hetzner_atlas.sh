#!/usr/bin/env bash
set -euo pipefail

APP_USER="${APP_USER:-atlas}"
APP_GROUP="${APP_GROUP:-atlas}"
APP_DIR="${APP_DIR:-/srv/atlas/OCR_annotation_Atlas}"
REPO_URL="${REPO_URL:-https://github.com/aymank2020/OCR_Annotation_Atlas.git}"
BRANCH="${BRANCH:-main}"
SWAP_SIZE_GB="${SWAP_SIZE_GB:-2}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_GOOGLE_CHROME="${INSTALL_GOOGLE_CHROME:-1}"

install_google_chrome() {
  if command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1; then
    echo "[setup] google chrome already installed"
    return
  fi
  if [[ "${INSTALL_GOOGLE_CHROME}" != "1" ]]; then
    echo "[setup] skipping google chrome install (INSTALL_GOOGLE_CHROME=${INSTALL_GOOGLE_CHROME})"
    return
  fi
  local deb="/tmp/google-chrome-stable_current_amd64.deb"
  curl -fsSL "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb" -o "$deb"
  apt-get install -y "$deb" || apt-get -f install -y
  rm -f "$deb"
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "[setup] please run as root or via sudo" >&2
    exit 1
  fi
}

ensure_user() {
  if ! id "$APP_USER" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash "$APP_USER"
  fi
}

ensure_swap() {
  if [[ "${SWAP_SIZE_GB}" == "0" ]]; then
    echo "[setup] swap creation disabled"
    return
  fi
  if swapon --show | grep -q '/swapfile'; then
    echo "[setup] swapfile already active"
    return
  fi
  fallocate -l "${SWAP_SIZE_GB}G" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
}

bootstrap_repo() {
  mkdir -p "$(dirname "$APP_DIR")"
  if [[ ! -d "${APP_DIR}/.git" ]]; then
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  else
    git -C "$APP_DIR" fetch origin
    git -C "$APP_DIR" checkout "$BRANCH"
    git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
  fi
  chown -R "${APP_USER}:${APP_GROUP}" "$(dirname "$APP_DIR")"
}

install_runtime() {
  apt-get update -y
  apt-get install -y git ffmpeg curl ca-certificates python3-venv python3-pip xvfb

  sudo -u "$APP_USER" mkdir -p "$APP_DIR/outputs" "$APP_DIR/logs" "$APP_DIR/.state/accounts"
  sudo -u "$APP_USER" bash -lc "
    cd '$APP_DIR'
    ${PYTHON_BIN} -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip wheel setuptools
    pip install -r requirements.txt
    python -m playwright install chromium
  "
  "$APP_DIR/.venv/bin/python" -m playwright install --with-deps chromium
  install_google_chrome
}

install_services() {
  chmod +x \
    "$APP_DIR/run_solver_hetzner.sh" \
    "$APP_DIR/run_discord_bot_service.sh" \
    "$APP_DIR/run_command_hub_local.sh" \
    "$APP_DIR/install_hetzner_services.sh" \
    "$APP_DIR/install_solver_health_timer.sh" \
    "$APP_DIR/check_solver_health.sh"

  APP_DIR="$APP_DIR" "$APP_DIR/install_hetzner_services.sh"
  APP_DIR="$APP_DIR" "$APP_DIR/install_solver_health_timer.sh"
}

show_next_steps() {
  cat <<EOF
[setup] complete
[setup] edit secrets in: ${APP_DIR}/.env
[setup] review account index: ${APP_DIR}/configs/accounts/index.yaml
[setup] start solver: systemctl start atlas-solver.service
[setup] start discord bot: systemctl start atlas-discord-bot.service
[setup] on-demand command hub: systemctl start atlas-command-hub.service
[setup] tunnel example: ssh -L 8500:127.0.0.1:8500 ${APP_USER}@$(hostname -I | awk '{print $1}')
EOF
}

require_root
ensure_user
ensure_swap
bootstrap_repo
install_runtime
install_services
show_next_steps
