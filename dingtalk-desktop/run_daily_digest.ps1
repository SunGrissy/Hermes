# run_daily_digest.ps1
# Daily report digest scheduled script (progress + failure alerts via DingTalk webhook)

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$LogFile = Join-Path $ScriptDir "logs\digest_$(Get-Date -Format 'yyyyMMdd').log"
$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# Webhook + keyword for DingTalk custom-keyword robots
$DigestWebhookUrl = $null
$CfgPath = Join-Path $ScriptDir "digest_config.json"
try {
    $cfgEarly = Get-Content -Path $CfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $DigestWebhookUrl = $cfgEarly.webhook_url
} catch {
    $DigestWebhookUrl = $null
}

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'HH:mm:ss') $Msg"
    Write-Host $line
    [System.IO.File]::AppendAllText($LogFile, "$line`n", [System.Text.Encoding]::UTF8)
}

function Send-DigestNotify {
    param(
        [string]$Phase,
        [string]$Detail
    )
    if (-not $DigestWebhookUrl) {
        return
    }
    $kw = "小秘书提醒"
    $safePhase = if ($Phase) { $Phase } else { "日报整理" }
    $safeDetail = if ($Detail) { $Detail } else { "" }
    $text = "### $kw · 日报整理`n**$safePhase**`n`n$safeDetail`n`n---`n###### ※ $kw"
    $bodyObj = @{
        msgtype  = "markdown"
        markdown = @{
            title = "$kw · 日报整理"
            text  = $text
        }
    }
    $body = $bodyObj | ConvertTo-Json -Compress -Depth 5
    try {
        Invoke-RestMethod -Uri $DigestWebhookUrl -Method Post -Body $body -ContentType "application/json; charset=utf-8" -TimeoutSec 15 | Out-Null
    } catch {
        Write-Log ("[notify] webhook failed: {0}" -f $_.Exception.Message)
    }
}

Write-Log "[digest] ===== daily digest task start ====="

# Target date: yesterday; on Monday use last Friday
$today = Get-Date
$yesterday = $today.AddDays(-1)
if ($today.DayOfWeek -eq [DayOfWeek]::Monday) {
    $yesterday = $today.AddDays(-3)
}
$TargetDate = $yesterday.ToString("yyyy-MM-dd")
Write-Log "[digest] target date = $TargetDate"

Send-DigestNotify "已开始" ("统计日期: **{0}**`n正在检查 daemon (19200)..." -f $TargetDate)

# Check daemon health
$daemonOk = $false
$daemonDetail = ""
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:19200/health" -TimeoutSec 5 -UseBasicParsing
    $json = $resp.Content | ConvertFrom-Json
    if ($json.daemon -eq "running" -and $json.frida_attached -eq $true -and $json.cef_ready -eq $true) {
        $daemonOk = $true
        $daemonDetail = "daemon 已就绪 (pid=$($json.pid), frida/cef OK)。"
        Write-Log "[daemon] already running (pid=$($json.pid), frida=ok, cef=ok)"
    } else {
        $daemonDetail = "daemon 在跑但未完全就绪: frida=$($json.frida_attached) cef=$($json.cef_ready)。将尝试拉起或继续。"
        Write-Log "[daemon] running but not ready: frida=$($json.frida_attached) cef=$($json.cef_ready)"
    }
} catch {
    $daemonDetail = "未探测到 daemon，将后台启动 daemon.py 并等待约 20s。"
    Write-Log "[daemon] not running, starting..."
}

Send-DigestNotify "Daemon 状态" $daemonDetail

if (-not $daemonOk) {
    Start-Process -FilePath "py" -ArgumentList "daemon.py" -WindowStyle Hidden -WorkingDirectory $ScriptDir
    Write-Log "[daemon] started, waiting 20s for frida attach..."
    Send-DigestNotify "启动 Daemon" "已执行 `py daemon.py`，等待约 20 秒 attach..."
    Start-Sleep -Seconds 20
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:19200/health" -TimeoutSec 5 -UseBasicParsing
        $json = $resp.Content | ConvertFrom-Json
        if ($json.frida_attached -eq $true -and $json.cef_ready -eq $true) {
            Write-Log "[daemon] ready (pid=$($json.pid))"
            Send-DigestNotify "Daemon 就绪" ("frida/cef 已 OK，pid=$($json.pid)。即将跑 report_digest。")
        } else {
            Write-Log "[daemon] WARNING: not fully ready, proceeding anyway"
            Send-DigestNotify "Daemon 未完全就绪" "仍将尝试执行日报整理（可能失败或变慢）。"
        }
    } catch {
        Write-Log "[daemon] ERROR: still not responding after 20s, aborting"
        Send-DigestNotify "失败" "daemon 在 20s 后仍无健康响应，**任务中止**。请检查钉钉是否打开、本机 19200 端口。"
        exit 1
    }
}

# Run report digest with full-content mode
Write-Log "[digest] running report_digest.py --full-content ..."
Send-DigestNotify "拉取与分析" ("正在执行 `report_digest.py --full-content`，日期 **{0}**。`n完整拉取可能较慢，下方将每隔约 60s 同步进度。" -f $TargetDate)

$digestStart = Get-Date
$runTag = Get-Date -Format "yyyyMMdd_HHmmss"
$stdoutFile = Join-Path $ScriptDir ("logs\digest_run_stdout_{0}.log" -f $runTag)
$stderrFile = Join-Path $ScriptDir ("logs\digest_run_stderr_{0}.log" -f $runTag)
$maxWaitSec = 480
$timedOut = $false
$progressIntervalSec = 60

$proc = Start-Process -FilePath "py" `
    -ArgumentList @("report_digest.py", "--date", $TargetDate, "--full-content") `
    -WorkingDirectory $ScriptDir `
    -NoNewWindow `
    -RedirectStandardOutput $stdoutFile `
    -RedirectStandardError $stderrFile `
    -PassThru

$elapsedWait = 0
while ($elapsedWait -lt $maxWaitSec) {
    $slice = [Math]::Min($progressIntervalSec, $maxWaitSec - $elapsedWait)
    $exitedInTime = Wait-Process -Id $proc.Id -Timeout $slice -ErrorAction SilentlyContinue
    if ($exitedInTime) { break }
    $elapsedWait += $slice
    if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) { break }
    Send-DigestNotify "进行中" ("report_digest 仍在运行，已等待 **{0}s** / 上限 **{1}s**。`n日志: stdout/stderr 已写入 logs\digest_run_*_{2}*" -f $elapsedWait, $maxWaitSec, $runTag)
}

if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {
    $timedOut = $true
    Write-Log ("[digest] ERROR: report_digest timeout after {0}s, killing pid={1}" -f $maxWaitSec, $proc.Id)
    Send-DigestNotify "超时" ("report_digest 超过 **{0}s** 未完成，已强制结束进程。`n请查看 logs\digest_run_*_{1}* 与当日 digest 日志。" -f $maxWaitSec, $runTag)
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}

$digestEnd = Get-Date
$output = @()
if (Test-Path $stdoutFile) { $output += Get-Content -Path $stdoutFile -Encoding UTF8 }
if (Test-Path $stderrFile) { $output += Get-Content -Path $stderrFile -Encoding UTF8 }
if ($timedOut -and $output.Count -eq 0) {
    $output = @("[digest] ERROR: report_digest timed out with no output")
}
$digestLines = @($output)
$output | ForEach-Object { Write-Log $_ }

$elapsed = ($digestEnd - $digestStart).TotalSeconds
$pyExit = $null
try {
    if (-not $timedOut) {
        $proc.Refresh()
        if ($proc.HasExited) { $pyExit = $proc.ExitCode }
    }
} catch { }

$sendFailed = $false
$joinedOut = ($output -join "`n")
if ($joinedOut -match "send failed") { $sendFailed = $true }

# Short output: log only; final success/fail card below will explain
if ($digestLines.Count -lt 3) {
    Write-Log ("[digest] WARNING: output too short ({0} lines, {1}s), JSAPI may be unavailable" -f $digestLines.Count, [int]$elapsed)
}

$digestFailed = ($timedOut -or ($pyExit -ne $null -and $pyExit -ne 0) -or $sendFailed -or ($digestLines.Count -lt 3))
if ($digestFailed) {
    $reasons = @()
    if ($timedOut) { $reasons += "子进程超时" }
    if ($pyExit -ne $null -and $pyExit -ne 0) { $reasons += ("Python 退出码 {0}" -f $pyExit) }
    if ($sendFailed) { $reasons += "日志中出现 send failed（推送失败）" }
    if ($digestLines.Count -lt 3) { $reasons += "输出过少" }
    Send-DigestNotify "日报整理未成功" ("日期 **{0}**`n耗时 **{1}s**`n原因: {2}`n日志: logs\digest_run_*_{3}*" -f $TargetDate, [int]$elapsed, ($reasons -join "；"), $runTag)
} else {
    Send-DigestNotify "日报整理完成" ("日期 **{0}**`n耗时 **{1}s**`n子进程退出码 **{2}**`n摘要已通过 report_digest 推送到配置的目标（若群机器人正常应已收到）。`n本地日志 tag: **{3}**" -f $TargetDate, [int]$elapsed, $(if ($pyExit -eq $null) { "n/a" } else { $pyExit }), $runTag)
}

# Restart DingTalk to restore UI state
Write-Log "[digest] restarting DingTalk to restore UI ..."
Send-DigestNotify "重启钉钉" "正在重启钉钉客户端以恢复搜索框等 UI（约数秒）..."
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
    Send-DigestNotify "钉钉已重启" "DingTalk.exe 已启动，watchdog 约在 30s 内重新 attach。"
} else {
    Write-Log "[digest] WARNING: DingTalk.exe not found at $dtPath"
    Send-DigestNotify "警告" ("未找到 DingTalk.exe: **{0}**`n请手动打开钉钉。" -f $dtPath)
}

Write-Log "[digest] ===== done ====="
Send-DigestNotify "任务结束" ("日报定时流程已全部跑完（含钉钉重启）。统计日 **{0}**。" -f $TargetDate)
