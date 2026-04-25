# OpenClaw 本机网关一键启动（状态目录固定为 D:\OpenClaw）
# 控制台：http://127.0.0.1:18789/
#
# 模型后端：
# - 若使用 Ollama：先启动 Ollama（托盘或 ollama serve）
# - 若使用自定义兼容网关：先执行 tools\openclaw-apply-custom-llm.ps1 写入配置，并保证 Base URL 可达

$ErrorActionPreference = "Stop"

$env:OPENCLAW_STATE_DIR = "D:\OpenClaw"
$env:OPENCLAW_CONFIG_PATH = "D:\OpenClaw\openclaw.json"
$envFile = "D:\OpenClaw\.env"

if (Test-Path $envFile) {
  $relay = Select-String -Path $envFile -Pattern '^TUYOO_RELAY_API_KEY=(.*)$' | Select-Object -First 1
  if ($relay -and $relay.Matches.Count -gt 0) {
    $env:TUYOO_RELAY_API_KEY = $relay.Matches[0].Groups[1].Value.Trim()
  }
}

if ([string]::IsNullOrWhiteSpace($env:TUYOO_RELAY_API_KEY)) {
  throw "[OpenClaw] TUYOO_RELAY_API_KEY 缺失：请在 D:\OpenClaw\.env 配置后重试。"
}

Write-Host "[OpenClaw] Stopping existing gateway on 18789 if any..."
openclaw gateway stop 2>$null
Start-Sleep -Seconds 2

Write-Host "[OpenClaw] Starting gateway (foreground). Ctrl+C to stop."
Write-Host "[OpenClaw] Dashboard: http://127.0.0.1:18789/"
openclaw gateway --port 18789
