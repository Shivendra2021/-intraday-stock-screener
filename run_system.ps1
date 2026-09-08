# Stock Analyser V2 - one-command launcher
# Run with:
#   .\run_system.ps1

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project venv Python not found: $pythonPath"
}

function Test-ProjectPythonProcess {
    param([string]$Pattern)
    $escapedRoot = [regex]::Escape($projectRoot)
    return @(Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -eq "python.exe" -and
            $_.CommandLine -match $escapedRoot -and
            $_.CommandLine -match $Pattern
        })
}

New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot "logs") | Out-Null

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Stock Analyser V2 - One Command System" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan

$bot = Test-ProjectPythonProcess "main\.py"
if ($bot.Count -eq 0) {
    Write-Host "Starting bot scheduler..." -ForegroundColor Green
    Start-Process powershell.exe -WindowStyle Normal -WorkingDirectory $projectRoot -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command",
        "& `"$pythonPath`" main.py 2>&1 | Tee-Object -FilePath `"$(Join-Path $projectRoot 'logs\scheduler.log')`" -Append"
    )
} else {
    Write-Host "Bot already running. PIDs=$($bot.ProcessId -join ',')" -ForegroundColor DarkYellow
}

$dashboard = Test-ProjectPythonProcess "dashboard[\\/]app\.py"
if ($dashboard.Count -eq 0) {
    Write-Host "Starting dashboard..." -ForegroundColor Green
    Start-Process powershell.exe -WindowStyle Normal -WorkingDirectory $projectRoot -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $projectRoot "run_dashboard.ps1")
    )
} else {
    Write-Host "Dashboard already running. PIDs=$($dashboard.ProcessId -join ',')" -ForegroundColor DarkYellow
}

Write-Host "Running time-aware catch-up pass..." -ForegroundColor Green
& $pythonPath tools\system_supervisor.py --quick

Write-Host "Opening dashboard..." -ForegroundColor Green
Start-Process chrome.exe "http://127.0.0.1:5001/?v=fresh-dashboard"

Write-Host ""
Write-Host "System command complete. Bot/dashboard will continue running." -ForegroundColor Cyan
Write-Host "Dashboard: http://127.0.0.1:5001/?v=fresh-dashboard" -ForegroundColor Cyan
