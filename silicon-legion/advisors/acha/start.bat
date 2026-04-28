@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [启动] PM阿茶 (port 8301)...
py main.py
