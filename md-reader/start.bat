@echo off
chcp 65001 >nul 2>&1
title MD Reader
cd /d "%~dp0"
echo Starting MD Reader...
echo http://localhost:8899
echo.
py -m uvicorn server:app --host 127.0.0.1 --port 8899
if errorlevel 1 (
    echo.
    echo [Failed] Make sure fastapi and uvicorn are installed:
    echo   pip install fastapi uvicorn
    pause
)
