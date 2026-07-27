$taskName   = "kk-TorontoParksLayer"
$projectDir = $PSScriptRoot
$logFile    = "$projectDir\logs\scheduler.log"

if (-not (Test-Path "$projectDir\logs")) {
    New-Item -ItemType Directory -Path "$projectDir\logs" | Out-Null
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c cd /d `"$projectDir`" && python run.py update >> `"$logFile`" 2>&1"

# Weekly is enough: the City refreshes the Green Spaces dataset monthly. The
# gap page is what actually moves week to week -- it diffs against live OSM.
# 16:30 clears the daily address task's worst case (14:00 start, 2h limit), so
# the two never drive tippecanoe in the same WSL instance at once.
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "16:30"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force

Write-Host "Scheduled '$taskName' to run weekly on Monday at 16:30."
Write-Host "Log: $logFile"
