# 启动 Multica 钉钉 Stream 派单桥；凭据读同目录 .env（勿提交）。
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
# 合并 Machine+User PATH，避免双击/计划任务启动时找不到 multica（仅继承窄 PATH）。
$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath"
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "未找到 .venv，请先执行: py -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -r requirements.txt"
    exit 1
}
& ".\.venv\Scripts\python.exe" ".\dispatch_bot.py"
