#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/atlas/OCR_annotation_Atlas}"
PRIMARY_ACCOUNT="${PRIMARY_ACCOUNT:-danatimer}"
DISABLE_SECONDARY_ACCOUNT="${DISABLE_SECONDARY_ACCOUNT:-0}"
SECONDARY_ACCOUNT="${SECONDARY_ACCOUNT:-wafaabayoumi}"
LEGACY_PRIMARY_ACCOUNT="${LEGACY_PRIMARY_ACCOUNT:-aymankamel}"

ENV_FILE="${APP_DIR}/.env"
INDEX_FILE="${APP_DIR}/configs/accounts/index.yaml"
PRIMARY_STATE="${APP_DIR}/.state/accounts/${PRIMARY_ACCOUNT}/atlas_auth.json"
LEGACY_PRIMARY_STATE="${APP_DIR}/.state/accounts/${LEGACY_PRIMARY_ACCOUNT}/atlas_auth.json"
HEALTH_SERVICE="/etc/systemd/system/atlas-solver-health.service"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[finalize] missing env file: ${ENV_FILE}" >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

PRIMARY_ACCOUNT_ENV_SUFFIX="$(printf '%s' "${PRIMARY_ACCOUNT}" | tr '[:lower:]-' '[:upper:]_')"

if [[ "${PRIMARY_ACCOUNT}" != "${LEGACY_PRIMARY_ACCOUNT}" ]] && [[ -f "${LEGACY_PRIMARY_STATE}" ]] && [[ ! -f "${PRIMARY_STATE}" ]]; then
  mkdir -p "$(dirname "${PRIMARY_STATE}")"
  cp "${LEGACY_PRIMARY_STATE}" "${PRIMARY_STATE}"
fi

sed -i '/^# BEGIN_HETZNER_ACCOUNT_ALIASES$/,/^# END_HETZNER_ACCOUNT_ALIASES$/d' "${ENV_FILE}"
cat >>"${ENV_FILE}" <<EOF

# BEGIN_HETZNER_ACCOUNT_ALIASES
ATLAS_LOGIN_EMAIL_${PRIMARY_ACCOUNT_ENV_SUFFIX}="${ATLAS_LOGIN_EMAIL:-}"
ATLAS_EMAIL_${PRIMARY_ACCOUNT_ENV_SUFFIX}="${ATLAS_EMAIL:-${ATLAS_LOGIN_EMAIL:-}}"
GMAIL_EMAIL_${PRIMARY_ACCOUNT_ENV_SUFFIX}="${GMAIL_EMAIL:-${GMAIL_USER:-}}"
GMAIL_APP_PASSWORD_${PRIMARY_ACCOUNT_ENV_SUFFIX}="${GMAIL_APP_PASSWORD:-}"
GEMINI_API_KEYS_PAID_POOL_${PRIMARY_ACCOUNT_ENV_SUFFIX}="${GEMINI_API_KEYS_PAID_POOL:-${GEMINI_API_KEYS_POOL:-}}"
GEMINI_API_KEY_PAID_EPISODE_EVAL_${PRIMARY_ACCOUNT_ENV_SUFFIX}="${GEMINI_API_KEY_PAID_EPISODE_EVAL:-${GEMINI_API_KEY_EPISODE_EVAL:-}}"
GEMINI_API_KEY_PAID_SECONDARY_${PRIMARY_ACCOUNT_ENV_SUFFIX}="${GEMINI_API_KEY_PAID_SECONDARY:-${GEMINI_API_KEY_FALLBACK:-}}"
# END_HETZNER_ACCOUNT_ALIASES
EOF

if [[ "${DISABLE_SECONDARY_ACCOUNT}" == "1" ]] && [[ -f "${INDEX_FILE}" ]]; then
  perl -0pi -e "s/(  - name: ${SECONDARY_ACCOUNT}\\n    config: [^\\n]+\\n    enabled:) true/\\1 false/" "${INDEX_FILE}"
fi

chmod 600 "${ENV_FILE}" || true
chown atlas:atlas "${ENV_FILE}" || true
if [[ -d "${APP_DIR}/.state" ]]; then
  chown -R atlas:atlas "${APP_DIR}/.state" || true
fi
if [[ -d "${APP_DIR}/outputs" ]]; then
  chown -R atlas:atlas "${APP_DIR}/outputs" || true
fi

if [[ -f "${HEALTH_SERVICE}" ]]; then
  sed -i 's/^User=.*/User=root/' "${HEALTH_SERVICE}"
fi

chmod +x \
  "${APP_DIR}/run_solver_hetzner.sh" \
  "${APP_DIR}/run_discord_bot_service.sh" \
  "${APP_DIR}/run_command_hub_local.sh" \
  "${APP_DIR}/install_hetzner_services.sh" \
  "${APP_DIR}/install_solver_health_timer.sh" \
  "${APP_DIR}/check_solver_health.sh"

systemctl daemon-reload
systemctl restart atlas-solver-health.timer
systemctl restart atlas-solver.service
systemctl restart atlas-discord-bot.service

echo "[finalize] atlas-solver.service"
systemctl status atlas-solver.service --no-pager -l || true
echo "[finalize] atlas-discord-bot.service"
systemctl status atlas-discord-bot.service --no-pager -l || true
echo "[finalize] atlas-solver-health.timer"
systemctl status atlas-solver-health.timer --no-pager -l || true
