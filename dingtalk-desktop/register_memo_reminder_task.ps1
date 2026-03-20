# register_memo_reminder_task.ps1
# 注册 Windows 计划任务：每日 09:30、14:00、17:30 各执行一次备忘提醒

$taskName = "MemoReminder"
$scriptPath = Join-Path $PSScriptRoot "run_memo_reminder.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -File `"$scriptPath`"" `
    -WorkingDirectory $PSScriptRoot

$trigger1 = New-ScheduledTaskTrigger -Daily -At "09:30"
$trigger2 = New-ScheduledTaskTrigger -Daily -At "14:00"
$trigger3 = New-ScheduledTaskTrigger -Daily -At "17:30"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "removed existing task: $taskName"
}

# 不设 RunLevel Highest，以当前用户注册，无需管理员权限
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger1, $trigger2, $trigger3 `
    -Settings $settings `
    -Description "Memo follow-up to DingTalk: 09:30, 14:00, 17:30" `
    -Force

Write-Host "registered: $taskName (09:30, 14:00, 17:30)"
