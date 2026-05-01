# 手工拉起：虾叔 18789 -> 满满 -> 小马 18790（不启 PM）
$ErrorActionPreference = "Continue"

function Wait-Health {
    param([string]$Url, [int]$MaxAttempts = 90, [int]$SleepSec = 2)
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 4 | Out-Null
            return $true
        } catch {
            Start-Sleep -Seconds $SleepSec
        }
    }
    return $false
}

function Test-Listen([int]$Port) {
    try {
        return [bool](Test-NetConnection -ComputerName 127.0.0.1 -TcpPort $Port -InformationLevel Quiet -WarningAction SilentlyContinue)
    } catch {
        return $false
    }
}

Write-Host "DingTalk :19200 ..."
if (-not (Wait-Health "http://127.0.0.1:19200/api/health" 30 2)) {
    Write-Host "WARN: 19200 not ready; still try gateways (钉钉若未起请先开 daemon)"
}

if (-not (Test-Listen 18789)) {
    Write-Host "Start OpenClaw :18789 ..."
    Start-Process -FilePath "D:\OpenClaw\gateway.cmd" -WorkingDirectory "D:\OpenClaw" -WindowStyle Minimized
} else {
    Write-Host "18789 already listening"
}

if (-not (Wait-Health "http://127.0.0.1:18789/health")) {
    Write-Host "ERROR: 18789 /health not ready"
    exit 1
}

Write-Host "Start ManMan ..."
Start-Process -FilePath "D:\OpenClaw\scripts\start_manman.bat" -WorkingDirectory "D:\OpenClaw\scripts" -WindowStyle Minimized
Start-Sleep -Seconds 10

if (-not (Test-Listen 18790)) {
    Write-Host "Start OpenClaw2 :18790 ..."
    Start-Process -FilePath "D:\OpenClaw2\gateway.cmd" -WorkingDirectory "D:\OpenClaw2" -WindowStyle Minimized
} else {
    Write-Host "18790 already listening"
}

if (-not (Wait-Health "http://127.0.0.1:18790/health")) {
    Write-Host "WARN: 18790 /health not ready (可多等几秒再查)"
    exit 2
}

Write-Host "Done: ManMan + XiaoMa gateways should be up."
exit 0
