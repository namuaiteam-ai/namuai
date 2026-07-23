@echo off
chcp 65001 >nul
:: YouTube Shorts 웹 UI 실행 스크립트 (Windows)
:: 실행: run_app.bat 더블클릭 -> http://localhost:5000 자동으로 열립니다.

cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 goto :no_python

python shorts_app.py
pause
exit /b 0

:no_python
echo [오류] Python이 설치되어 있지 않습니다.
echo  설치: https://www.python.org/downloads/
pause
exit /b 1
