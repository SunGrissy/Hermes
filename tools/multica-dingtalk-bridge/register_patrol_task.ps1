# register_patrol_task.ps1
# 注册「Multica 定时巡检」Windows 计划任务
# 用法：在 tools\multica-dingtalk-bridge 目录下以普通用户权限执行即可（无需管理员）
# 设置 PATROL_AUTO_DISPATCH=1 后会自动派单给开发 Agent；默认只上报不派单

param(
    [string]$TaskName = "MulticaPatrolScheduler",
    [int]$IntervalMinutes = 30,
    [switch]$AutoDispatch,
    [switch]$Unregister
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunnerScript = Join-Path $ScriptDir "run_patrol.ps1"

# 先生成 run_patrol.ps1（每次运行的实际调用脚本）
$AutoDispatchVal = if ($AutoDispatch) { "1" } else { "0" }
$RunnerContent = @"
# 由 register_patrol_task.ps1 生成，勿手动编辑
`$env:PATROL_AUTO_DISPATCH = "$AutoDispatchVal"
`$env:PATROL_INTERVAL_MINUTES = "0"

# 加载 .env
`$envFile = Join-Path "$ScriptDir" ".env"
if (Test-Path `$envFile) {
    Get-Content `$envFile | ForEach-Object {
        if (`$_ -match '^\s*([^#][^=]+)=(.*)$') {
            `$key = `$Matches[1].Trim()
            `$val = `$Matches[2].Trim()
            if (-not [System.Environment]::GetEnvironmentVariable(`$key)) {
                [System.Environment]::SetEnvironmentVariable(`$key, `$val, "Process")
            }
        }
    }
}

Push-Location "$ScriptDir"
py patrol_scheduler.py >> "$ScriptDir\patrol_scheduler.log" 2>&1
Pop-Location
"@
$RunnerContent | Out-File -FilePath $RunnerScript -Encoding UTF8 -Force

if ($Unregister) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "计划任务 '$TaskName' 已删除。"
    } else {
        Write-Host "计划任务 '$TaskName' 不存在，无需删除。"
    }
    exit 0
}

# 删除旧任务（幂等）
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -NoProfile -ExecutionPolicy Bypass -File `"$RunnerScript`"" `
    -WorkingDirectory $ScriptDir

# 从现在起每隔 N 分钟重复一次（工作时间 8:00-22:00）
$StartTime = (Get-Date).Date.AddHours(8)
$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At $StartTime `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Hours 14)  # 8:00 - 22:00

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes ([math]::Max(15, $IntervalMinutes)))

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Multica 工单定时巡检，每 $IntervalMinutes 分钟扫描一次，auto_dispatch=$AutoDispatchVal" `
    -Force | Out-Null

Write-Host ""
Write-Host "计划任务 '$TaskName' 注册完成。"
Write-Host "  间隔: ${IntervalMinutes} 分钟"
Write-Host "  自动派单: $AutoDispatchVal (1=开启，0=只报告)"
Write-Host "  日志: $ScriptDir\patrol_scheduler.log"
Write-Host ""
Write-Host "验证: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "删除: .\register_patrol_task.ps1 -Unregister"
