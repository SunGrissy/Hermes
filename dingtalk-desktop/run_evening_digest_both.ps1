# run_evening_digest_both.ps1
# 傍晚依次推送：1) PMO晚报（pmo-evening，制作人向） 2) 管线晚报（pm-evening，PM 行动向）
# 由计划任务 MyAgents_EveningDigest_1800 每日 18:00 调用（见 register_evening_digest_task.ps1）。
#
# 手动：cd dingtalk-desktop
#   .\run_evening_digest_both.ps1

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("evening_digest_{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    Write-Host $line
    [System.IO.File]::AppendAllText($LogFile, "$line`n", [System.Text.Encoding]::UTF8)
}

Write-Log "========== Evening digest batch start =========="

Write-Log "----- PMO evening (pmo-evening) -----"
try {
    & py version_digest.py --mode pmo-evening 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) { Write-Log "[pmo-evening] WARN exit code $LASTEXITCODE" }
} catch {
    Write-Log "[pmo-evening] ERROR $($_.Exception.Message)"
}

Write-Log "----- Pipeline evening (pm-evening) -----"
try {
    & py version_digest.py --mode pm-evening 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) { Write-Log "[pm-evening] WARN exit code $LASTEXITCODE" }
} catch {
    Write-Log "[pm-evening] ERROR $($_.Exception.Message)"
}

Write-Log "========== Evening digest batch end =========="
