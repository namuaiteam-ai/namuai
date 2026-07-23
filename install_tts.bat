@echo off
chcp 65001 >nul
:: Supertonic 3 로컬 TTS 설치 스크립트 (Windows)
:: 최초 설치 후 shorts_app.py 실행 시 텍스트-TTS(로컬) 모드를 사용할 수 있습니다.
:: 첫 실행 시 Hugging Face에서 모델(약 수백MB)을 자동으로 내려받으므로 인터넷 연결이 필요합니다.

cd /d "%~dp0"

echo ============================================================
echo  Supertonic 3 로컬 TTS 설치
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 goto :no_python

echo [1/2] 의존성 설치 (pip install supertonic) ...
python -m pip install --upgrade supertonic
if errorlevel 1 goto :pip_fail

echo.
echo [2/2] 모델 다운로드 및 동작 확인 (최초 1회, 인터넷 필요) ...
python tts_supertonic.py --text "안녕하세요 로컬 TTS 설치가 완료되었습니다" --out install_tts_test.wav --voice F1 --lang ko
if errorlevel 1 goto :tts_fail

echo.
echo [완료] install_tts_test.wav 파일을 재생해 음성을 확인해보세요.
echo  이후 shorts_app.py 실행 후 텍스트-TTS(로컬) 모드로 대본을 입력하면
echo  나레이션 오디오가 로컬에서 자동 생성됩니다.
pause
exit /b 0

:no_python
echo [오류] Python이 설치되어 있지 않습니다.
echo  설치: https://www.python.org/downloads/
pause
exit /b 1

:pip_fail
echo [오류] supertonic 설치에 실패했습니다. 위 pip 오류 메시지를 확인하세요.
pause
exit /b 1

:tts_fail
echo [오류] 모델 다운로드 또는 음성 합성에 실패했습니다. 인터넷 연결을 확인하세요.
pause
exit /b 1
