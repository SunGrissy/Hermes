@echo off
chcp 65001 >nul 2>&1
title MD Reader
cd /d "%~dp0"
echo Starting MD Reader...
echo http://localhost:8899
echo.
py server.py
if errorlevel 1 (
    echo.
    echo [Failed] Try: py server.py
    pause
)
