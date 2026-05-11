# MarketMind Pro — Dashboard Loop (PowerShell)
# Run with: .\run_dashboard.ps1

$Host.UI.RawUI.WindowTitle = "MarketMind Pro - DASHBOARD :5001"
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "    MarketMind Pro - Dashboard" -ForegroundColor Yellow
Write-Host "    Open browser: http://localhost:5001" -ForegroundColor Green
Write-Host "    Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""

while ($true) {
    Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] Starting dashboard..." -ForegroundColor Green
    & ".\.venv\Scripts\python.exe" dashboard\app.py
    $code = $LASTEXITCODE
    Write-Host ""
    Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] Dashboard exited (code $code). Restarting in 5 seconds..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}
