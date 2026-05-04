@echo off
title GAME DEV AUTO-OFFICE ARMY COMMANDER
color 0b

echo ==================================================
echo      INITIALIZING CENTRAL COMMAND PROTOCOLS
echo ==================================================
echo.

echo [1/3] Mobilizing Intelligence Legion (LLM Plotter)...
start "LLM Plotter" /min cmd /k "cd llm-plotter && streamlit run app.py --server.headless=true"

echo [2/3] Deploying Alignment Legion (AlignFlow)...
start "AlignFlow Backend" /min cmd /k "cd align-flow\backend && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
start "AlignFlow Frontend" /min cmd /k "cd align-flow && npm run dev"


echo [3/3] Launching Central Command Console...
timeout /t 3 >nul
start central-console\index.html

echo.
echo ==================================================
echo             SYSTEMS ONLINE
echo ==================================================
echo.
echo.
echo You may close this window, but keep the service windows open (LLM Plotter, AlignFlow).
echo.
echo REM To start dispatch_bot with watchdog: cd tools\multica-dingtalk-bridge && py watchdog.py
pause
