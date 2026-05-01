$ErrorActionPreference = "Stop"

$taskRoot = "D:\MyAgents\tools\startup-orchestration"
$chainPs1 = Join-Path $taskRoot "boot-postlogon-chain.ps1"

function Invoke-TaskCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command
    )

    cmd /c $Command | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command"
    }
}

function Invoke-TaskCommandIgnore {
    param(
        [Parameter(Mandatory = $true)][string]$Command
    )

    cmd /c $Command | Out-Null
}

Write-Host "[0/6] Remove legacy per-phase tasks (ignore if missing)..."
Invoke-TaskCommandIgnore "schtasks /Delete /F /TN `"Hermes-Manman-Bootstrap`" >nul 2>&1"
Invoke-TaskCommandIgnore "schtasks /Delete /F /TN `"OpenClaw2-XiaoMa`" >nul 2>&1"
Invoke-TaskCommandIgnore "schtasks /Delete /F /TN `"PM-Bootstrap`" >nul 2>&1"

Write-Host "[1/6] Register DingTalk-Daemon (ONSTART, chain head)..."
Invoke-TaskCommand "schtasks /Create /F /TN `"DingTalk-Daemon`" /SC ONSTART /DELAY 0000:15 /TR `"py -u D:\MyAgents\dingtalk-desktop\daemon.py`""

Write-Host "[2/6] Register Legion-PostLogon-Bootstrap (ONLOGON: 满满+小马+PM in one script)..."
Invoke-TaskCommand "schtasks /Create /F /TN `"Legion-PostLogon-Bootstrap`" /SC ONLOGON /DELAY 0001:00 /TR `"powershell -NoProfile -ExecutionPolicy Bypass -File $chainPs1`""

Write-Host "[3/6] Disable standalone OpenClaw Gateway (avoid duplicate 18789)..."
Invoke-TaskCommandIgnore "schtasks /Change /TN `"OpenClaw Gateway`" /DISABLE >nul 2>&1"

Write-Host "Done. DingTalk still ONSTART; Hermes+XiaoMa+PM run after user logon (see boot-postlogon-chain.ps1)."
Write-Host "Logs: $taskRoot\logs\"
