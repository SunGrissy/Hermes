# run_evening_pmo.ps1
# 制作人向 PMO晚报：对比今日早间 producer 基线与当前 producer 正文，推一条到 version_digest_pmo。
# 依赖：早间已跑过 snapshot 并写入 morning_producer（见 version_digest.py）；否则回退基线并打日志。
#
# 手动试发：cd dingtalk-desktop
#   py version_digest.py --mode pmo-evening --dry-run
#   py version_digest.py --mode pmo-evening

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("evening_pmo_{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    Write-Host $line
    [System.IO.File]::AppendAllText($LogFile, "$line`n", [System.Text.Encoding]::UTF8)
}

Write-Log "===== PMO evening start ====="
Write-Log "[E-PMO] version_digest.py --mode pmo-evening"
try {
    & py version_digest.py --mode pmo-evening 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) { Write-Log "[E-PMO] WARN exit code $LASTEXITCODE" }
} catch {
    Write-Log "[E-PMO] ERROR $($_.Exception.Message)"
}
Write-Log "===== PMO evening end ====="
