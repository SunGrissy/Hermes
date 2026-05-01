# 手工/调试用。开机计划任务请用 boot-postlogon-chain.ps1（ONLOGON），避免 SYSTEM 起不来用户 npm 下的 OpenClaw。
$ErrorActionPreference = "Stop"

function Wait-Http {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$MaxAttempts = 40,
        [int]$SleepSeconds = 2
    )

    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            Invoke-WebRequest -Uri $Url -Method Get -UseBasicParsing -TimeoutSec 3 | Out-Null
            return $true
        } catch {
            Start-Sleep -Seconds $SleepSeconds
        }
    }

    return $false
}

function Start-IfPortClosed {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$FilePath
    )

    $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listening) {
        return
    }

    Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$FilePath`"" -WindowStyle Minimized
}

$dingtalkReady = Wait-Http -Url "http://127.0.0.1:19200/api/health" -MaxAttempts 45 -SleepSeconds 2
if (-not $dingtalkReady) {
    throw "DingTalk daemon is not ready at :19200, phase2 aborted."
}

Start-IfPortClosed -Port 18789 -FilePath "D:\OpenClaw\gateway.cmd"

$openclawReady = Wait-Http -Url "http://127.0.0.1:18789/health" -MaxAttempts 30 -SleepSeconds 2
if (-not $openclawReady) {
    throw "OpenClaw gateway is not ready at :18789, phase2 aborted."
}

Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"D:\OpenClaw\scripts\start_manman.bat`"" -WindowStyle Minimized
