#!/usr/bin/env bash
set -euo pipefail

# Safe update helper:
# - pulls latest code from origin/<branch>
# - preserves local runtime secrets/settings (e.g. .env and server YAML)
# - avoids destructive git reset/hard operations

BRANCH="${1:-main}"
APP_DIR="${2:-$(pwd)}"
REMOTE_URL="${3:-https://github.com/aymank2020/OCR_Annotation_Atlas.git}"

cd "$APP_DIR"
if [ ! -d .git ]; then
  echo "[safe-update] .git is missing. Bootstrapping git metadata from remote..."
  TMP="$(mktemp -d)"
  git clone --no-checkout "$REMOTE_URL" "$TMP/repo"
  cp -a "$TMP/repo/.git" .
  rm -rf "$TMP"
  echo "[safe-update] git metadata restored."
fi

TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${APP_DIR}/.safe_update_backups/${TS}"
mkdir -p "$BACKUP_DIR"
DID_STASH=0
STASH_NAME="safe-update-autostash-${TS}"
AUTO_STASH="${SAFE_UPDATE_AUTOSTASH:-1}"

# Trap to ensure stash is restored even if git pull fails (set -e)
cleanup_stash() {
  if [ "$DID_STASH" -eq 1 ]; then
    if git stash list | grep -q "$STASH_NAME"; then
      echo "[safe-update] restoring autostash due to script exit..."
      git stash pop --index || echo "[safe-update] warning: stash restore had conflicts. See: git stash list"
    fi
  fi
}
trap cleanup_stash EXIT

preserve_paths=(
  ".env"
  "configs/production_hetzner.yaml"
  "configs/accounts"
  "sample_web_auto_solver_vps.yaml"
  "sample_web_auto_solver.yaml"
  "sample_web_auto_solver_production.yaml"
  "sample_web_auto_solver_no_complete.yaml"
  ".state/atlas_auth.json"
  ".state/accounts"
)

echo "[safe-update] backup dir: $BACKUP_DIR"
for rel in "${preserve_paths[@]}"; do
  if [ -e "$rel" ]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
    cp -a "$rel" "$BACKUP_DIR/$rel"
    echo "[safe-update] backed up: $rel"
  fi
done

if [ "$AUTO_STASH" = "1" ]; then
  if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
    if git stash push --include-untracked -m "$STASH_NAME" >/dev/null; then
      DID_STASH=1
      echo "[safe-update] autostash created: $STASH_NAME"
    fi
  fi
fi

git fetch origin
git pull --ff-only origin "$BRANCH"

# Stash restoration is now handled by the EXIT trap above

# Restore preserved local runtime files (if they existed before update)
for rel in "${preserve_paths[@]}"; do
  if [ -e "$BACKUP_DIR/$rel" ]; then
    mkdir -p "$(dirname "$rel")"
    cp -a "$BACKUP_DIR/$rel" "$rel"
    echo "[safe-update] restored: $rel"
  fi
done

# Self-heal: if .env is missing, try restoring latest historical backup copy.
if [ ! -f ".env" ]; then
  LAST_ENV="$(find "${APP_DIR}/.safe_update_backups" -type f -path "*/.env" 2>/dev/null | sort | tail -n1 || true)"
  if [ -n "${LAST_ENV:-}" ] && [ -f "$LAST_ENV" ]; then
    cp -f "$LAST_ENV" ".env"
    echo "[safe-update] restored: .env (historical backup)"
  fi
fi

if [ -f ".env" ]; then
  chmod 600 .env || true
fi

echo "[safe-update] done. branch=origin/$BRANCH"
