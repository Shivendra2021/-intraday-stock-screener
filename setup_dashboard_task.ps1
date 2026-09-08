# Create/update the Windows Task Scheduler entry for Stock Analyser dashboard.

$ErrorActionPreference = "Stop"

$taskName = "Stock Analyser Dashboard"
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$launcherPath = Join-Path $projectRoot "tools\start_dashboard_once.ps1"
$time = "07:31"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project venv Python not found: $pythonPath."
}
if (-not (Test-Path -LiteralPath $launcherPath)) {
    throw "Dashboard launcher not found: $launcherPath"
}

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Task exists, replacing old version..."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$launcherPath`"" `
    -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $time

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Stock Analyser V2 Dashboard - daily unattended startup" | Out-Null

Write-Host "Task created successfully."
Write-Host "Task name: $taskName"
Write-Host "Schedule: daily at $time"
Write-Host "Command: powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$launcherPath`""
Write-Host "Working directory: $projectRoot"
