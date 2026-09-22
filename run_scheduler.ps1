# MarketMind Pro — Main Scheduler Loop (PowerShell)
# Run with: .\run_scheduler.ps1

$Host.UI.RawUI.WindowTitle = "MarketMind Pro - MAIN SCHEDULER"
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "    MarketMind Pro - Bot Scheduler" -ForegroundColor Yellow
Write-Host "    Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""

New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "logs") | Out-Null
$logFile = Join-Path $PSScriptRoot "logs\scheduler.log"

while ($true) {
    Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] Starting main.py..." -ForegroundColor Green
    & ".\.venv\Scripts\python.exe" main.py 2>&1 | Tee-Object -FilePath $logFile -Append
    $code = $LASTEXITCODE
    Write-Host ""
    Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] Scheduler exited (code $code). Restarting in 5 seconds..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}
