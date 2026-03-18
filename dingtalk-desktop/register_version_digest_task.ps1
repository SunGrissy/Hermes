# register_version_digest_task.ps1
# 以管理员权限运行此脚本即可注册定时任务
# 右键 -> 用 PowerShell 运行（或在管理员 PowerShell 中执行）

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$DigestScript = Join-Path $ScriptDir "run_version_digest.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$DigestScript`""

$trigger = New-ScheduledTaskTrigger -Daily -At "15:00"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "VersionDigest" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "每日15:00推送PmSystem版本状态到助理通知群" `
    -RunLevel Highest `
    -Force

Write-Host ""
Write-Host "注册完成！任务名称: VersionDigest，每日 15:00 运行" -ForegroundColor Green
Write-Host "脚本路径: $DigestScript" -ForegroundColor Cyan
Write-Host ""
Write-Host "立即测试: Start-ScheduledTask -TaskName VersionDigest" -ForegroundColor Yellow
Read-Host "按回车关闭"
