# run_memo_reminder.ps1
# 备忘定时提醒（每日 09:30、14:00、17:30 各一次）
# 从 TaskReminder 读取待跟进备忘，通过 memo_tracker webhook 发到钉钉

$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

$DateTag = Get-Date -Format "yyyyMMdd"
$LogFile = Join-Path $LogDir "memo_reminder_$DateTag.log"

function Log($msg) {
    $ts = Get-Date -Format "HH:mm:ss"
    "$ts $msg" | Tee-Object -Append -FilePath $LogFile
}

Log "=== memo reminder start ==="

# Reminder uses webhook directly, no daemon needed
Log "running memo_reminder.py..."
py "$ScriptDir\memo_reminder.py" 2>&1 | Tee-Object -Append -FilePath $LogFile

Log "=== memo reminder done ==="
