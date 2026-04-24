# 将 OpenClaw 默认模型切到「自定义 OpenAI / Anthropic 兼容」端点（写入 D:\OpenClaw\openclaw.json）
# 用法：先在当前 PowerShell 会话里设置环境变量，再执行本脚本。
#
# 必填：
#   $env:OPENCLAW_CUSTOM_BASE_URL   例如 http://127.0.0.1:8080/v1  或  https://你的网关/v1
#   $env:OPENCLAW_CUSTOM_MODEL_ID   例如 gpt-4o-mini、qwen-max、部署名等（与对端一致）
# 可选：
#   $env:OPENCLAW_CUSTOM_API_KEY     若对端需要 Bearer / api-key，填密钥（勿写入脚本文件）
#   $env:OPENCLAW_CUSTOM_COMPAT       openai（默认）或 anthropic
#   $env:OPENCLAW_CUSTOM_PROVIDER_ID  写入 models.providers 的固定 id（仅小写字母数字连字符），便于辨认
#
# 说明：多数自建/代理网关为 OpenAI Chat Completions 兼容，用 openai 即可；Anthropic Messages 兼容才用 anthropic。
# 文档：https://docs.openclaw.ai/cli/onboard

$ErrorActionPreference = "Stop"

$env:OPENCLAW_STATE_DIR = "D:\OpenClaw"
$env:OPENCLAW_CONFIG_PATH = "D:\OpenClaw\openclaw.json"

$base = [string]$env:OPENCLAW_CUSTOM_BASE_URL
$model = [string]$env:OPENCLAW_CUSTOM_MODEL_ID
if ([string]::IsNullOrWhiteSpace($base) -or [string]::IsNullOrWhiteSpace($model)) {
    Write-Host "缺少环境变量：请先设置 OPENCLAW_CUSTOM_BASE_URL 与 OPENCLAW_CUSTOM_MODEL_ID，再运行本脚本。"
    exit 1
}

$compat = if ([string]::IsNullOrWhiteSpace($env:OPENCLAW_CUSTOM_COMPAT)) { "openai" } else { $env:OPENCLAW_CUSTOM_COMPAT.Trim() }
if ($compat -ne "openai" -and $compat -ne "anthropic") {
    Write-Host "OPENCLAW_CUSTOM_COMPAT 只能是 openai 或 anthropic。"
    exit 1
}

$args = @(
    "onboard", "--non-interactive", "--accept-risk", "--mode", "local",
    "--auth-choice", "custom-api-key",
    "--custom-base-url", $base.Trim(),
    "--custom-model-id", $model.Trim(),
    "--custom-compatibility", $compat,
    "--skip-channels", "--skip-search", "--skip-skills", "--skip-ui",
    "--no-install-daemon", "--skip-health"
)

if (-not [string]::IsNullOrWhiteSpace($env:OPENCLAW_CUSTOM_API_KEY)) {
    $args += "--custom-api-key"
    $args += $env:OPENCLAW_CUSTOM_API_KEY.Trim()
}

if (-not [string]::IsNullOrWhiteSpace($env:OPENCLAW_CUSTOM_PROVIDER_ID)) {
    $args += "--custom-provider-id"
    $args += $env:OPENCLAW_CUSTOM_PROVIDER_ID.Trim()
}

Write-Host "[OpenClaw] Applying custom LLM via onboard (non-interactive)..."
& openclaw @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[OpenClaw] Done. Validate: openclaw config validate"
Write-Host "[OpenClaw] Restart gateway: run tools\openclaw-start.ps1 or: openclaw gateway stop; openclaw gateway --port 18789"
