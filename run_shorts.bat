@echo off
chcp 65001 >nul
:: YouTube Shorts 제작 실행 스크립트 (Windows)
:: 경로: C:\이지뉴스\

cd /d "%~dp0"

echo ============================================================
echo  YouTube Shorts 제작 도구
echo ============================================================
echo.

:: Python 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo  설치: https://www.python.org/downloads/
    pause & exit /b 1
)

:: ffmpeg 확인
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [오류] ffmpeg가 설치되어 있지 않습니다.
    echo  설치: https://ffmpeg.org/download.html
    echo  또는: winget install ffmpeg
    pause & exit /b 1
)

:: 사용 예시 출력
echo [사용법]
echo   python make_shorts.py -i 이미지1.jpg 이미지2.jpg 이미지3.jpg ^
echo       -a 나레이션.mp3 -s 자막.srt -o 출력영상.mp4
echo.
echo [옵션]
echo   --duration    사진 표시 시간 (초, 기본 4)
echo   --transition  전환 효과 길이 (초, 기본 0.6)
echo   --crf         화질 (18=최고화질 ~ 28=저화질, 기본 23)
echo   --thumbnail   썸네일 추출 경로
echo   --dump-config 현재 설정을 settings.json 저장
echo.

:: 인자가 없으면 대화형 모드
if "%~1"=="" (
    echo [대화형 모드]
    set /p IMAGES="이미지 파일명 (공백 구분, 최대 6장): "
    set /p AUDIO="나레이션 파일명 (없으면 Enter): "
    set /p SUBTITLE="자막 파일명 (없으면 Enter): "
    set /p OUTPUT="출력 파일명 (기본: shorts_output.mp4): "

    if "!OUTPUT!"=="" set OUTPUT=shorts_output.mp4

    set CMD=python make_shorts.py -i !IMAGES!
    if not "!AUDIO!"==""    set CMD=!CMD! -a !AUDIO!
    if not "!SUBTITLE!"=="" set CMD=!CMD! -s !SUBTITLE!
    set CMD=!CMD! -o !OUTPUT!

    echo.
    echo 실행: !CMD!
    echo.
    !CMD!
) else (
    python make_shorts.py %*
)

echo.
if errorlevel 1 (
    echo [실패] 오류가 발생했습니다. 위 메시지를 확인하세요.
) else (
    echo [완료] 영상 제작이 완료되었습니다.
)
pause
