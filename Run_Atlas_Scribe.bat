@echo off
title Atlas Scribe — Real-Time Audio Intelligence
color 0B

cd /d "%~dp0"

echo ╔════════════════════════════════════════════════════════╗
echo ║          🎙️  Atlas Scribe — Audio Intelligence        ║
echo ║          Dashboard: http://localhost:8501/             ║
echo ╚════════════════════════════════════════════════════════╝
echo.

REM ── Activate venv ─────────────────────────────────────────
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo ❌ ERROR: .venv not found! Run: python -m venv .venv
    pause
    exit /b 1
)

REM ── Auto-restart loop ─────────────────────────────────────
:restart
echo [%date% %time%] Starting Streamlit...
echo.

.venv\Scripts\streamlit.exe run atlas_scribe_dashboard.py ^
    --server.port 8501 ^
    --server.headless true ^
    --server.runOnSave false ^
    --server.fileWatcherType none ^
    --browser.gatherUsageStats false ^
    --theme.base dark

echo.
echo [%date% %time%] ⚠️ Scribe stopped. Restarting in 5 seconds...
echo     Press Ctrl+C now to stop permanently.
timeout /t 5 /nobreak >nul
goto restart
