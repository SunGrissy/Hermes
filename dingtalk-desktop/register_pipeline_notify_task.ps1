# register_pipeline_notify_task.ps1
# 以当前用户注册计划任务（无需管理员）：周一至周六 9:15、19:45 各一次（周日不跑），跑 run_pipeline_notify_scheduled.ps1
# 若需「以最高权限运行」，请改用 register_pipeline_notify_schtasks.ps1（管理员执行）

$taskMorning = "MyAgents_PipelineNotify_0915"
# 任务名保留 _1615 历史标识；触发时间已为 19:45
$taskAfternoon = "MyAgents_PipelineNotify_1615"
$scriptPath = Join-Path $PSScriptRoot "run_pipeline_notify_scheduled.ps1"

if (-not (Test-Path $scriptPath)) {
    Write-Error "Missing $scriptPath"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`"" `
    -WorkingDirectory $PSScriptRoot

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

$weekdays = [System.DayOfWeek]::Monday, [System.DayOfWeek]::Tuesday, [System.DayOfWeek]::Wednesday, `
    [System.DayOfWeek]::Thursday, [System.DayOfWeek]::Friday, [System.DayOfWeek]::Saturday

foreach ($pair in @(
        @{ Name = $taskMorning; At = "09:15"; Desc = "管线提醒 webhook --auto-scheduled (morning, Mon-Sat)" },
        @{ Name = $taskAfternoon; At = "19:45"; Desc = "管线提醒 webhook --auto-scheduled (evening, Mon-Sat)" }
    )) {
    $trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $weekdays -At $pair.At
    $existing = Get-ScheduledTask -TaskName $pair.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $pair.Name -Confirm:$false
        Write-Host "removed existing: $($pair.Name)"
    }
    Register-ScheduledTask `
        -TaskName $pair.Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description $pair.Desc `
        -Force
    $slot = if ($pair.At -eq "09:15") { "Mon-Sat morning" } else { "Mon-Sat evening" }
    Write-Host "registered: $($pair.Name) $slot $($pair.At)"
}

Write-Host "Runner: $scriptPath"
