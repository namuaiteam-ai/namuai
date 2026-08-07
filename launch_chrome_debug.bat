@echo off
REM Restarts Chrome with a remote debugging port so the Gemini automation
REM script can attach to it and reuse your normal logged-in Google account.
REM WARNING: this force-closes ALL open Chrome windows/tabs first. Save
REM anything important before running this.

echo ============================================================
echo  Restart Chrome in debug mode (keeps your normal login)
echo ============================================================
echo.
echo All open Chrome windows will be closed. Continue?
pause

taskkill /IM chrome.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME_PATH% set CHROME_PATH="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

start "" %CHROME_PATH% --remote-debugging-port=9222 --profile-directory="Default"

echo.
echo Chrome restarted in debug mode on port 9222, still logged in as usual.
echo Now use gemini_app.py (web UI) or the --attach option to connect to this window.
echo.
pause
