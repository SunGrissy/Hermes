# OpenClaw 本机网关一键启动（状态目录固定为 D:\OpenClaw）
# 控制台：http://127.0.0.1:18789/
#
# 模型后端：
# - 若使用 Ollama：先启动 Ollama（托盘或 ollama serve）
# - 若使用自定义兼容网关：先执行 tools\openclaw-apply-custom-llm.ps1 写入配置，并保证 Base URL 可达

$ErrorActionPreference = "Stop"

$env:OPENCLAW_STATE_DIR = "D:\OpenClaw"
$env:OPENCLAW_CONFIG_PATH = "D:\OpenClaw\openclaw.json"

Write-Host "[OpenClaw] Stopping existing gateway on 18789 if any..."
openclaw gateway stop 2>$null
Start-Sleep -Seconds 2

Write-Host "[OpenClaw] Starting gateway (foreground). Ctrl+C to stop."
Write-Host "[OpenClaw] Dashboard: http://127.0.0.1:18789/"
openclaw gateway --port 18789
