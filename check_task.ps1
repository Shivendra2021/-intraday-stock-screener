# Check MarketMind Bot task status
$taskName = "MarketMind Bot"

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "=== MarketMind Bot Task Status ==="
    Write-Host "Task Name: $($task.TaskName)"
    Write-Host "State: $($task.State)"
    Write-Host "Last Run: $($task.LastRunTime)"
    Write-Host ""
    Write-Host "To stop: powershell -File stop_task.ps1"
    Write-Host "To remove: Unregister-ScheduledTask -TaskName 'MarketMind Bot' -Confirm:`$false"
} else {
    Write-Host "Task not found - run setup_task.ps1 first"
}