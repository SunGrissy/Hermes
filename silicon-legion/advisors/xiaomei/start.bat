@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [启动] 策划小美 (port 8301)...
py main.py
