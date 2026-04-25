@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
echo ==========================================
echo  硅基军团 - Advisor 批量启动
echo ==========================================
echo.

start "PM阿茳 - 8300" cmd /k "cd advisors\pm && start.bat"
timeout /t 2 >nul

start "策划小美 - 8301" cmd /k "cd advisors\design && start.bat"
timeout /t 2 >nul

start "关怀师妙妙 - 8302" cmd /k "cd advisors\care && start.bat"
timeout /t 2 >nul

echo.
echo 三个 Advisor 已启动，各自独立窗口运行。
echo 健康检查: http://localhost:8300/health http://localhost:8301/health http://localhost:8302/health
pause
