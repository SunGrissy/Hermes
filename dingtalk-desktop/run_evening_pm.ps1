# run_evening_pm.ps1
# 管线晚报（pm-evening）：对比早间基线，推一条到 version_digest_pmo_evening 配置的 webhook。
#
# 手动试发：cd dingtalk-desktop
#   py version_digest.py --mode pm-evening --dry-run
#   py version_digest.py --mode pm-evening

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("evening_pm_{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    Write-Host $line
    [System.IO.File]::AppendAllText($LogFile, "$line`n", [System.Text.Encoding]::UTF8)
}

Write-Log "===== Pipeline evening (pm-evening) start ====="
Write-Log "[E-PM] version_digest.py --mode pm-evening"
try {
    & py version_digest.py --mode pm-evening 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) { Write-Log "[E-PM] WARN exit code $LASTEXITCODE" }
} catch {
    Write-Log "[E-PM] ERROR $($_.Exception.Message)"
}
Write-Log "===== Pipeline evening end ====="
