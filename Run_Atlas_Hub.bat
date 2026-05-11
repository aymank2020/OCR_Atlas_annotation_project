@echo off
setlocal
cd /d "%~dp0"

echo ===================================================
echo 🏛️ Atlas Command Hub Launcher
echo ===================================================

:: Check if virtual environment exists
if not exist ".venv\Scripts\activate" (
    echo ❌ ERROR: Virtual environment not found at .venv\Scripts\activate
    pause
    exit /b 1
)

:: Activate virtual environment
echo 🔄 Activating Python environment...
call .venv\Scripts\activate

:: Start the hub in the background to keep the terminal clean,
:: but we use streamlit run directly because we want the console output
echo 🚀 Starting Master Dashboard on port 8500...
echo.
echo ⚠️ Leave this window open while using the hub.
echo ⚠️ To stop all services, close this window.
echo.

:: Open the browser immediately
start http://localhost:8500

:: Run the hub blocking
streamlit run atlas_command_hub.py --server.port 8500 --server.headless true

endlocal
pause
