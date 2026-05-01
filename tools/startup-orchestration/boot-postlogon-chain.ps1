# 登录后四棒链：钉钉(已起) -> 18789+满满 -> 18790小马 -> PM
# 须在用户已登录会话中运行（计划任务 ONLOGON），避免 SYSTEM 无法读用户 npm 下的 openclaw。

$ErrorActionPreference = "Stop"

$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir ("postlogon-chain-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
Start-Transcript -Path $logPath -Force

function Wait-Http {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$MaxAttempts = 120,
        [int]$SleepSeconds = 2
    )

    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            Invoke-WebRequest -Uri $Url -Method Get -UseBasicParsing -TimeoutSec 5 | Out-Null
            return $true
        } catch {
            Start-Sleep -Seconds $SleepSeconds
        }
    }

    return $false
}

function Test-TcpListen {
    param([Parameter(Mandatory = $true)][int]$Port)

    try {
        return [bool](Test-NetConnection -ComputerName 127.0.0.1 -TcpPort $Port -InformationLevel Quiet -WarningAction SilentlyContinue)
    } catch {
        return $false
    }
}

function Start-GatewayIfNeeded {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$GatewayCmd,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    if (Test-TcpListen -Port $Port) {
        Write-Host "Port $Port already listening, skip start."
        return
    }

    Write-Host "Starting gateway on port $Port ..."
    Start-Process -FilePath $GatewayCmd -WorkingDirectory $WorkingDirectory -WindowStyle Hidden
}

try {
    Write-Host "[1/4] Wait DingTalk :19200 ..."
    if (-not (Wait-Http -Url "http://127.0.0.1:19200/api/health" -MaxAttempts 90 -SleepSeconds 2)) {
        throw "DingTalk daemon not ready at :19200"
    }

    Write-Host "[2/4] OpenClaw 18789 + ManMan ..."
    Start-GatewayIfNeeded -Port 18789 -GatewayCmd "D:\OpenClaw\gateway.cmd" -WorkingDirectory "D:\OpenClaw"
    if (-not (Wait-Http -Url "http://127.0.0.1:18789/health" -MaxAttempts 180 -SleepSeconds 2)) {
        throw "OpenClaw :18789 /health not ready"
    }

    Start-Process -FilePath "D:\OpenClaw\scripts\start_manman.bat" -WorkingDirectory "D:\OpenClaw\scripts" -WindowStyle Hidden
    Start-Sleep -Seconds 15

    Write-Host "[3/4] OpenClaw2 18790 ..."
    Start-GatewayIfNeeded -Port 18790 -GatewayCmd "D:\OpenClaw2\gateway.cmd" -WorkingDirectory "D:\OpenClaw2"
    if (-not (Wait-Http -Url "http://127.0.0.1:18790/health" -MaxAttempts 180 -SleepSeconds 2)) {
        throw "OpenClaw2 :18790 /health not ready"
    }

    Write-Host "[4/4] PM quick_start 1/2/3/5 ..."
    & (Join-Path $PSScriptRoot "boot-phase4-pm.ps1")

    Write-Host "Post-logon chain finished OK."
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message)
    throw
} finally {
    try { Stop-Transcript } catch {}
}
