# Gemini Chat Web Setup on Hetzner VPS

This guide explains how to set up Gemini Chat Web mode on a headless Hetzner VPS using Chrome CDP.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Hetzner VPS (Ubuntu)                         │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  atlas-chrome-cdp.service (systemd)                    │   │
│  │  - Xvfb (virtual display :99)                          │   │
│  │  - Chrome with CDP on port 9222                         │   │
│  │  - Persistent Google session                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          │                                      │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  atlas-solver.service                                   │   │
│  │  - Connects to CDP instantly (< 1s)                     │   │
│  │  - No Chrome launch overhead                            │   │
│  │  - Uses saved Google session                            │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Why This Matters

Without a persistent Chrome CDP service:

| Phase | Without CDP Service | With CDP Service |
|-------|---------------------|------------------|
| CDP connect | 45s timeout | < 1s |
| Chrome launch | ~15s | 0s (already running) |
| Google login | Manual each time | Saved in user_data_dir |
| Total per request | **60s+ overhead** | **~0s overhead** |

For episodes with 6+ chunks, this saves **6+ minutes** of wasted time.

## Installation

### 1. Install Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Chrome and Xvfb
sudo apt install -y wget gnupg xvfb
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update
sudo apt install -y google-chrome-stable

# Optional: Install x11vnc for remote access during setup
sudo apt install -y x11vnc
```

### 2. Create User Data Directory

```bash
# Create directory for Chrome user data
sudo mkdir -p /srv/atlas/OCR_annotation_Atlas/.state/gemini_chat_user_data
sudo chown -R atlas:atlas /srv/atlas/OCR_annotation_Atlas/.state/
```

### 3. Install Systemd Service

```bash
# Copy the service file
sudo cp deploy/atlas-chrome-cdp.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload
```

### 4. One-Time Google Login

Before starting the service, you must login to Google manually:

```bash
# Run the setup script
cd /srv/atlas/OCR_annotation_Atlas
bash deploy/setup_gemini_login_hetzner.sh
```

This script will:
1. Start Xvfb on display :99
2. Start x11vnc on port 5900
3. Launch Chrome for manual Google login
4. Save the session to user_data_dir

**To connect via VNC:**

From your local machine:
```bash
# SSH tunnel to VNC port
ssh -L 5900:127.0.0.1:5900 atlas@<server-ip>

# Then connect with any VNC client to:
# vnc://localhost:5900
```

In the Chrome window:
1. Login to your Google account
2. Accept any prompts (cookies, etc.)
3. Verify you see the Gemini chat interface
4. Press Enter in the terminal to save the session

### 5. Start the CDP Service

```bash
# Enable on boot
sudo systemctl enable atlas-chrome-cdp.service

# Start the service
sudo systemctl start atlas-chrome-cdp.service

# Check status
sudo systemctl status atlas-chrome-cdp.service
```

### 6. Verify CDP is Working

```bash
# Check if Chrome is listening on CDP port
curl -s http://127.0.0.1:9222/json/version

# Expected output:
# {"Browser":"Chrome/...","Protocol-Version":"1.3",...}
```

### 7. Start/Restart the Solver

```bash
# If atlas-solver is a separate service
sudo systemctl restart atlas-solver.service

# Or run manually
cd /srv/atlas/OCR_annotation_Atlas
python atlas_web_auto_solver.py --config configs/production_hetzner.yaml
```

## Configuration

Key settings in `configs/production_hetzner.yaml`:

```yaml
gemini:
  auth_mode: chat_web
  chat_web_connect_over_cdp_url: http://127.0.0.1:9222
  chat_web_cdp_connect_timeout_ms: 8000  # Fast-fail if Chrome not up
  chat_web_headless: false               # Must be false for Xvfb
  chat_web_user_data_dir: .state/gemini_chat_user_data
  chat_web_launch_args:
    - --no-sandbox
    - --disable-dev-shm-usage
    - --disable-gpu
    - --disable-software-rasterizer
```

## Monitoring

### Check Chrome Health

```bash
# Service status
sudo systemctl status atlas-chrome-cdp.service

# Chrome process
ps aux | grep chrome

# CDP endpoint
curl -s http://127.0.0.1:9222/json/version

# View logs
sudo journalctl -u atlas-chrome-cdp.service -f
```

### Common Issues

#### CDP Connection Failed

**Symptom:** `chat_web_cdp_fallback=...` in logs

**Solution:**
```bash
# Check if service is running
sudo systemctl status atlas-chrome-cdp.service

# Restart if needed
sudo systemctl restart atlas-chrome-cdp.service
```

#### Google Session Expired

**Symptom:** "Gemini chat input not visible" or redirect to login page

**Solution:**
```bash
# Re-run the login setup script
bash deploy/setup_gemini_login_hetzner.sh
```

#### Chrome Crashes

**Symptom:** Service keeps restarting

**Solution:**
```bash
# Check memory
free -h

# Chrome may need more RAM, increase in service file:
# MemoryMax=4G

# Check for zombie processes
pkill -9 chrome
sudo systemctl restart atlas-chrome-cdp.service
```

## Security Notes

1. **CDP is bound to 127.0.0.1** - not exposed to the internet
2. **User data directory** contains Google session - protect it
3. **Run as non-root user** (`atlas`) for security
4. **No VNC after setup** - x11vnc is only needed during login

## Troubleshooting

### Enable Debug Logging

Check solver logs for:

```
[chat_web_diag] cdp_connect_start url=http://127.0.0.1:9222 timeout=8000ms
[chat_web_diag] cdp_connect_ok: 0.8s elapsed        # ✅ Success
[chat_web_diag] browser_ready launch_mode=connect_over_cdp
```

vs:

```
[chat_web_diag] cdp_connect_failed: ...              # ❌ CDP failed
[chat_web_diag] browser_ready launch_mode=persistent # Fallback mode
```

### Manual Testing

```bash
# Test Chrome CDP manually
curl http://127.0.0.1:9222/json/list

# Should return list of open tabs including Gemini
```

## Related Files

- `deploy/atlas-chrome-cdp.service` - Systemd service definition
- `deploy/setup_gemini_login_hetzner.sh` - One-time login helper
- `configs/production_hetzner.yaml` - Production configuration
- `atlas_triplet_compare.py` - Chat web implementation with diagnostics