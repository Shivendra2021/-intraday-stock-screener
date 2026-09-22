@echo off
chcp 65001 > nul
title Stock Analyser V2 - DASHBOARD :5001
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo.
echo  ============================================================
echo    Stock Analyser V2 - Dashboard
echo    Browser: http://localhost:5001
echo    Ctrl+C to stop
echo  ============================================================
echo.

for /f %%i in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'dashboard\\app.py' }; if($p){ '1' } else { '0' }"') do set "DASHBOARD_RUNNING=%%i"

if "%DASHBOARD_RUNNING%"=="1" (
    echo [%TIME%] Dashboard is already running. Open http://localhost:5001
    exit /b 0
)

echo [%TIME%] Starting dashboard...
.venv\Scripts\python.exe dashboard\app.py
echo.
echo [%TIME%] Dashboard stopped.
exit /b %ERRORLEVEL%
