# YouTube Shorts 제작 도구

이미지 · 나레이션 오디오 · 자막을 조합해 ffmpeg 기반 Shorts 영상을 만듭니다.

- CLI: `make_shorts.py` (`run_shorts.bat`으로 실행)
- 웹 UI: `shorts_app.py` (`run_app.bat` 더블클릭, 또는 `python shorts_app.py` → http://localhost:5000)

## 로컬 TTS (Supertonic 3)

나레이션 오디오 파일이 없어도, 대본 텍스트만 입력하면 [Supertonic 3](https://github.com/supertone-inc/supertonic)
(Supertone사의 온디바이스 TTS)로 로컬에서 직접 음성을 합성할 수 있습니다. 클라우드 API를 호출하지 않고
내 PC에서만 처리되며, 최초 1회 모델(약 수백MB)을 Hugging Face에서 내려받은 뒤에는 오프라인으로 동작합니다.

### 설치

```
install_tts.bat
```

또는 수동으로:

```
pip install -r requirements.txt
```

### 사용 (영상 제작과 무관하게 나레이션 wav만 필요할 때)

`run_tts.bat` 더블클릭 (또는 `python tts_app.py`) → http://localhost:5001 에서
대본을 입력하고 음성 생성 버튼을 누르면 wav 파일을 바로 듣고 다운로드할 수 있습니다.
영상 제작 기능과는 완전히 분리된 독립 도구입니다.

**자막(.srt)도 함께 생성됩니다.** 대본에서 줄바꿈된 한 줄이 자막 한 줄이 되고, 그 줄을 실제로
합성한 음성 길이에 맞춰 타이밍이 자동 계산됩니다 (줄바꿈이 없으면 문장 부호 기준으로 자동 분리).
생성된 srt는 `shorts_app.py`의 자막 업로드에 그대로 쓸 수 있습니다.

CLI로 직접 만들고 싶다면:

```
python tts_supertonic.py --text "안녕하세요" --out narration.wav --voice F1 --lang ko

:: 자막도 함께 (대본에 줄바꿈으로 자막 줄 구분)
python tts_supertonic.py --text "첫 줄입니다.
둘째 줄입니다." --out narration.wav --srt-out narration.srt --voice F1 --lang ko
```

지원 음성: `F1`~`F5`(여성), `M1`~`M5`(남성). 지원 언어: 한국어(`ko`), 영어(`en`), 일본어(`ja`) 등 31개 언어.

### 더 개성 있는 목소리 (커스텀 음성)

기본 10개 음성이 밋밋하게 느껴진다면, Supertone의 [Voice Builder](https://supertonic.supertone.ai/voice-builder)에서
원하는 목소리를 녹음/업로드해 커스텀 음성 스타일(JSON)을 만든 뒤 `voice_styles/` 폴더에 넣으세요.
자세한 방법은 `voice_styles/README.md` 참고. 넣고 나면 `tts_app.py`/`shorts_app.py`의 음성 선택 목록에
자동으로 추가됩니다.

### 영상 제작 툴과 연동해서 쓰고 싶다면

웹 UI(`shorts_app.py`)의 나레이션 섹션에서도 **"텍스트 → TTS(로컬)"** 모드를 선택하면
같은 엔진으로 생성한 음성이 영상 제작에 바로 쓰입니다 (선택 사항).
