#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════
# setup_gemini_login_hetzner.sh — One-time Google login for Gemini Chat
#
# This script launches Chrome with a virtual display and exposes it via
# VNC so you can login manually from your local machine.
#
# Usage:
#   1. Run this script on the Hetzner server:
#      bash setup_gemini_login_hetzner.sh
#
#   2. From your LOCAL machine, create an SSH tunnel:
#      ssh -L 5900:127.0.0.1:5900 atlas@YOUR_SERVER_IP
#
#   3. Connect a VNC client to localhost:5900
#      (e.g., TigerVNC Viewer, RealVNC, or any VNC client)
#
#   4. Login to Google in the Chrome window
#
#   5. After login, press Ctrl+C in the terminal to stop
#
# Alternative (no VNC): Use SSH X11 forwarding:
#   ssh -X atlas@YOUR_SERVER_IP
#   google-chrome-stable --user-data-dir=.state/gemini_chat_user_data \
#     https://gemini.google.com/app
# ═══════════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

USER_DATA_DIR="${GEMINI_CHAT_USER_DATA_DIR:-.state/gemini_chat_user_data}"
VNC_PORT="${VNC_PORT:-5900}"
DISPLAY_NUM="${DISPLAY_NUM:-99}"
GEMINI_URL="${GEMINI_URL:-https://gemini.google.com/app}"

echo "═══════════════════════════════════════════════════════"
echo " Gemini Chat — One-time Google Login Setup"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "user_data_dir: $USER_DATA_DIR"
echo "vnc_port:      $VNC_PORT"
echo "display:       :$DISPLAY_NUM"
echo ""

# Check dependencies
for cmd in Xvfb x11vnc google-chrome-stable; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "[setup] MISSING: $cmd"
    echo "[setup] Install with: apt install -y xvfb x11vnc google-chrome-stable"
    exit 1
  fi
done

# Create user data directory
mkdir -p "$USER_DATA_DIR"

# Kill any existing Xvfb on this display
pkill -f "Xvfb :$DISPLAY_NUM" 2>/dev/null || true
sleep 1

# Start Xvfb
echo "[setup] starting Xvfb on :$DISPLAY_NUM"
Xvfb ":$DISPLAY_NUM" -screen 0 1920x1080x24 -ac +extension RANDR &
XVFB_PID=$!
sleep 2

# Start VNC server
echo "[setup] starting x11vnc on port $VNC_PORT"
x11vnc -display ":$DISPLAY_NUM" -rfbport "$VNC_PORT" -nopw -forever -shared &
VNC_PID=$!
sleep 1

# Cleanup function
cleanup() {
  echo ""
  echo "[setup] shutting down..."
  kill "$CHROME_PID" 2>/dev/null || true
  kill "$VNC_PID" 2>/dev/null || true
  kill "$XVFB_PID" 2>/dev/null || true
  echo "[setup] done. Session saved in: $USER_DATA_DIR"
  echo ""
  echo "═══════════════════════════════════════════════════════"
  echo " Next steps:"
  echo "   1. Start Chrome CDP service:"
  echo "      systemctl start atlas-chrome-cdp.service"
  echo ""
  echo "   2. Verify Chrome is listening:"
  echo "      curl -s http://127.0.0.1:9222/json/version"
  echo ""
  echo "   3. Restart the solver:"
  echo "      systemctl restart atlas-solver.service"
  echo "═══════════════════════════════════════════════════════"
}
trap cleanup EXIT

# Launch Chrome
echo "[setup] launching Chrome..."
echo ""
echo "═══════════════════════════════════════════════════════"
echo " INSTRUCTIONS:"
echo "   1. From your LOCAL machine, SSH tunnel:"
echo "      ssh -L 5900:127.0.0.1:$VNC_PORT atlas@YOUR_SERVER_IP"
echo ""
echo "   2. Connect VNC client to: localhost:5900"
echo ""
echo "   3. Login to Google in the Chrome window"
echo ""
echo "   4. After login, press Ctrl+C here to save & exit"
echo "═══════════════════════════════════════════════════════"
echo ""

DISPLAY=":$DISPLAY_NUM" google-chrome-stable \
  --user-data-dir="$USER_DATA_DIR" \
  --no-sandbox \
  --test-type \
  --disable-session-crashed-bubble \
  --hide-crash-restore-bubble \
  --disable-dev-shm-usage \
  --disable-gpu \
  --disable-blink-features=AutomationControlled \
  --no-first-run \
  --disable-default-apps \
  --disable-extensions \
  "$GEMINI_URL" &
CHROME_PID=$!

# Wait for user to finish login
wait "$CHROME_PID" 2>/dev/null || true
