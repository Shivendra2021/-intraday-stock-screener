@echo off
chcp 65001 > nul
title MarketMind Pro - Cloudflare Tunnel (Angel One Redirect)
cd /d "%~dp0"

echo.
echo   ============================================================
echo     MarketMind Pro - Cloudflare Quick Tunnel
echo     Target: http://localhost:5001
echo   ============================================================
echo.

if exist "tools\cloudflared.exe" (
    tools\cloudflared.exe tunnel --url http://localhost:5001
) else (
    cloudflared tunnel --url http://localhost:5001
)
pause
