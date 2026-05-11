@echo off
chcp 65001 > nul
title MarketMind Pro - DASHBOARD :5001
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo.
echo  ============================================================
echo    MarketMind Pro - Dashboard
echo    Browser: http://localhost:5001
echo    Ctrl+C to stop
echo  ============================================================
echo.

:loop
echo [%TIME%] Starting dashboard...
.venv\Scripts\python.exe dashboard\app.py
echo.
echo [%TIME%] Dashboard stopped. Restarting in 5s...
ping -n 6 127.0.0.1 > nul
goto loop
