@echo off
chcp 65001 > nul
title Stock Analyser V2 - AI LIVE TERMINAL
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo.
echo  ============================================================
echo    Stock Analyser V2 - AI Live Terminal
echo    Reads dashboard/database state and refreshes continuously
echo    Ctrl+C to stop this terminal view
echo  ============================================================
echo.

.venv\Scripts\python.exe tools\live_terminal.py
exit /b %ERRORLEVEL%
