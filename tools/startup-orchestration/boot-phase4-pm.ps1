$ErrorActionPreference = "Stop"

function Start-PmStep {
    param(
        [Parameter(Mandatory = $true)][string]$Step
    )

    Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"D:\MyAgents\pm-system\quick_start.bat $Step`"" -WindowStyle Minimized -Wait
    Start-Sleep -Seconds 2
}

Start-PmStep -Step "1"
Start-PmStep -Step "2"
Start-PmStep -Step "3"
Start-PmStep -Step "5"
