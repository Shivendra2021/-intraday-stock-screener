# Stop MarketMind Bot task
$taskName = "MarketMind Bot"

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Task STOPPED (but still scheduled)"
} else {
    Write-Host "Task not found"
}

# To remove completely:
# Unregister-ScheduledTask -TaskName $taskName -Confirm:$false