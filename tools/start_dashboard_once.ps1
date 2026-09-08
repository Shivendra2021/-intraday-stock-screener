$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logPath = Join-Path $projectRoot "logs\dashboard-launcher.log"

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $logPath) | Out-Null

$existing = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -match [regex]::Escape($projectRoot) -and
        $_.CommandLine -match "dashboard[\\/]app\.py"
    }

if ($existing) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') dashboard already running; scheduled launch skipped. PIDs=$($existing.ProcessId -join ',')"
    Add-Content -LiteralPath $logPath -Value $line
    exit 0
}

Set-Location -LiteralPath $projectRoot
& $pythonPath dashboard\app.py
