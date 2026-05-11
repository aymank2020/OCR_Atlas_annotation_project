# 🏛️ Atlas Localhost Startup Guide

Use this guide to start the Atlas services correctly on your local machine. All services are configured to run on specific ports to avoid conflicts.

## 🚀 Recommended: One-Click Startup
The easiest way to start is using the provided batch files:

1.  **[Run_Atlas_Hub.bat](file:///e:/OCR_annotation_Atlas/Run_Atlas_Hub.bat)**: Starts the Master Command Hub (Port 8500).
2.  **[Run_Atlas_Scribe.bat](file:///e:/OCR_annotation_Atlas/Run_Atlas_Scribe.bat)**: Starts the Scribe Transcription Dashboard (Port 8501).

---

## 🛠️ Manual Startup Commands
If you prefer running commands manually in your terminal, use these (Ensure your `.venv` is active):

### 1. Atlas Command Hub (Master Control)
**Port:** `8500`
```bash
streamlit run atlas_command_hub.py --server.port 8500
```
*   **Purpose:** The central "entry point" to manage all other services.

### 2. Atlas Scribe (Audio Intelligence)
**Port:** `8501`
```bash
streamlit run atlas_scribe_dashboard.py --server.port 8501
```
*   **Purpose:** Real-time transcription, VAD analysis, and Gemini AI session summaries.

### 3. Atlas Control Center (Operations)
**Port:** `8502`
```bash
streamlit run atlas_control_center.py --server.port 8502
```
*   **Purpose:** VPS management, Discord 24/7 question dispatcher, and knowledge building.

---

## 🔍 Troubleshooting "Broken" Services

### 🚫 Issue: "Port already in use"
**Fix:** Close the terminal window that is running the previous instance. If it's "stuck" in the background, run:
```powershell
# Kill anything on port 8500-8503
Get-Process | Where-Object { $_.MainWindowTitle -like "*Streamlit*" } | Stop-Process -Force
```

### 🎙️ Issue: Scribe stops or crashes on Start
**Fix:** 
1.  Check **[atlas_scribe_config.yaml](file:///e:/OCR_annotation_Atlas/atlas_scribe_config.yaml)**.
2.  Ensure `microphone_device` and `loopback_device` names match your Windows Sound settings exactly.
3.  I have added an **Automatic Fallback** — if a device is missing, Scribe will now automatically switch to your **Default** system device instead of crashing.

### 🌐 Issue: Control Center shows "VPS Offline"
**Fix:**
1.  Ensure you are connected to the internet.
2.  Check your **[.env](file:///e:/OCR_annotation_Atlas/.env)** file for `SERVER_IPV4`.
3.  If the IP has changed, update it in the `.env` and click **"Rerun Dashboard"** in the sidebar.

---

## 📋 View Logs
I have updated the **Command Hub** to save logs for every service. If something fails to start, check the logs here:
-   **Scribe Logs:** `e:/OCR_annotation_Atlas/logs/scribe.log`
-   **Control Center Logs:** `e:/OCR_annotation_Atlas/logs/control_center.log`
