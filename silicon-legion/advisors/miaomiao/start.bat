@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [启动] 关怀师妙妙 (port 8303)...
py main.py
