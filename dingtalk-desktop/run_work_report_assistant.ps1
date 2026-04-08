# run_work_report_assistant.ps1
# 由计划任务调用：执行 work_report_assistant_run.py --scenario <id>
# 用法: .\run_work_report_assistant.ps1 -Scenario morning_digest

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("morning_digest", "weekly_material", "weekly_px_insight", "weekly_ai_px_report")]
    [string]$Scenario
)

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("work_report_assistant_{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    Write-Host $line
    [System.IO.File]::AppendAllText($LogFile, "$line`n", [System.Text.Encoding]::UTF8)
}

Write-Log "===== work_report_assistant start scenario=$Scenario ====="
try {
    & py work_report_assistant_run.py --scenario $Scenario 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) { Write-Log "WARN exit code $LASTEXITCODE" }
}
catch {
    Write-Log "ERROR $($_.Exception.Message)"
}
Write-Log "===== work_report_assistant end ====="
