@echo off
echo Starting File Cleaner Tool...
"C:\Users\TU\AppData\Local\Programs\Python\Python311\python.exe" gui.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
)
pause
