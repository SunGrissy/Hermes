# 定时管线提醒：由计划任务周一至周六 9:15 / 19:45 调用（周日不跑）。
# 筛选规则见 _push_versions_webhook_at_dm.py --auto-scheduled

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("pipeline_scheduled_{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    Write-Host $line
    [System.IO.File]::AppendAllText($LogFile, "$line`n", [System.Text.Encoding]::UTF8)
}

Write-Log "===== pipeline scheduled push start ====="
try {
    & py _push_versions_webhook_at_dm.py --auto-scheduled --report "_pipeline_scheduled_report.md" 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) { Write-Log "WARN exit code $LASTEXITCODE" }
} catch {
    Write-Log "ERROR $($_.Exception.Message)"
}
Write-Log "===== pipeline scheduled push end ====="
