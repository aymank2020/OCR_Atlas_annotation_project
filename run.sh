#!/usr/bin/env bash
set -euo pipefail
# ═══════════════════════════════════════════════════════════════════════
# run.sh — Simple production runner for Atlas Web Auto-Solver
#
# Usage:
#   bash run.sh                               # Execute (real submit)
#   bash run.sh --dry                         # Dry-run only (no submit)
#   bash run.sh --max 3                       # Limit to 3 episodes
#   bash run.sh --model gemini-2.5-pro        # Override model
# ═══════════════════════════════════════════════════════════════════════

cd "$(dirname "${BASH_SOURCE[0]}")"

# Activate venv if present
[[ -f .venv/bin/activate && -z "${VIRTUAL_ENV:-}" ]] && source .venv/bin/activate

# Load .env
[[ -f .env ]] && { set -a; source .env; set +a; }

# Determine python
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
[[ -z "$PY" ]] && { echo "❌ Python not found"; exit 1; }

# Config
CONFIG="${CONFIG:-sample_web_auto_solver_production.yaml}"

# Parse simple flags
EXECUTE="--execute"
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry)       EXECUTE=""; shift ;;
    --max)       EXTRA_ARGS+=("--max-episodes" "$2"); shift 2 ;;
    --model)     EXTRA_ARGS+=("--gemini-model" "$2"); shift 2 ;;
    --fallback)  EXTRA_ARGS+=("--use-fallback-key"); shift ;;
    --config)    CONFIG="$2"; shift 2 ;;
    *)           EXTRA_ARGS+=("$1"); shift ;;
  esac
done

echo "═══════════════════════════════════════"
echo " Atlas Auto-Solver — $(date -u '+%Y-%m-%d %H:%M UTC')"
echo " config=$CONFIG"
echo " mode=$([ -n "$EXECUTE" ] && echo 'EXECUTE 🟢' || echo 'DRY-RUN 🟡')"
echo "═══════════════════════════════════════"

"$PY" atlas_web_auto_solver.py \
  --config "$CONFIG" \
  $EXECUTE \
  "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
