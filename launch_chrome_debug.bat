@echo off
chcp 65001 >nul
:: Gemini 자동화가 "평소 쓰는 Chrome(이미 로그인된 구글 계정)"에 붙을 수 있도록
:: 원격 디버깅 포트를 열어서 Chrome 을 재시작합니다.
::
:: 주의: 열려 있는 Chrome 창/탭이 모두 강제로 닫힙니다. 작업 중이던 내용은 먼저 저장하세요.

echo ============================================================
echo  Chrome 디버그 모드로 재시작 (기존 로그인 유지)
echo ============================================================
echo.
echo 열려 있는 모든 Chrome 창이 닫힙니다. 계속하시겠습니까?
pause

taskkill /IM chrome.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME_PATH% set CHROME_PATH="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

start "" %CHROME_PATH% --remote-debugging-port=9222 --profile-directory="Default"

echo.
echo Chrome 이 디버그 모드(포트 9222)로 다시 열렸습니다.
echo 평소처럼 로그인되어 있는 상태 그대로입니다.
echo 이제 gemini_app.py(웹 UI)나 --attach 옵션으로 이 창에 연결해서 사용하세요.
echo.
pause
