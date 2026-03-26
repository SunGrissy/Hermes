# 注册 Windows 计划任务：周一至周六 9:15、19:45 执行管线提醒推送（周日不跑）。
# 需管理员 PowerShell 执行一次：右键「以管理员身份运行」或在提升会话中：
#   Set-ExecutionPolicy -Scope Process Bypass; .\register_pipeline_notify_schtasks.ps1

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Runner = Join-Path $ScriptDir "run_pipeline_notify_scheduled.ps1"
if (-not (Test-Path $Runner)) {
    Write-Error "Missing $Runner"
    exit 1
}

$TaskNameMorning = "MyAgents_PipelineNotify_0915"
$TaskNameAfternoon = "MyAgents_PipelineNotify_1945"
$Tr = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Runner`""

schtasks /Delete /TN "MyAgents_PipelineNotify_1615" /F 2>$null
schtasks /Create /F /TN $TaskNameMorning /SC WEEKLY /D MON,TUE,WED,THU,FRI,SAT /ST 09:15 /TR $Tr /RL HIGHEST 2>&1
schtasks /Create /F /TN $TaskNameAfternoon /SC WEEKLY /D MON,TUE,WED,THU,FRI,SAT /ST 19:45 /TR $Tr /RL HIGHEST 2>&1

Write-Host "Done. Tasks: $TaskNameMorning , $TaskNameAfternoon"
Write-Host "Runner: $Runner"
