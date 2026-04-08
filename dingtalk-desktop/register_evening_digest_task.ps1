# register_evening_digest_task.ps1
# 以当前用户注册计划任务（无需管理员）：每日 18:00 执行 run_evening_digest_both.ps1
# （依次：PMO晚报 pmo-evening -> 管线晚报 pm-evening）
#
# 用法：在 PowerShell 中 cd 到 dingtalk-desktop 后执行：
#   .\register_evening_digest_task.ps1
#
# 测试：Start-ScheduledTask -TaskName MyAgents_EveningDigest_1800
# 删除：Unregister-ScheduledTask -TaskName MyAgents_EveningDigest_1800 -Confirm:$false

$ErrorActionPreference = "Stop"

$TaskName = "MyAgents_EveningDigest_1800"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Runner = Join-Path $ScriptDir "run_evening_digest_both.ps1"

if (-not (Test-Path $Runner)) {
    Write-Error "Missing runner: $Runner"
    exit 1
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task: $TaskName"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`"" `
    -WorkingDirectory $ScriptDir

$trigger = New-ScheduledTaskTrigger -Daily -At "18:00"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Daily 18:00: PMO evening (pmo-evening) then pipeline evening (pm-evening)" `
    -Force

Write-Host ""
Write-Host "OK: Task registered - $TaskName daily at 18:00" -ForegroundColor Green
Write-Host "Runner: $Runner" -ForegroundColor Cyan
Write-Host "Log:    logs\evening_digest_YYYYMMDD.log" -ForegroundColor Cyan
Write-Host "Test:   Start-ScheduledTask -TaskName $TaskName" -ForegroundColor Yellow
