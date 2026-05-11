@echo off
setlocal
cd /d "%~dp0"

:: Check if venv exists and activate it
if exist "venv\Scripts\activate.bat" (
    echo [System] Activating venv...
    call venv\Scripts\activate.bat
) else if exist "env\Scripts\activate.bat" (
    echo [System] Activating env...
    call env\Scripts\activate.bat
) else (
    echo [Warning] No virtual environment found. Running with global python.
)

echo [System] Starting Atlas Stealth Daemon...
python atlas_stealth_daemon.py
pause
