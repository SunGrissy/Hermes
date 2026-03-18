# run_daily_digest.ps1
# 每日日报摘要定时任务脚本
# 自动获取昨日日期，检查 daemon 状态，发送摘要到钉钉

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$LogFile = Join-Path $ScriptDir "logs\digest_$(Get-Date -Format 'yyyyMMdd').log"
$LogDir  = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'HH:mm:ss') $Msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log "[digest] ===== 日报摘要定时任务启动 ====="

# 昨日日期（工作日判断：周一取上周五，其余取昨天）
$today     = Get-Date
$yesterday = $today.AddDays(-1)
if ($today.DayOfWeek -eq [DayOfWeek]::Monday) {
    $yesterday = $today.AddDays(-3)   # 周一 -> 上周五
}
$TargetDate = $yesterday.ToString("yyyy-MM-dd")
Write-Log "[digest] target date = $TargetDate"

# 检查 daemon 是否运行
$daemonOk = $false
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:19200/health" -TimeoutSec 5 -UseBasicParsing
    $json = $resp.Content | ConvertFrom-Json
    if ($json.daemon -eq "running" -and $json.frida_attached -eq $true -and $json.cef_ready -eq $true) {
        $daemonOk = $true
        Write-Log "[daemon] already running (pid=$($json.pid), frida=ok, cef=ok)"
    } else {
        Write-Log "[daemon] running but not ready: frida=$($json.frida_attached) cef=$($json.cef_ready)"
    }
} catch {
    Write-Log "[daemon] not running, starting..."
}

if (-not $daemonOk) {
    Start-Process -FilePath "py" -ArgumentList "daemon.py" -WindowStyle Hidden -WorkingDirectory $ScriptDir
    Write-Log "[daemon] started, waiting 20s for frida attach..."
    Start-Sleep -Seconds 20
    # 再次检查
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:19200/health" -TimeoutSec 5 -UseBasicParsing
        $json = $resp.Content | ConvertFrom-Json
        if ($json.frida_attached -eq $true -and $json.cef_ready -eq $true) {
            Write-Log "[daemon] ready (pid=$($json.pid))"
        } else {
            Write-Log "[daemon] WARNING: not fully ready, proceeding anyway"
        }
    } catch {
        Write-Log "[daemon] ERROR: still not responding after 20s, aborting"
        exit 1
    }
}

# 运行日报摘要
Write-Log "[digest] running report_digest.py --full-content ..."
$output = py report_digest.py --date $TargetDate --full-content 2>&1
$output | ForEach-Object { Write-Log $_ }

Write-Log "[digest] ===== 完成 ====="
