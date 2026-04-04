@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 의존성 확인 중...
pip install -q -r requirements.txt

echo.
echo  NewFinder 뉴스 크롤러 시작
echo  브라우저 : http://localhost:8000
echo  API 문서 : http://localhost:8000/docs
echo  종료     : Ctrl+C
echo.

start "" http://localhost:8000
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
