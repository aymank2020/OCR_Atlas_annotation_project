#!/bin/bash
# One-time setup script for Google login on Hetzner VPS
# This script launches Chrome via VNC so you can login manually
# Run this ONCE after installing the service, BEFORE starting atlas-chrome-cdp.service

set -e

USER_DATA_DIR="${USER_DATA_DIR:-/srv/atlas/OCR_annotation_Atlas/.state/gemini_chat_user_data}"
VNC_PORT="${VNC_PORT:-5900}"
CHROME_BIN="${CHROME_BIN:-/usr/bin/google-chrome-stable}"

echo "================================================"
echo "Atlas Gemini Chat Web - Google Login Setup"
echo "================================================"
echo ""
echo "This script will:"
echo "1. Start a virtual X11 display (Xvfb)"
echo "2. Start x11vnc to share it remotely"
echo "3. Launch Chrome for manual Google login"
echo "4. Save the session to: $USER_DATA_DIR"
echo ""
echo "After login, the session persists for atlas-chrome-cdp.service"
echo ""

# Check if already logged in
if [ -d "$USER_DATA_DIR/Default" ]; then
    echo "⚠️  Existing Chrome profile found at: $USER_DATA_DIR"
    read -p "Continue anyway? (y/N): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted. Session already exists."
        exit 0
    fi
fi

# Create user data directory
mkdir -p "$USER_DATA_DIR"

# Kill any existing Xvfb or Chrome processes
echo "Cleaning up any existing processes..."
pkill -f "Xvfb.*:99" 2>/dev/null || true
pkill -f "x11vnc.*5900" 2>/dev/null || true
pkill -f "chrome.*gemini_chat_user_data" 2>/dev/null || true
sleep 2

# Start Xvfb
echo "Starting virtual display (Xvfb on :99)..."
/usr/bin/Xvfb :99 -screen 0 1920x1080x24 -ac +extension RANDR +extension GLX &
XVFB_PID=$!
sleep 2

# Verify Xvfb is running
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "❌ Failed to start Xvfb"
    exit 1
fi

# Start x11vnc for remote access
echo "Starting VNC server on port $VNC_PORT..."
/usr/bin/x11vnc -display :99 -rfbport $VNC_PORT -forever -shared -bg -o /tmp/atlas_vnc.log 2>/dev/null || {
    echo "⚠️  x11vnc not installed or failed to start"
    echo "   You can try SSH tunneling instead:"
    echo "   ssh -L 9222:127.0.0.1:9222 atlas@<server-ip>"
    echo "   Then access: http://127.0.0.1:9222"
}

# Wait for VNC to start
sleep 2

echo ""
echo "==========================================="
echo "✅ VNC Server is running on port $VNC_PORT"
echo ""
echo "📡 To connect from your local machine:"
echo "   vnc://<server-ip>:$VNC_PORT"
echo ""
echo "Or use an SSH tunnel:"
echo "   ssh -L 5900:127.0.0.1:$VNC_PORT atlas@<server-ip>"
echo "   Then connect to: localhost:5900"
echo ""
echo "🌐 Chrome will open to gemini.google.com/app"
echo "==========================================="
echo ""

# Launch Chrome with Gemini
echo "Launching Chrome..."
DISPLAY=:99 "$CHROME_BIN" \
    --remote-debugging-port=9222 \
    --user-data-dir="$USER_DATA_DIR" \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --window-size=1920,1080 \
    https://gemini.google.com/app &

CHROME_PID=$!

echo ""
echo "Chrome PID: $CHROME_PID"
echo ""
echo "=========================================="
echo "👉 ACTION REQUIRED:"
echo "=========================================="
echo ""
echo "1. Connect via VNC (or SSH tunnel)"
echo "2. Login to your Google account in Chrome"
echo "3. Accept any prompts (cookies, etc.)"
echo "4. Verify you see the Gemini chat interface"
echo "5. Press Enter HERE when done to save session"
echo ""
echo "=========================================="

# Wait for user to complete login
read -p "Press Enter when you've completed the Google login... " dummy

echo ""
echo "Saving session..."

# Kill Chrome gracefully
kill $CHROME_PID 2>/dev/null || true
sleep 3

# Kill Chrome forcefully if still running
pkill -9 -f "chrome.*gemini_chat_user_data" 2>/dev/null || true
sleep 2

# Kill VNC and Xvfb
pkill -f "x11vnc.*5900" 2>/dev/null || true
kill $XVFB_PID 2>/dev/null || true

echo ""
echo "==========================================="
echo "✅ Google session saved to: $USER_DATA_DIR"
echo ""
echo "Now run:"
echo "  sudo systemctl enable atlas-chrome-cdp.service"
echo "  sudo systemctl start atlas-chrome-cdp.service"
echo ""
echo "Then verify:"
echo "  curl -s http://127.0.0.1:9222/json/version"
echo "==========================================="