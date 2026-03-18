# run_version_digest.ps1
# 版本状态定时推送脚本（每日 15:00 运行）
# 从 PmSystem 拉取活跃版本状态，通过 webhook 推送到助理通知群

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$LogFile = Join-Path $ScriptDir "logs\version_digest_$(Get-Date -Format 'yyyyMMdd').log"
$LogDir  = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'HH:mm:ss') $Msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log "[version] ===== 版本状态推送启动 ====="

# 运行版本摘要（直接读 pm_data.json，无需 daemon 或 PmSystem 运行中）
$output = py version_digest.py 2>&1
$output | ForEach-Object { Write-Log $_ }

Write-Log "[version] ===== 完成 ====="
