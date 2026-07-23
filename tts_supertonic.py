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
import re
from pathlib import Path

VOICE_STYLES = ["F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5"]

CUSTOM_VOICE_DIR = Path("voice_styles")

_tts_cache: dict = {}


def list_custom_voices() -> list[str]:
    """voice_styles/ 폴더에 있는 커스텀 음성 스타일(json) 파일명 목록을 반환한다."""
    if not CUSTOM_VOICE_DIR.is_dir():
        return []
    return sorted(p.stem for p in CUSTOM_VOICE_DIR.glob("*.json"))


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


def _get_voice_style(tts, voice: str):
    custom_path = CUSTOM_VOICE_DIR / f"{voice}.json"
    if custom_path.is_file():
        return tts.get_voice_style_from_path(custom_path)
    return tts.get_voice_style(voice)


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
    style = _get_voice_style(tts, voice)
    wav, _duration = tts.synthesize(text.strip(), voice_style=style, lang=lang, speed=speed)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tts.save_audio(wav, str(out_path))
    return out_path


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def synthesize_with_srt(
    lines: list[str],
    out_audio_path: str | Path,
    out_srt_path: str | Path,
    voice: str = "F1",
    lang: str = "ko",
    speed: float = 1.05,
    gap_seconds: float = 0.3,
    model: str = "supertonic-3",
) -> tuple[Path, Path]:
    """줄 단위 대본을 한 줄씩 합성해 이어붙이고, 각 줄의 실제 길이에 맞춘 SRT 자막을 함께 생성한다."""
    import numpy as np

    lines = [line.strip() for line in lines if line.strip()]
    if not lines:
        raise ValueError("합성할 텍스트가 비어 있습니다.")

    tts = _get_engine(model)
    style = _get_voice_style(tts, voice)

    gap = np.zeros((1, int(gap_seconds * tts.sample_rate)), dtype=np.float32)

    chunks = []
    srt_entries = []
    cursor = 0.0
    for i, line in enumerate(lines):
        wav, duration = tts.synthesize(line, voice_style=style, lang=lang, speed=speed)
        dur = float(np.asarray(duration).reshape(-1)[0])

        start, end = cursor, cursor + dur
        srt_entries.append((i + 1, start, end, line))
        cursor = end + gap_seconds

        chunks.append(wav)
        if i < len(lines) - 1:
            chunks.append(gap)

    combined = np.concatenate(chunks, axis=1)

    out_audio_path = Path(out_audio_path)
    out_audio_path.parent.mkdir(parents=True, exist_ok=True)
    tts.save_audio(combined, str(out_audio_path))

    out_srt_path = Path(out_srt_path)
    out_srt_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_srt_path, "w", encoding="utf-8") as f:
        for idx, start, end, line in srt_entries:
            f.write(f"{idx}\n")
            f.write(f"{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}\n")
            f.write(f"{line}\n\n")

    return out_audio_path, out_srt_path


def split_script_lines(text: str) -> list[str]:
    """대본 텍스트를 자막 한 줄 단위로 분리한다: 줄바꿈 우선, 없으면 문장 부호 기준."""
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(raw_lines) > 1:
        return raw_lines
    # 줄바꿈이 없는 한 덩어리 텍스트면 문장 단위로 나눈다.
    sentences = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip()]


def main():
    parser = argparse.ArgumentParser(description="Supertonic 3 로컬 TTS 나레이션 생성")
    parser.add_argument("--text", required=True, help="합성할 텍스트 (줄바꿈으로 자막 줄 구분 가능)")
    parser.add_argument("--out", required=True, help="출력 wav 경로")
    parser.add_argument("--srt-out", help="함께 생성할 SRT 자막 경로 (지정하면 줄 단위로 나눠 합성)")
    parser.add_argument("--voice", default="F1",
                        help=f"음성 스타일. 내장: {', '.join(VOICE_STYLES)}. "
                             f"또는 voice_styles/<이름>.json 커스텀 음성 이름")
    parser.add_argument("--lang", default="ko", help="언어 코드 (예: ko, en, ja)")
    parser.add_argument("--speed", type=float, default=1.05, help="배속")
    args = parser.parse_args()

    if args.srt_out:
        lines = split_script_lines(args.text)
        audio_path, srt_path = synthesize_with_srt(
            lines, args.out, args.srt_out, voice=args.voice, lang=args.lang, speed=args.speed)
        print(f"저장 완료: {audio_path}, {srt_path}")
    else:
        path = synthesize_to_file(args.text, args.out, voice=args.voice, lang=args.lang, speed=args.speed)
        print(f"저장 완료: {path}")


if __name__ == "__main__":
    main()
