$ErrorActionPreference = "Stop"

$repoRoot = "D:\MyAgents"
$workspacesRoot = "$env:USERPROFILE\multica_workspaces"

$env:MULTICA_REPOS_ROOT = $repoRoot
$env:MULTICA_WORKSPACES_ROOT = $workspacesRoot
$env:MULTICA_DAEMON_MAX_CONCURRENT_TASKS = "2"
$env:MULTICA_KEEP_ENV_AFTER_TASK = "1"

Write-Host "Starting Multica daemon with isolated execution settings..."
Write-Host "MULTICA_REPOS_ROOT=$env:MULTICA_REPOS_ROOT"
Write-Host "MULTICA_WORKSPACES_ROOT=$env:MULTICA_WORKSPACES_ROOT"
Write-Host "MULTICA_DAEMON_MAX_CONCURRENT_TASKS=$env:MULTICA_DAEMON_MAX_CONCURRENT_TASKS"

multica daemon start
multica daemon status --output json
