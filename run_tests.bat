@echo off
echo ========================================
echo  Atlas Capture — Full Test Suite
echo ========================================
echo.

python -m pytest tests/ -v --tb=short

echo.
echo ========================================
echo  Test run complete.
echo ========================================
pause