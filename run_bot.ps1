# MarketMind Pro — Bot Loop (PowerShell)
# Run with: .\run_bot.ps1

$Host.UI.RawUI.WindowTitle = "MarketMind Pro - BOT"
Set-Location -LiteralPath $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$mainPath = Join-Path $PSScriptRoot "main.py"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project venv Python not found: $pythonPath"
}

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "    MarketMind Pro - Stock Screener Bot" -ForegroundColor Yellow
Write-Host "    Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] Starting bot..." -ForegroundColor Green
& $pythonPath $mainPath
$code = $LASTEXITCODE
Write-Host ""
Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] Bot exited (code $code)." -ForegroundColor Yellow
exit $code
