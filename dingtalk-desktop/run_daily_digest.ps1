# run_daily_digest.ps1
# UTF-8 BOM required: Task Scheduler uses Windows PowerShell 5.1 which defaults to system ANSI for scripts without BOM.
# Daily report digest: grouped segments, configurable DingTalk notify density.

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$LogFile = Join-Path $ScriptDir "logs\digest_$(Get-Date -Format 'yyyyMMdd').log"
$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$DigestWebhookUrl = $null
$CfgPath = Join-Path $ScriptDir "digest_config.json"
try {
    $cfgEarly = Get-Content -Path $CfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $DigestWebhookUrl = $cfgEarly.webhook_url
} catch {
    $DigestWebhookUrl = $null
}

# NotifyRank: 0=minimal 1=normal 2=full (digest_run.ps1_notify_level)
$script:NotifyRank = 0

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

function Digest-Notify {
    param(
        [int]$NeedRank,
        [string]$Phase,
        [string]$Detail
    )
    if ($script:NotifyRank -lt $NeedRank) {
        return
    }
    Send-DigestNotify $Phase $Detail
}

function Ensure-DaemonReady {
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

    Digest-Notify 1 "Daemon 状态" $daemonDetail

    if ($daemonOk) { return $true }

    Start-Process -FilePath "py" -ArgumentList "daemon.py" -WindowStyle Hidden -WorkingDirectory $ScriptDir
    Write-Log "[daemon] started, waiting 20s for frida attach..."
    Digest-Notify 1 "启动 Daemon" "已执行 `py daemon.py`，等待约 20 秒 attach..."
    Start-Sleep -Seconds 20
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:19200/health" -TimeoutSec 5 -UseBasicParsing
        $json = $resp.Content | ConvertFrom-Json
        if ($json.frida_attached -eq $true -and $json.cef_ready -eq $true) {
            Write-Log "[daemon] ready (pid=$($json.pid))"
            Digest-Notify 1 "Daemon 就绪" ("frida/cef 已 OK，pid=$($json.pid)。即将跑 report_digest。")
            return $true
        }
        Write-Log "[daemon] WARNING: not fully ready, proceeding anyway"
        Digest-Notify 1 "Daemon 未完全就绪" "仍将尝试执行日报整理（可能失败或变慢）。"
        return $true
    } catch {
        Write-Log "[daemon] ERROR: still not responding after 20s, aborting"
        Send-DigestNotify "失败" "daemon 在 20s 后仍无健康响应，**任务中止**。请检查钉钉是否打开、本机 19200 端口。"
        return $false
    }
}

function Resolve-DigestGroups {
    param([object]$Cfg)
    $grouped = @{}
    $firstOrder = New-Object System.Collections.Generic.List[string]
    foreach ($entry in ($Cfg.report_cids | Where-Object { $_ -ne $null })) {
        $gid = [string]$entry.digest_group
        if ([string]::IsNullOrWhiteSpace($gid)) { $gid = "_default" }
        $gid = $gid.ToLower()
        if (-not $grouped.ContainsKey($gid)) {
            $grouped[$gid] = New-Object System.Collections.ArrayList
            [void]$firstOrder.Add($gid)
        }
        [void]$grouped[$gid].Add($entry)
    }

    $labels = @{}
    if ($Cfg.digest_group_labels) {
        foreach ($p in $Cfg.digest_group_labels.PSObject.Properties) {
            $labels[$p.Name.ToLower()] = [string]$p.Value
        }
    }

    $ordered = New-Object System.Collections.Generic.List[string]
    $seen = @{}
    if ($Cfg.digest_group_order) {
        foreach ($raw in $Cfg.digest_group_order) {
            $gid = ([string]$raw).ToLower()
            if ($grouped.ContainsKey($gid) -and -not $seen.ContainsKey($gid)) {
                [void]$ordered.Add($gid)
                $seen[$gid] = $true
            }
        }
    }
    foreach ($gid in $firstOrder) {
        if (-not $seen.ContainsKey($gid)) {
            [void]$ordered.Add($gid)
            $seen[$gid] = $true
        }
    }
    if ($ordered.Contains("_default")) {
        [void]$ordered.Remove("_default")
        [void]$ordered.Add("_default")
    }

    $targets = @()
    foreach ($gid in $ordered) {
        $label = if ($labels.ContainsKey($gid)) { $labels[$gid] } else { $gid }
        $targets += [pscustomobject]@{
            GroupId = $gid
            Label = $label
            GroupCount = @($grouped[$gid]).Count
        }
    }
    return ,$targets
}

function Parse-DigestMetaLine {
    param([string[]]$Lines)
    $hit = $Lines | Where-Object { $_ -match '^\[digest-meta\]\s+' } | Select-Object -Last 1
    if (-not $hit) {
        return $null
    }
    $m = [regex]::Match($hit, 'full_content_enriched=(\d+)')
    $m2 = [regex]::Match($hit, 'full_content_with_url=(\d+)')
    $m3 = [regex]::Match($hit, 'full_content_messages=(\d+)')
    $en = if ($m.Success) { [int]$m.Groups[1].Value } else { -1 }
    $wu = if ($m2.Success) { [int]$m2.Groups[1].Value } else { -1 }
    $mc = if ($m3.Success) { [int]$m3.Groups[1].Value } else { -1 }
    return [pscustomobject]@{
        Enriched = $en
        WithUrl = $wu
        Messages = $mc
        Raw = $hit
    }
}

function Run-OneGroupDigest {
    param(
        [string]$GroupId,
        [string]$GroupLabel,
        [string]$TargetDate,
        [int]$MaxWaitSec,
        [bool]$UseProgressWebhook
    )
    $runTag = Get-Date -Format "yyyyMMdd_HHmmss_${GroupId}"
    $stdoutFile = Join-Path $ScriptDir ("logs\digest_run_stdout_{0}.log" -f $runTag)
    $stderrFile = Join-Path $ScriptDir ("logs\digest_run_stderr_{0}.log" -f $runTag)
    $progressIntervalSec = 60
    $timedOut = $false
    $startAt = Get-Date

    $argv = @("report_digest.py", "--date", $TargetDate, "--full-content", "--digest-group", $GroupId)
    if ($UseProgressWebhook) {
        $argv += "--notify-default"
    }

    $proc = Start-Process -FilePath "py" `
        -ArgumentList $argv `
        -WorkingDirectory $ScriptDir `
        -NoNewWindow `
        -RedirectStandardOutput $stdoutFile `
        -RedirectStandardError $stderrFile `
        -PassThru

    $elapsedWait = 0
    while ($elapsedWait -lt $MaxWaitSec) {
        $slice = [Math]::Min($progressIntervalSec, $MaxWaitSec - $elapsedWait)
        $exitedInTime = Wait-Process -Id $proc.Id -Timeout $slice -ErrorAction SilentlyContinue
        if ($exitedInTime) { break }
        $elapsedWait += $slice
        if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) { break }
        Digest-Notify 2 "进行中" ("分组 **{0}** 仍在运行，已等待 **{1}s** / 上限 **{2}s**。`n日志: digest_run_*_{3}*" -f $GroupLabel, $elapsedWait, $MaxWaitSec, $runTag)
    }

    if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {
        $timedOut = $true
        Write-Log ("[digest] ERROR: group={0} timeout after {1}s, killing pid={2}" -f $GroupId, $MaxWaitSec, $proc.Id)
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }

    $output = @()
    if (Test-Path $stdoutFile) { $output += Get-Content -Path $stdoutFile -Encoding UTF8 }
    if (Test-Path $stderrFile) { $output += Get-Content -Path $stderrFile -Encoding UTF8 }
    $output | ForEach-Object { Write-Log $_ }

    $exitCode = $null
    try {
        $proc.Refresh()
        if ($proc.HasExited) { $exitCode = $proc.ExitCode }
    } catch { }

    $meta = Parse-DigestMetaLine -Lines $output

    $status = "success"
    if ($timedOut) {
        $status = "timeout"
    } elseif ($exitCode -ne $null -and $exitCode -ne 0) {
        $status = "failed"
    }

    $elapsed = [int]((Get-Date) - $startAt).TotalSeconds
    return [pscustomobject]@{
        GroupId = $GroupId
        Label = $GroupLabel
        Status = $status
        ExitCode = $exitCode
        ElapsedSec = $elapsed
        RunTag = $runTag
        FullEnriched = $(if ($meta) { $meta.Enriched } else { $null })
        FullWithUrl = $(if ($meta) { $meta.WithUrl } else { $null })
        FullMessages = $(if ($meta) { $meta.Messages } else { $null })
    }
}

function Restart-DingTalk {
    Write-Log "[digest] restarting DingTalk to restore UI ..."
    Digest-Notify 1 "重启钉钉" "正在重启钉钉客户端以恢复搜索框等 UI（约数秒）..."
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
        Digest-Notify 1 "钉钉已重启" "DingTalk.exe 已启动，watchdog 约在 30s 内重新 attach。"
    } else {
        Write-Log "[digest] WARNING: DingTalk.exe not found at $dtPath"
        Digest-Notify 1 "警告" ("未找到 DingTalk.exe: **{0}**`n请手动打开钉钉。" -f $dtPath)
    }
}

Write-Log "[digest] ===== daily digest task start ====="

$today = Get-Date
$yesterday = $today.AddDays(-1)
if ($today.DayOfWeek -eq [DayOfWeek]::Monday) {
    $yesterday = $today.AddDays(-3)
}
$TargetDate = $yesterday.ToString("yyyy-MM-dd")
Write-Log "[digest] target date = $TargetDate"

$cfg = $null
try {
    $cfg = Get-Content -Path $CfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Log "[digest] WARN: failed to load digest_config.json"
}

$maxWaitSecPerGroup = 480
$interGroupWaitSec = 15
$useProgressWebhook = $false
if ($cfg -and $cfg.digest_run) {
    if ($cfg.digest_run.max_seconds_per_group -is [int]) { $maxWaitSecPerGroup = [int]$cfg.digest_run.max_seconds_per_group }
    if ($cfg.digest_run.inter_group_wait_seconds -is [int]) { $interGroupWaitSec = [int]$cfg.digest_run.inter_group_wait_seconds }
    $lvl = [string]$cfg.digest_run.ps1_notify_level
    if ($lvl -eq 'normal') { $script:NotifyRank = 1 }
    elseif ($lvl -eq 'full') { $script:NotifyRank = 2 }
    else { $script:NotifyRank = 0 }
    if ($cfg.digest_run.use_progress_webhook -is [bool]) {
        $useProgressWebhook = $cfg.digest_run.use_progress_webhook
    }
}
if ($env:DIGEST_MAX_WAIT_SEC) {
    $tmp = 0
    if ([int]::TryParse($env:DIGEST_MAX_WAIT_SEC, [ref]$tmp) -and $tmp -gt 0) {
        $maxWaitSecPerGroup = $tmp
    }
}
if ($env:DIGEST_INTER_WAIT_SEC) {
    $tmp2 = 0
    if ([int]::TryParse($env:DIGEST_INTER_WAIT_SEC, [ref]$tmp2) -and $tmp2 -ge 0) {
        $interGroupWaitSec = $tmp2
    }
}
if ($env:DIGEST_USE_PROGRESS_WEBHOOK -eq '1') {
    $useProgressWebhook = $true
}

if (-not (Ensure-DaemonReady)) {
    exit 1
}

$targets = @()
if ($cfg) {
    $targets = Resolve-DigestGroups -Cfg $cfg
}
if (-not $targets -or $targets.Count -eq 0) {
    $targets = @([pscustomobject]@{ GroupId = "_default"; Label = "默认分组"; GroupCount = 0 })
}
if ($env:DIGEST_GROUP_IDS) {
    $wanted = @{}
    foreach ($gidRaw in ($env:DIGEST_GROUP_IDS -split ',')) {
        $gid = ($gidRaw.Trim().ToLower())
        if (-not [string]::IsNullOrWhiteSpace($gid)) { $wanted[$gid] = $true }
    }
    if ($wanted.Count -gt 0) {
        $targets = @($targets | Where-Object { $wanted.ContainsKey($_.GroupId.ToLower()) })
    }
}
if (-not $targets -or $targets.Count -eq 0) {
    Write-Log "[digest] no digest groups selected, exit."
    Send-DigestNotify "任务结束" "未匹配到分组（可能是 DIGEST_GROUP_IDS 过滤后为空），任务未执行。"
    exit 1
}

Write-Log ("[digest] groups: {0}" -f (($targets | ForEach-Object { "$($_.GroupId)[$($_.GroupCount)]" }) -join ", "))
Write-Log ("[digest] notify_rank={0} use_progress_webhook={1}" -f $script:NotifyRank, $useProgressWebhook)

$notifyLevelLabel = "minimal"
if ($cfg -and $cfg.digest_run -and $cfg.digest_run.ps1_notify_level) {
    $notifyLevelLabel = [string]$cfg.digest_run.ps1_notify_level
}
$startBody = @(
    "统计日期: **$TargetDate**",
    "共 **$($targets.Count)** 组 · 单组上限 **${maxWaitSecPerGroup}s** · 组间 **${interGroupWaitSec}s**",
    "通知档位: **$notifyLevelLabel** · 子进程进度 webhook: **$useProgressWebhook**"
) -join "`n"
Digest-Notify 0 "已开始" $startBody
Digest-Notify 2 "分组编排" ("共 **{0}** 组，单组上限 **{1}s**，组间等待 **{2}s**。" -f $targets.Count, $maxWaitSecPerGroup, $interGroupWaitSec)

$results = @()
for ($i = 0; $i -lt $targets.Count; $i++) {
    $t = $targets[$i]
    $idx = $i + 1
    Write-Log ("[digest] start group {0}/{1}: {2} ({3})" -f $idx, $targets.Count, $t.Label, $t.GroupId)
    Digest-Notify 2 "开始分组" ("第 **{0}/{1}** 组：**{2}** (`{3}`)；监听群 **{4}** 个" -f $idx, $targets.Count, $t.Label, $t.GroupId, $t.GroupCount)

    $ret = Run-OneGroupDigest -GroupId $t.GroupId -GroupLabel $t.Label -TargetDate $TargetDate -MaxWaitSec $maxWaitSecPerGroup -UseProgressWebhook:$useProgressWebhook
    $results += $ret

    if ($ret.Status -eq "success") {
        Digest-Notify 2 "分组完成" ("**{0}** 完成，耗时 **{1}s**，exit={2}" -f $ret.Label, $ret.ElapsedSec, $(if ($ret.ExitCode -eq $null) { "n/a" } else { $ret.ExitCode }))
    } elseif ($ret.Status -eq "timeout") {
        Digest-Notify 1 "分组超时" ("**{0}** 超时，已终止进程。`n日志 tag: **{1}**" -f $ret.Label, $ret.RunTag)
    } else {
        Digest-Notify 1 "分组失败" ("**{0}** 失败，exit={1}。`n日志 tag: **{2}**" -f $ret.Label, $ret.ExitCode, $ret.RunTag)
    }

    if ($idx -lt $targets.Count) {
        Write-Log ("[digest] wait {0}s before next group" -f $interGroupWaitSec)
        Start-Sleep -Seconds $interGroupWaitSec
    }
}

$ok = @($results | Where-Object { $_.Status -eq "success" }).Count
$timeout = @($results | Where-Object { $_.Status -eq "timeout" }).Count
$failed = @($results | Where-Object { $_.Status -eq "failed" }).Count
$lines = @()
foreach ($r in $results) {
    $st = if ($r.Status -eq "success") { "成功" } elseif ($r.Status -eq "timeout") { "超时" } else { "失败(exit=$($r.ExitCode))" }
    $fc = ""
    if ($r.FullEnriched -ne $null -and $r.FullWithUrl -ne $null) {
        $fc = "，CEF全文 **$($r.FullEnriched)/$($r.FullWithUrl)**（消息 $($r.FullMessages) 条）"
    }
    $lines += ("- **{0}**：{1}，耗时 {2}s{3}" -f $r.Label, $st, $r.ElapsedSec, $fc)
}
$summary = "共 **{0}** 组：成功 **{1}**，超时 **{2}**，失败 **{3}**`n统计日 **{4}**`n已重启钉钉恢复 UI。" -f $results.Count, $ok, $timeout, $failed, $TargetDate
Digest-Notify 0 "任务汇总" ($summary + "`n`n" + ($lines -join "`n"))

Restart-DingTalk
Write-Log "[digest] ===== done ====="
Digest-Notify 2 "任务结束" ("日报分组流程已全部跑完（含钉钉重启）。统计日 **{0}**。" -f $TargetDate)
