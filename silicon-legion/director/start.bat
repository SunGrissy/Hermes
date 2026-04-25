@echo off
chcp 65001 >nul
echo 启动 硅基军团总管服务（端口8299）...
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
py main.py
