#!/usr/bin/env python3
"""
Whisper 기반 자동 자막 생성기
오디오 파일 → SRT 자막 파일 (한국어 음성 인식)

설치: pip install openai-whisper
모델: base(빠름) / small / medium / large(정확)
"""

import argparse
import sys
from datetime import timedelta
from pathlib import Path


def format_timestamp(seconds: float) -> str:
    """초 단위 → SRT 타임스탬프 (00:00:00,000)"""
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours   = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs    = total_seconds % 60
    millis  = int(td.microseconds / 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(audio_path: str, output_srt_path: str,
                 model_name: str = "base", language: str = "ko",
                 progress_cb=None) -> str:
    try:
        import whisper
    except ImportError:
        sys.exit(
            "[오류] openai-whisper가 설치되어 있지 않습니다.\n"
            "  설치: pip install openai-whisper"
        )

    audio_path = str(audio_path)
    output_srt_path = str(output_srt_path)

    if not Path(audio_path).exists():
        sys.exit(f"[오류] 오디오 파일을 찾을 수 없습니다: {audio_path}")

    if progress_cb:
        progress_cb(0, 3, f"Whisper '{model_name}' 모델 로딩 중...")
    else:
        print(f"[Whisper] '{model_name}' 모델 로딩 중...")

    model = whisper.load_model(model_name)

    if progress_cb:
        progress_cb(1, 3, f"음성 인식 중... ({Path(audio_path).name})")
    else:
        print(f"[Whisper] '{audio_path}' 음성 인식 중... (언어: {language})")

    result = model.transcribe(audio_path, language=language)

    if progress_cb:
        progress_cb(2, 3, "SRT 자막 파일 생성 중...")

    segments = result.get("segments", [])
    if not segments:
        raise RuntimeError("음성 인식 결과가 없습니다. 오디오 파일을 확인해주세요.")

    with open(output_srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            start = format_timestamp(seg["start"])
            end   = format_timestamp(seg["end"])
            text  = seg["text"].strip()
            if not text:
                continue
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

    seg_count = len(segments)
    if progress_cb:
        progress_cb(3, 3, f"자막 생성 완료 ({seg_count}개 구간, {output_srt_path})")
    else:
        print(f"[Whisper] 완료! {seg_count}개 구간 → {output_srt_path}")

    return output_srt_path


def check_whisper() -> bool:
    try:
        import whisper  # noqa
        return True
    except ImportError:
        return False


def main():
    parser = argparse.ArgumentParser(description="Whisper 자동 자막 생성기")
    parser.add_argument("-a", "--audio",    required=True, metavar="AUDIO")
    parser.add_argument("-o", "--output",   metavar="SRT")
    parser.add_argument("-m", "--model",    default="base",
                        choices=["tiny", "base", "small", "medium", "large"])
    parser.add_argument("-l", "--language", default="ko")

    args = parser.parse_args()
    output = args.output or str(Path(args.audio).with_suffix(".srt"))

    generate_srt(
        audio_path=args.audio,
        output_srt_path=output,
        model_name=args.model,
        language=args.language,
    )


if __name__ == "__main__":
    main()
