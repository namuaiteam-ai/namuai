@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 의존성 확인 중...
pip install -q -r requirements.txt

echo.
echo  네이버 뉴스 실시간 크롤러 시작
echo  브라우저: http://localhost:5000
echo  종료: Ctrl+C
echo.

python app.py
pause
