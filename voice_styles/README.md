# 커스텀 음성 스타일

기본 제공되는 10개 음성(F1~F5, M1~M5)보다 개성 있는 목소리가 필요하면,
Supertone의 [Voice Builder](https://supertonic.supertone.ai/voice-builder)에서
원하는 목소리 샘플을 녹음하거나 업로드해 Supertonic 3용 커스텀 음성 스타일(JSON)을
만들 수 있습니다.

## 사용 방법

1. https://supertonic.supertone.ai/voice-builder 에서 음성 스타일 JSON 파일을 만들고 다운로드합니다.
2. 그 JSON 파일을 이 폴더(`voice_styles/`)에 넣습니다. 예: `voice_styles/my_voice.json`
3. `tts_app.py` / `shorts_app.py`를 (재)실행하면 음성 선택 목록에 `my_voice (커스텀)`로 자동으로 나타납니다.
4. CLI에서 직접 쓰려면: `python tts_supertonic.py --text "..." --out out.wav --voice my_voice`

이 폴더 안의 `*.json` 파일은 개인 음성 데이터라 git에는 커밋되지 않습니다 (`.gitignore` 참고).
