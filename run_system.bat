@echo off
chcp 65001 > nul
title Stock Analyser V2 - System Launcher
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_system.ps1"
exit /b %ERRORLEVEL%
