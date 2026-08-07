@echo off
REM Gemini image prompt automation - web UI launcher (Windows)

cd /d "%~dp0"

echo ============================================================
echo  Gemini Image Prompt Automation UI
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed.
    echo  Install: https://www.python.org/downloads/
    pause & exit /b 1
)

python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing required packages: flask, selenium
    pip install flask selenium
)

echo Browser will open automatically at http://localhost:5001
echo Press Ctrl+C in this window to stop the server.
echo.

python gemini_app.py

pause
