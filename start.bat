@echo off
title Kiro Agent Proxy - Dashboard
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║       Kiro Agent Proxy Dashboard         ║
echo  ║  Starting on http://localhost:3128 ...    ║
echo  ╚══════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: Check Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

:: Install dependencies if needed
echo [*] Checking dependencies...
pip install -r requirements.txt -q
echo [OK] Dependencies ready.
echo.

:: Launch the dashboard
echo [*] Starting dashboard server...
echo     Open http://localhost:3128 in your browser.
echo     Press Ctrl+C to stop.
echo.
:: Wait 2 seconds and open the browser in the background
start /b "" cmd /c "timeout /t 2 >nul && start http://localhost:3128/"
python auth_capture_v2.py

pause
