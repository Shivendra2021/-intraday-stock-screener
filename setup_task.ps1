# Create/update the Windows Task Scheduler entry for MarketMind Bot.
# Run from this project folder in PowerShell.

$ErrorActionPreference = "Stop"

$taskName = "MarketMind Bot"
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$launcherPath = Join-Path $projectRoot "tools\start_main_once.ps1"
$time = "07:30"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project venv Python not found: $pythonPath. Run setup_and_verify.py before creating the task."
}
if (-not (Test-Path -LiteralPath $launcherPath)) {
    throw "Scheduled launcher not found: $launcherPath"
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
    -RunOnlyIfNetworkAvailable `
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
    -Description "MarketMind Pro Bot - daily unattended startup using project venv" | Out-Null

Write-Host "Task created successfully."
Write-Host "Task name: $taskName"
Write-Host "Schedule: daily at $time"
Write-Host "Command: powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$launcherPath`""
Write-Host "Working directory: $projectRoot"
Write-Host "Log file: $(Join-Path $projectRoot 'logs\bot.log')"
