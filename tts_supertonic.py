#!/usr/bin/env python3
"""
Supertonic 3 (Supertone) 온디바이스 TTS 나레이션 생성기
- 최초 실행 시 Hugging Face에서 모델(약 수백MB)을 자동 다운로드하므로 인터넷 연결이 필요합니다.
- 이후에는 완전히 로컬(오프라인)에서 음성을 합성합니다.

사용법 (CLI):
    python tts_supertonic.py --text "안녕하세요" --out narration.wav --voice F1 --lang ko

사용법 (모듈):
    from tts_supertonic import synthesize_to_file
    synthesize_to_file("안녕하세요", "narration.wav", voice="F1", lang="ko")
"""

from __future__ import annotations

import argparse
from pathlib import Path

VOICE_STYLES = ["F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5"]

_tts_cache: dict = {}


def is_available() -> bool:
    try:
        import supertonic  # noqa: F401
        return True
    except ImportError:
        return False


def _get_engine(model: str = "supertonic-3"):
    if model not in _tts_cache:
        from supertonic import TTS
        _tts_cache[model] = TTS(model=model)
    return _tts_cache[model]


def synthesize_to_file(
    text: str,
    out_path: str | Path,
    voice: str = "F1",
    lang: str = "ko",
    speed: float = 1.05,
    model: str = "supertonic-3",
) -> Path:
    """텍스트를 음성으로 합성해 out_path(.wav)에 저장하고 경로를 반환한다."""
    if not text or not text.strip():
        raise ValueError("합성할 텍스트가 비어 있습니다.")

    tts = _get_engine(model)
    style = tts.get_voice_style(voice)
    wav, _duration = tts.synthesize(text.strip(), voice_style=style, lang=lang, speed=speed)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tts.save_audio(wav, str(out_path))
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Supertonic 3 로컬 TTS 나레이션 생성")
    parser.add_argument("--text", required=True, help="합성할 텍스트")
    parser.add_argument("--out", required=True, help="출력 wav 경로")
    parser.add_argument("--voice", default="F1", choices=VOICE_STYLES, help="음성 스타일")
    parser.add_argument("--lang", default="ko", help="언어 코드 (예: ko, en, ja)")
    parser.add_argument("--speed", type=float, default=1.05, help="배속")
    args = parser.parse_args()

    path = synthesize_to_file(args.text, args.out, voice=args.voice, lang=args.lang, speed=args.speed)
    print(f"저장 완료: {path}")


if __name__ == "__main__":
    main()
