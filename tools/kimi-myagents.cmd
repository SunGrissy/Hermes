@echo off
REM 固定以本仓库根目录作为 Kimi 工作区（等价于 kimi -w <repo>）
pushd "%~dp0.."
kimi -w "%CD%" %*
set "EXITCODE=%ERRORLEVEL%"
popd
exit /b %EXITCODE%
