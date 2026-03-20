# Restart dingtalk-desktop daemon: POST /shutdown, wait, then start py daemon.py (ASCII-only output for Windows consoles)

$ErrorActionPreference = 'SilentlyContinue'
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:19200/shutdown" -Method POST -TimeoutSec 3 | Out-Null
} catch {}
Start-Sleep -Seconds 3
Set-Location $PSScriptRoot
Start-Process -FilePath "py" -ArgumentList "daemon.py" -WindowStyle Hidden -PassThru | Out-Null
Start-Sleep -Seconds 2
try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:19200/health" -Method Get -TimeoutSec 8
    Write-Host ("OK: daemon={0} frida_attached={1} cef_ready={2} pid={3}" -f $r.daemon, $r.frida_attached, $r.cef_ready, $r.pid)
} catch {
    Write-Host ("WARN: /health not responding yet (Frida may still attach). {0}" -f $_.Exception.Message)
}
