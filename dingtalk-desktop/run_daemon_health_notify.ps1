# One-click: daemon /health, restart if needed, DingTalk notify (webhook_config default)
Set-Location $PSScriptRoot
py daemon_health_notify.py @args
