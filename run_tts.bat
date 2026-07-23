@echo off
chcp 65001 >nul
:: Supertonic 3 로컬 나레이션 생성기 실행 스크립트 (Windows)
:: 실행: run_tts.bat 더블클릭 -> http://localhost:5001 자동으로 열립니다.
:: 영상 제작과 무관한 독립 TTS 도구입니다 (음성 파일만 생성).

cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 goto :no_python

python tts_app.py
pause
exit /b 0

:no_python
echo [오류] Python이 설치되어 있지 않습니다.
echo  설치: https://www.python.org/downloads/
pause
exit /b 1
