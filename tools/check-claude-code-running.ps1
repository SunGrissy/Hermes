# Check whether Claude Code appears to be running on Windows (claude.exe or node hosting @anthropic-ai/claude-code).
# Usage: pwsh -File "d:\MyAgents\tools\check-claude-code-running.ps1"
# Or:    powershell -ExecutionPolicy Bypass -File "d:\MyAgents\tools\check-claude-code-running.ps1"
# Notes: ASCII-only output so Windows PowerShell 5.x parses reliably without UTF-8 BOM.

$rows = @()

Get-Process -Name 'claude' -ErrorAction SilentlyContinue | ForEach-Object {
    $rows += [PSCustomObject]@{
        Kind = 'claude.exe'
        PID  = $_.Id
        Detail = $_.Path
    }
}

Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" | ForEach-Object {
    $cmd = $_.CommandLine
    if ($null -eq $cmd) { return }
    if ($cmd -match '@anthropic-ai[\\/]claude-code|(\\|\\/)claude-code(\\|\\/)') {
        $short = if ($cmd.Length -gt 140) { $cmd.Substring(0, 137) + '...' } else { $cmd }
        $rows += [PSCustomObject]@{
            Kind = 'node (claude-code package)'
            PID  = $_.ProcessId
            Detail = $short
        }
    }
}

Write-Host '=== Claude Code process check ==='
if ($rows.Count -eq 0) {
    Write-Host 'RESULT: No Claude Code related process found.'
    Write-Host 'HINT:   Claude Code usually runs while a terminal session has `claude` open; it is not a resident daemon.'
    Write-Host 'TIP:    Task Manager -> sort by name -> look for claude.exe'
    exit 0
}

Write-Host 'RESULT: Found process(es) that may be Claude Code:'
$rows | Format-Table -AutoSize -Wrap
exit 0
