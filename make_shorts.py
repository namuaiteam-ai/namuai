#!/usr/bin/env python3
"""
YouTube Shorts 영상 제작 스크립트
- 이미지 최대 6장 + 나레이션 오디오 + 자막(SRT/VTT/ASS) → MP4 (720×1280)
- Ken Burns 줌 효과, 페이드 전환, 흐르는 자막 (좌→우)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


# ─── 기본 설정 ────────────────────────────────────────────────────────────────
DEFAULTS = {
    "width": 720,
    "height": 1280,
    "fps": 30,
    "photo_duration": 4.0,       # 사진 표시 시간 (초)
    "transition": 0.6,           # 전환 효과 길이 (초)
    "zoom_ratio": 0.04,          # Ken Burns 줌 비율 (0.04 = 4% 확대)
    "crf": 23,                   # H.264 품질 (낮을수록 고화질, 18~28 권장)
    "audio_norm": True,          # 오디오 정규화 여부
}

SUBTITLE_STYLE = {
    "fontname": "NanumGothic",
    "fontsize": 22,
    "primary_color": "&H00FFFFFF",   # 흰색
    "outline_color": "&H00000000",   # 검정 외곽선
    "back_color": "&H80000000",      # 반투명 배경
    "bold": 1,
    "outline": 2,
    "shadow": 0,
    "margin_v": 60,                  # 하단 여백
    "scroll_speed": 80,              # 흐르는 자막 속도 (px/s)
}


# ─── ffmpeg 유틸 ──────────────────────────────────────────────────────────────
def run(cmd: list[str], desc: str = "") -> subprocess.CompletedProcess:
    """ffmpeg 명령 실행 + 오류 출력"""
    print(f"\n{'='*60}")
    if desc:
        print(f"[단계] {desc}")
    print("$ " + " ".join(cmd))
    print("=" * 60)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("[오류] stderr:\n", result.stderr[-3000:])
        raise RuntimeError(f"ffmpeg 실패 (code {result.returncode}): {desc}")
    return result


def check_ffmpeg():
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True)
        assert r.returncode == 0
    except (FileNotFoundError, AssertionError):
        sys.exit("[오류] ffmpeg가 설치되어 있지 않습니다.\n  설치: sudo apt install ffmpeg  또는  brew install ffmpeg")


def check_file(path: str, label: str) -> Path:
    p = Path(path)
    if not p.exists():
        sys.exit(f"[오류] {label} 파일을 찾을 수 없습니다: {path}")
    return p


# ─── Ken Burns 필터 생성 ──────────────────────────────────────────────────────
def ken_burns_filter(index: int, w: int, h: int, duration: float,
                     fps: int, zoom: float) -> str:
    """
    짝수 인덱스 → 줌인(중앙 확대), 홀수 인덱스 → 줌아웃(외곽 → 중앙)
    zoompan 필터: z=줌배율, x/y=팬 좌표
    """
    total_frames = int(duration * fps)
    z_start = 1.0
    z_end = 1.0 + zoom

    if index % 2 == 0:
        # 줌인: 1.0 → 1+zoom (중앙 고정)
        z_expr = f"'min(zoom+{zoom / total_frames:.6f},{z_end})'"
        x_expr = f"'iw/2-(iw/zoom/2)'"
        y_expr = f"'ih/2-(ih/zoom/2)'"
    else:
        # 줌아웃: 1+zoom → 1.0 (중앙 고정)
        z_expr = f"'max(zoom-{zoom / total_frames:.6f},{z_start})'"
        x_expr = f"'iw/2-(iw/zoom/2)'"
        y_expr = f"'ih/2-(ih/zoom/2)'"

    return (
        f"scale={w * 2}:{h * 2},"
        f"zoompan=z={z_expr}:x={x_expr}:y={y_expr}"
        f":d={total_frames}:s={w}x{h}:fps={fps},"
        f"setsar=1"
    )


# ─── 페이드 전환 전처리 ───────────────────────────────────────────────────────
def fade_filter(duration: float, transition: float, fps: int) -> str:
    """각 클립 앞뒤에 페이드 인/아웃 추가"""
    fade_frames = int(transition * fps / 2)
    total_frames = int(duration * fps)
    fade_out_start = total_frames - fade_frames
    return (
        f"fade=t=in:st=0:nb_frames={fade_frames},"
        f"fade=t=out:st={fade_out_start}:nb_frames={fade_frames}"
    )


# ─── 개별 이미지 클립 생성 ────────────────────────────────────────────────────
def make_clip(img_path: Path, index: int, out_path: Path, cfg: dict) -> Path:
    """이미지 1장 → Ken Burns + 페이드 → 임시 클립 파일"""
    w, h = cfg["width"], cfg["height"]
    fps = cfg["fps"]
    dur = cfg["photo_duration"]
    zoom = cfg["zoom_ratio"]
    trans = cfg["transition"]

    kb = ken_burns_filter(index, w, h, dur, fps, zoom)
    fade = fade_filter(dur, trans, fps)

    vf = (
        f"format=yuv420p,"
        f"scale='if(gt(iw/ih,{w}/{h}),{w},-2)':'if(gt(iw/ih,{w}/{h}),-2,{h})',"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"{kb},"
        f"{fade}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(img_path),
        "-vf", vf,
        "-t", str(dur),
        "-r", str(fps),
        "-an",
        "-c:v", "libx264", "-preset", "fast",
        "-crf", str(cfg["crf"]),
        str(out_path),
    ]
    run(cmd, f"클립 {index + 1} 생성: {img_path.name}")
    return out_path


# ─── 클립 연결 ────────────────────────────────────────────────────────────────
def concat_clips(clip_paths: list[Path], out_path: Path) -> Path:
    """concat demuxer로 클립 연결"""
    list_file = out_path.parent / "concat_list.txt"
    with open(list_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy",
        str(out_path),
    ]
    run(cmd, "클립 연결")
    return out_path


# ─── 오디오 합성 ──────────────────────────────────────────────────────────────
def merge_audio(video_path: Path, audio_path: Path,
                out_path: Path, normalize: bool) -> Path:
    """나레이션 오디오 합성 (영상 길이에 맞춰 자름/패딩)"""
    audio_filter = "apad" if normalize else "apad"
    if normalize:
        audio_filter = "loudnorm=I=-16:TP=-1.5:LRA=11,apad"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-filter_complex",
        f"[1:a]{audio_filter}[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-shortest",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ]
    run(cmd, "오디오 합성")
    return out_path


# ─── 자막 합성 ────────────────────────────────────────────────────────────────
def add_subtitles(video_path: Path, sub_path: Path,
                  out_path: Path, cfg: dict) -> Path:
    """
    SRT/VTT → ASS 변환 후 burn-in (하드코딩)
    ASS 파일은 그대로 사용
    흐르는 자막(Marquee)은 ASS ScriptInfo에서 처리
    """
    ext = sub_path.suffix.lower()
    style = SUBTITLE_STYLE

    if ext in (".srt", ".vtt"):
        # SRT/VTT → ASS 변환 (ffmpeg 내장 컨버터)
        ass_path = out_path.parent / (sub_path.stem + "_conv.ass")
        run(
            ["ffmpeg", "-y", "-i", str(sub_path), str(ass_path)],
            "자막 형식 변환 (→ ASS)"
        )
        sub_path = ass_path

    # ASS 스타일 덮어쓰기
    _patch_ass_style(sub_path, style, cfg)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"ass={sub_path}",
        "-c:v", "libx264", "-preset", "fast",
        "-crf", str(cfg["crf"]),
        "-c:a", "copy",
        str(out_path),
    ]
    run(cmd, "자막 합성")
    return out_path


def _patch_ass_style(ass_path: Path, style: dict, cfg: dict):
    """ASS Style 라인을 원하는 스타일로 교체 + 흐르는 자막 이벤트 처리"""
    text = ass_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    new_lines = []
    in_styles = False

    for line in lines:
        if line.strip().startswith("[V4+ Styles]"):
            in_styles = True
            new_lines.append(line)
            continue
        if in_styles and line.strip().startswith("Style:"):
            # 기본 스타일 교체
            new_lines.append(
                f"Style: Default,"
                f"{style['fontname']},{style['fontsize']},"
                f"{style['primary_color']},{style['outline_color']},"
                f"{style['back_color']},&H00000000,"
                f"{style['bold']},0,0,0,"
                f"100,100,0,0,1,"
                f"{style['outline']},{style['shadow']},"
                f"2,10,10,{style['margin_v']},1"
            )
            continue
        if line.strip().startswith("[") and in_styles:
            in_styles = False
        new_lines.append(line)

    ass_path.write_text("\n".join(new_lines), encoding="utf-8")


# ─── 메인 파이프라인 ──────────────────────────────────────────────────────────
def build_shorts(images: list[str], audio: str | None,
                 subtitle: str | None, output: str,
                 cfg: dict, thumbnail: str | None = None):

    check_ffmpeg()

    img_paths = []
    for i, img in enumerate(images[:6]):
        img_paths.append(check_file(img, f"이미지 {i+1}"))

    audio_path = check_file(audio, "오디오") if audio else None
    sub_path = check_file(subtitle, "자막") if subtitle else None
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n[설정]")
    print(f"  이미지 {len(img_paths)}장 / 오디오: {'있음' if audio_path else '없음'} "
          f"/ 자막: {'있음' if sub_path else '없음'}")
    print(f"  해상도: {cfg['width']}x{cfg['height']} / fps: {cfg['fps']}")
    print(f"  사진 표시: {cfg['photo_duration']}초 / 전환: {cfg['transition']}초")
    print(f"  효과: Ken Burns 줌 / 출력: {out_path}")

    with tempfile.TemporaryDirectory(prefix="shorts_") as tmpdir:
        tmp = Path(tmpdir)

        # 1단계: 개별 클립 생성
        clip_paths = []
        for i, img in enumerate(img_paths):
            clip = tmp / f"clip_{i:02d}.mp4"
            make_clip(img, i, clip, cfg)
            clip_paths.append(clip)

        # 2단계: 클립 연결
        merged = tmp / "merged.mp4"
        concat_clips(clip_paths, merged)

        # 3단계: 오디오 합성
        if audio_path:
            with_audio = tmp / "with_audio.mp4"
            merge_audio(merged, audio_path, with_audio, cfg["audio_norm"])
            current = with_audio
        else:
            current = merged

        # 4단계: 자막 합성
        if sub_path:
            with_sub = tmp / "with_sub.mp4"
            add_subtitles(current, sub_path, with_sub, cfg)
            current = with_sub

        # 5단계: 최종 출력 (재인코딩 없이 복사 또는 최적화)
        cmd_final = [
            "ffmpeg", "-y",
            "-i", str(current),
            "-c:v", "libx264", "-preset", "slow",
            "-crf", str(cfg["crf"]),
            "-profile:v", "high", "-level", "4.0",
            "-movflags", "+faststart",        # 유튜브 스트리밍 최적화
            "-c:a", "aac", "-b:a", "192k",
            "-ar", "44100",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]
        run(cmd_final, "최종 출력 파일 생성")

    size_mb = out_path.stat().st_size / 1024 / 1024
    total_sec = len(img_paths) * cfg["photo_duration"]
    print(f"\n✅ 완료!")
    print(f"  출력 파일: {out_path}")
    print(f"  파일 크기: {size_mb:.1f} MB")
    print(f"  영상 길이: 약 {total_sec:.1f}초")

    if thumbnail:
        _extract_thumbnail(out_path, Path(thumbnail))


def _extract_thumbnail(video: Path, thumb: Path):
    """영상 첫 프레임을 썸네일로 추출"""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-ss", "0.5",
        "-vframes", "1",
        "-vf", "scale=1280:720",
        str(thumb),
    ]
    run(cmd, "썸네일 생성")
    print(f"  썸네일: {thumb}")


# ─── CLI ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="YouTube Shorts 자동 제작 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 기본 (이미지 3장, 오디오, 자막)
  python make_shorts.py -i img1.jpg img2.jpg img3.jpg \\
      -a narration.mp3 -s subtitle.srt -o output.mp4

  # 설정 파일 사용
  python make_shorts.py --config settings.json

  # 옵션 오버라이드
  python make_shorts.py -i *.jpg -a audio.mp3 -o out.mp4 \\
      --duration 5 --transition 0.8 --crf 20
        """
    )

    parser.add_argument("-i", "--images", nargs="+", metavar="IMG",
                        help="이미지 파일 (최대 6장, JPG/PNG/WEBP)")
    parser.add_argument("-a", "--audio", metavar="AUDIO",
                        help="나레이션 오디오 파일 (MP3/WAV/M4A/AAC)")
    parser.add_argument("-s", "--subtitle", metavar="SUB",
                        help="자막 파일 (SRT/VTT/ASS)")
    parser.add_argument("-o", "--output", default="shorts_output.mp4",
                        help="출력 MP4 파일 경로 (기본: shorts_output.mp4)")
    parser.add_argument("--thumbnail", metavar="THUMB",
                        help="썸네일 추출 경로 (JPG/PNG, 1280×720)")
    parser.add_argument("--config", metavar="JSON",
                        help="설정 파일 (JSON)")
    parser.add_argument("--duration", type=float,
                        help=f"사진 표시 시간 (초, 기본: {DEFAULTS['photo_duration']})")
    parser.add_argument("--transition", type=float,
                        help=f"전환 효과 길이 (초, 기본: {DEFAULTS['transition']})")
    parser.add_argument("--width", type=int,
                        help=f"출력 너비 (기본: {DEFAULTS['width']})")
    parser.add_argument("--height", type=int,
                        help=f"출력 높이 (기본: {DEFAULTS['height']})")
    parser.add_argument("--fps", type=int,
                        help=f"프레임레이트 (기본: {DEFAULTS['fps']})")
    parser.add_argument("--crf", type=int,
                        help=f"H.264 품질 CRF (기본: {DEFAULTS['crf']}, 낮을수록 고화질)")
    parser.add_argument("--no-normalize", action="store_true",
                        help="오디오 정규화 비활성화")
    parser.add_argument("--dump-config", action="store_true",
                        help="현재 설정을 settings.json으로 저장")

    args = parser.parse_args()

    # 설정 병합 (기본값 → JSON → CLI)
    cfg = dict(DEFAULTS)

    if args.config:
        with open(args.config) as f:
            cfg.update(json.load(f))

    if args.duration:   cfg["photo_duration"] = args.duration
    if args.transition: cfg["transition"] = args.transition
    if args.width:      cfg["width"] = args.width
    if args.height:     cfg["height"] = args.height
    if args.fps:        cfg["fps"] = args.fps
    if args.crf:        cfg["crf"] = args.crf
    if args.no_normalize: cfg["audio_norm"] = False

    if args.dump_config:
        with open("settings.json", "w") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        print("설정 저장: settings.json")

    if not args.images:
        parser.error("이미지 파일을 1장 이상 지정해주세요 (-i 옵션)")

    build_shorts(
        images=args.images,
        audio=args.audio,
        subtitle=args.subtitle,
        output=args.output,
        cfg=cfg,
        thumbnail=args.thumbnail,
    )


if __name__ == "__main__":
    main()
