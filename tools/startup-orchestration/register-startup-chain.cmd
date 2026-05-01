@echo off
cd /d "D:\MyAgents\tools\startup-orchestration"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register-startup-chain.ps1"
pause
