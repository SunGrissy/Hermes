# register_version_digest_task.ps1
# Register Windows scheduled task "VersionDigest" -> run_version_digest.ps1 daily at 09:40
# Requires: Run as Administrator (or use register_version_digest_task_elevated.cmd)
#
# Chinese help: 以管理员身份运行 PowerShell，cd 到本目录后执行 .\register_version_digest_task.ps1

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$DigestScript = Join-Path $ScriptDir "run_version_digest.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$DigestScript`""

$trigger = New-ScheduledTaskTrigger -Daily -At "09:40"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "VersionDigest" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Daily 09:40 VersionDigest: run_version_digest.ps1 -> version_digest.py" `
    -RunLevel Highest `
    -Force

Write-Host ""
Write-Host "OK: Task VersionDigest registered, daily at 09:40" -ForegroundColor Green
Write-Host "Script: $DigestScript" -ForegroundColor Cyan
Write-Host "Test: Start-ScheduledTask -TaskName VersionDigest" -ForegroundColor Yellow
if (-not $env:VERSION_DIGEST_REGISTER_NONINTERACTIVE) { Read-Host 'Press Enter to close' }
