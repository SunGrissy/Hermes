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
    # Add-Content -Encoding UTF8 在计划任务环境中对中文字符不稳定，改用 .NET 方法
    [System.IO.File]::AppendAllText($LogFile, "$line`n", [System.Text.Encoding]::UTF8)
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

# 运行日报摘要（带 --full-content 获取完整日报内容）
# full-content 会临时占用 browser 1，完成后通过重启钉钉恢复 UI 状态
Write-Log "[digest] running report_digest.py --full-content ..."
$digestStart = Get-Date
$output = py report_digest.py --date $TargetDate --full-content 2>&1
$digestEnd = Get-Date
$digestLines = @($output)
$output | ForEach-Object { Write-Log $_ }

# 如果输出极少（< 3 行），说明进程可能卡死后被外部杀掉，发告警
$elapsed = ($digestEnd - $digestStart).TotalSeconds
if ($digestLines.Count -lt 3) {
    Write-Log "[digest] WARNING: 输出异常少（$($digestLines.Count) 行，耗时 $([int]$elapsed)s），可能 JSAPI 不可用"
    $cfg = Get-Content -Path (Join-Path $ScriptDir "digest_config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $wh = $cfg.webhook_url
    if ($wh) {
        $body = @{msgtype="text"; text=@{content="[小秘书] ⚠️ $TargetDate 日报摘要任务异常：输出仅 $($digestLines.Count) 行，耗时 $([int]$elapsed)s。JSAPI 可能不可用，请检查钉钉/daemon 状态。"}} | ConvertTo-Json -Compress
        try { Invoke-RestMethod -Uri $wh -Method Post -Body $body -ContentType "application/json" -TimeoutSec 10 | Out-Null } catch {}
    }
}

# 重启钉钉以恢复 UI 状态（搜索框等）
Write-Log "[digest] restarting DingTalk to restore UI ..."
$dtProc = Get-Process -Name "DingTalk" -ErrorAction SilentlyContinue
if ($dtProc) {
    $dtProc | Stop-Process -Force
    Write-Log "[digest] DingTalk stopped, waiting 5s ..."
    Start-Sleep -Seconds 5
}
$dtPath = Join-Path ${env:ProgramFiles(x86)} "DingDing\main\current\DingTalk.exe"
if (Test-Path $dtPath) {
    Start-Process -FilePath $dtPath -WindowStyle Normal
    Write-Log "[digest] DingTalk restarted, watchdog will re-attach in ~30s"
} else {
    Write-Log "[digest] WARNING: DingTalk.exe not found at $dtPath"
}

Write-Log "[digest] ===== 完成 ====="
