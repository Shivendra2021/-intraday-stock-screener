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
Write-Host "  Stock Analyser V2 - One Command System Launcher" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Start Bot Scheduler if not running
$bot = Test-ProjectPythonProcess "main\.py"
if ($bot.Count -eq 0) {
    Write-Host "Starting bot scheduler..." -ForegroundColor Green
    Start-Process powershell.exe -WindowStyle Normal -WorkingDirectory $projectRoot -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $projectRoot "run_scheduler.ps1")
    )
} else {
    Write-Host "Bot already running. PIDs=$($bot.ProcessId -join ',')" -ForegroundColor DarkYellow
}

# 2. Start Dashboard if not running
$dashboard = Test-ProjectPythonProcess "dashboard[\\/]app\.py"
if ($dashboard.Count -eq 0) {
    Write-Host "Starting dashboard..." -ForegroundColor Green
    Start-Process powershell.exe -WindowStyle Normal -WorkingDirectory $projectRoot -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $projectRoot "run_dashboard.ps1")
    )
} else {
    Write-Host "Dashboard already running. PIDs=$($dashboard.ProcessId -join ',')" -ForegroundColor DarkYellow
}

# 3. Start Cloudflare Tunnel for Angel One SmartAPI if enabled and not running
$tunnelProc = Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue
if (-not $tunnelProc) {
    $envFile = Join-Path $projectRoot ".env"
    $angelEnabled = $false
    if (Test-Path -LiteralPath $envFile) {
        $lines = Get-Content -LiteralPath $envFile
        if ($lines -match "ANGEL_ENABLED\s*=\s*True") {
            $angelEnabled = $true
        }
    }
    if ($angelEnabled) {
        Write-Host "Starting Cloudflare Quick Tunnel for Angel One..." -ForegroundColor Green
        Start-Process powershell.exe -WindowStyle Normal -WorkingDirectory $projectRoot -ArgumentList @(
            "-NoExit",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $projectRoot "run_tunnel.ps1")
        )
    }
} else {
    Write-Host "Cloudflare tunnel already running. PIDs=$($tunnelProc.Id -join ',')" -ForegroundColor DarkYellow
}

# 4. Run time-aware catch-up pass
Write-Host "Running time-aware catch-up pass..." -ForegroundColor Green
& $pythonPath tools\system_supervisor.py --quick

# 5. Open Dashboard in default browser
Write-Host "Opening dashboard..." -ForegroundColor Green
try {
    Start-Process chrome.exe "http://127.0.0.1:5001/?v=fresh-dashboard"
} catch {
    Start-Process "http://127.0.0.1:5001/?v=fresh-dashboard"
}

Write-Host ""
Write-Host "System command complete. All services are running." -ForegroundColor Cyan
Write-Host "Dashboard: http://127.0.0.1:5001/?v=fresh-dashboard" -ForegroundColor Cyan
