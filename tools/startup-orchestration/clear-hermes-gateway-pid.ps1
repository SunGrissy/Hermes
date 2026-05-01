# 清理 D:\hermes 下各实例的 gateway.pid / gateway_state.json（不杀进程）
$root = "D:\hermes"
if (-not (Test-Path -LiteralPath $root)) {
    Write-Host "SKIP: $root not found"
    exit 0
}

Get-ChildItem -LiteralPath $root -Recurse -Filter "gateway.pid" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
        Write-Host "removed $($_.FullName)"
    }

Get-ChildItem -LiteralPath $root -Recurse -Filter "gateway_state.json" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
        Write-Host "removed $($_.FullName)"
    }

Write-Host "done"
