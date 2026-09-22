@echo off
chcp 65001 > nul
title MarketMind Pro - MAIN SCHEDULER
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo.
echo  ============================================================
echo    MarketMind Pro - Bot Scheduler
echo    Press Ctrl+C to stop
echo  ============================================================
echo.

if not exist "logs" mkdir "logs"

:loop
echo [%TIME%] Starting main.py...
.venv\Scripts\python.exe main.py
echo.
echo [%TIME%] Scheduler exited (code %ERRORLEVEL%). Restarting in 5 seconds...
timeout /t 5 /nobreak > nul
goto loop
