$taskName   = "TorontoParksLayer"
$projectDir = $PSScriptRoot
$logFile    = "$projectDir\logs\scheduler.log"

if (-not (Test-Path "$projectDir\logs")) {
    New-Item -ItemType Directory -Path "$projectDir\logs" | Out-Null
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c cd /d `"$projectDir`" && python run.py update >> `"$logFile`" 2>&1"

# Weekly is enough: the City refreshes the Green Spaces dataset monthly.
# 15:00 keeps it clear of the sibling address tasks (noon and 14:00).
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "15:00"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force

Write-Host "Scheduled '$taskName' to run weekly on Monday at 15:00."
Write-Host "Log: $logFile"
