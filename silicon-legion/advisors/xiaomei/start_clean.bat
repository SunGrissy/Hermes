@echo off
chcp 65001 >nul
cd /d "%~dp0"
set DINGTALK_CLIENT_ID=
set DINGTALK_CLIENT_SECRET=
set DINGTALK_APP_SECRET=
set DINGTALK_AGENT_ID=
set DINGTALK_AGENT=
echo [START] Design Advisor XiaoMei (port 8302)...
py main.py
