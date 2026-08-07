@echo off
chcp 65001 >nul
:: Gemini 이미지 프롬프트 자동화 - 웹 UI 실행 스크립트 (Windows)

cd /d "%~dp0"

echo ============================================================
echo  Gemini 이미지 프롬프트 자동화 UI
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo  설치: https://www.python.org/downloads/
    pause & exit /b 1
)

python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [알림] 필요한 패키지를 설치합니다: flask, selenium
    pip install flask selenium
)

echo 브라우저가 자동으로 열립니다. (http://localhost:5001)
echo 창을 닫으려면 이 콘솔에서 Ctrl+C 를 누르세요.
echo.

python gemini_app.py

pause
