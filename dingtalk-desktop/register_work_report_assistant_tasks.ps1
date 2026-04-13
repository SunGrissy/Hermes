# register_work_report_assistant_tasks.ps1
# 以当前用户注册 4 个计划任务（无需管理员）：工作日早报 / 周日周报素材 / 周一体验提炼 / 周五 AI 与体验
# 早报：每日 09:00 触发，是否推送由脚本按 PM「假日与调休」判定（非法定周一到周五）
# 执行前请在 webhook_config.json 中配置 work_report_assistant 的机器人 URL（或与 default 共用）

$ScriptDir = $PSScriptRoot
$runner = Join-Path $ScriptDir "run_work_report_assistant.ps1"

if (-not (Test-Path $runner)) {
    Write-Error "Missing $runner"
    exit 1
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 45)

$jobs = @(
    @{
        Name     = "MyAgents_WorkReportAssist_Morning"
        At       = "09:00"
        Trigger  = "Daily"
        Days     = $null
        Scenario = "morning_digest"
        Desc     = "Work report assistant: morning_digest daily 09:00 (PM workday filter in script)"
    },
    @{
        Name     = "MyAgents_WorkReportAssist_WeeklyMaterial"
        At       = "16:00"
        Trigger  = "Weekly"
        Days     = [System.DayOfWeek]::Sunday
        Scenario = "weekly_material"
        Desc     = "Work report assistant: weekly_material Sun 16:00"
    },
    @{
        Name     = "MyAgents_WorkReportAssist_PxInsight"
        At       = "10:30"
        Trigger  = "Weekly"
        Days     = [System.DayOfWeek]::Monday
        Scenario = "weekly_px_insight"
        Desc     = "Work report assistant: weekly_px_insight Mon 10:30"
    },
    @{
        Name     = "MyAgents_WorkReportAssist_AiPx"
        At       = "17:00"
        Trigger  = "Weekly"
        Days     = [System.DayOfWeek]::Friday
        Scenario = "weekly_ai_px_report"
        Desc     = "Work report assistant: weekly_ai_px_report Fri 17:00"
    }
)

foreach ($j in $jobs) {
    $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Scenario $($j.Scenario)"
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument $arg `
        -WorkingDirectory $ScriptDir

    if ($j.Trigger -eq "Daily") {
        $trigger = New-ScheduledTaskTrigger -Daily -At $j.At
    } else {
        $trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $j.Days -At $j.At
    }

    $existing = Get-ScheduledTask -TaskName $j.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $j.Name -Confirm:$false
        Write-Host "removed existing: $($j.Name)"
    }

    Register-ScheduledTask `
        -TaskName $j.Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description $j.Desc `
        -Force | Out-Null

    Write-Host "registered: $($j.Name) -> $($j.Scenario)"
}

Write-Host "Runner: $runner"
Write-Host "Ensure dingtalk-desktop/webhook_config.json has key hr (same bot as resume_notify / HR)."
