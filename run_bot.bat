@echo off
setlocal

cd /d "%~dp0"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "LOG_DIR=%~dp0logs"
set "SCHEDULER_LOG=%LOG_DIR%\scheduler.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%DATE% %TIME%] Scheduler launcher started.>> "%SCHEDULER_LOG%"

if not exist "%PYTHON_EXE%" (
    echo [%DATE% %TIME%] ERROR: Python venv not found at "%PYTHON_EXE%".>> "%SCHEDULER_LOG%"
    echo [%DATE% %TIME%] Run setup_and_verify.py or create .venv before enabling the scheduled task.>> "%SCHEDULER_LOG%"
    exit /b 2
)

echo [%DATE% %TIME%] Running: "%PYTHON_EXE%" main.py>> "%SCHEDULER_LOG%"
"%PYTHON_EXE%" main.py >> "%SCHEDULER_LOG%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"

echo [%DATE% %TIME%] Bot process exited with code %EXIT_CODE%.>> "%SCHEDULER_LOG%"
exit /b %EXIT_CODE%
