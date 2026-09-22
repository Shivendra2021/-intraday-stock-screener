# MarketMind Pro — Cloudflare Quick Tunnel for Angel One SmartAPI
# Run with: .\run_tunnel.ps1

$Host.UI.RawUI.WindowTitle = "MarketMind Pro - Cloudflare Tunnel (Angel One Redirect)"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "    MarketMind Pro - Cloudflare Quick Tunnel" -ForegroundColor Yellow
Write-Host "    Target Local URL: http://localhost:5001" -ForegroundColor Green
Write-Host "    Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""

$cloudflared = Join-Path $PSScriptRoot "tools\cloudflared.exe"
if (-not (Test-Path $cloudflared)) {
    $cloudflared = "cloudflared"
}

& $cloudflared tunnel --url http://localhost:5001
