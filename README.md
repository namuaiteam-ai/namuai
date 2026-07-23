# YouTube Shorts 제작 도구

이미지 · 나레이션 오디오 · 자막을 조합해 ffmpeg 기반 Shorts 영상을 만듭니다.

- CLI: `make_shorts.py` (`run_shorts.bat`으로 실행)
- 웹 UI: `shorts_app.py` (`python shorts_app.py` → http://localhost:5000)

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

### 사용

- 웹 UI(`shorts_app.py`)의 나레이션 섹션에서 **"텍스트 → TTS(로컬)"** 모드를 선택하고 대본을 입력하면
  자동으로 음성이 생성되어 영상 제작에 사용됩니다.
- CLI에서 직접 wav 파일을 만들고 싶다면:

```
python tts_supertonic.py --text "안녕하세요" --out narration.wav --voice F1 --lang ko
```

지원 음성: `F1`~`F5`(여성), `M1`~`M5`(남성). 지원 언어: 한국어(`ko`), 영어(`en`), 일본어(`ja`) 등 31개 언어.
