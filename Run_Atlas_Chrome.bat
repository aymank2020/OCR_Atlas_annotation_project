@echo off
echo ============================================================
echo  Atlas Stealth Scraper — Chrome Debug Mode Launcher
echo ============================================================
echo.
echo Closing all existing Chrome instances...
taskkill /F /IM chrome.exe /T 2>nul
timeout /t 3 /nobreak >nul

echo Starting Chrome with Remote Debugging Port 9222...
echo (This is required for the stealth scraper to connect)
echo.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\ChromeDebug"

echo.
echo ============================================================
echo  Chrome is starting in Debug Mode!
echo.
echo  NEXT STEPS:
echo  1. In Chrome, go to discord.com/app
echo  2. Log in as danatimmer2050 (if not already logged in)
echo  3. Open the Atlas Label Community server
echo  4. Open a NEW terminal and run:
echo     python atlas_stealth_scraper.py
echo ============================================================
echo.
pause