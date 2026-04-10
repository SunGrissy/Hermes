# run_daily_version.ps1
# 工作日定时：版本状态摘要（A1）+ 可选专项远端推送（A2）
# 建议在「日报 digest」计划任务之前或并行单独排程执行。

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
param(
    [switch]$EveningChange
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("version_daily_{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    Write-Host $line
    [System.IO.File]::AppendAllText($LogFile, "$line`n", [System.Text.Encoding]::UTF8)
}

Write-Log "===== version daily start ====="

if ($EveningChange) {
    Write-Log "[E1] version_digest.py --mode change"
    try {
        & py version_digest.py --mode change 2>&1 | ForEach-Object { Write-Log $_ }
        if ($LASTEXITCODE -ne 0) { Write-Log "[E1] WARN exit code $LASTEXITCODE" }
    } catch {
        Write-Log "[E1] ERROR $($_.Exception.Message)"
    }
    Write-Log "===== version daily end ====="
    exit 0
}

Write-Log "[A1] version_digest.py --mode snapshot"
try {
    & py version_digest.py --mode snapshot 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) { Write-Log "[A1] WARN exit code $LASTEXITCODE" }
} catch {
    Write-Log "[A1] ERROR $($_.Exception.Message)"
}

Start-Sleep -Seconds 10

Write-Log "[A2] _push_versions_webhook_at_dm.py（digest_config.pm_system_url + 各版本 progressNotifyWebhooks；默认含五一版/五月中/0401）"
try {
    & py _push_versions_webhook_at_dm.py 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) { Write-Log "[A2] WARN exit code $LASTEXITCODE" }
} catch {
    Write-Log "[A2] ERROR $($_.Exception.Message)"
}

Write-Log "===== version daily end ====="
