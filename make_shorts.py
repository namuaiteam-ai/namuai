#!/usr/bin/env python3
"""
YouTube Shorts 영상 제작 스크립트
- 이미지 최대 6장 + 나레이션 오디오 + 자막(SRT/VTT/ASS) → MP4 (720×1280)
- 6가지 움직임 효과: Ken Burns, Pan, Tilt, Zoom In, Zoom Out, Shake
- 오디오 길이 기반 영상 길이 결정 (오디오-자막-영상 완전 동기화)
- 자막 2줄 표시 (SRT 자동 파싱 및 2개씩 묶음)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


# ─── 기본 설정 ────────────────────────────────────────────────────────────────
DEFAULTS = {
    "width": 720,
    "height": 1280,
    "fps": 30,
    "photo_duration": 4.0,
    "transition": 0.6,
    "zoom_ratio": 0.04,
    "crf": 23,
    "audio_norm": True,
    "effect": "ken_burns",        # ken_burns | pan | tilt | zoom_in | zoom_out | shake
    "subtitle_font": "Arial",
    "subtitle_size": 22,
    "subtitle_color": "&H00FFFFFF",
    "subtitle_outline": "&H00000000",
    "subtitle_bg": "&H80000000",
    "subtitle_bold": 1,
    "subtitle_margin_v": 60,
}

SUBTITLE_STYLE = {
    "fontname": "Arial",
    "fontsize": 22,
    "primary_color": "&H00FFFFFF",
    "outline_color": "&H00000000",
    "back_color": "&H80000000",
    "bold": 1,
    "outline": 2,
    "shadow": 0,
    "margin_v": 60,
}


# ─── ffmpeg 유틸 ──────────────────────────────────────────────────────────────
def run(cmd: list[str], desc: str = "",
        progress_cb=None, step: int = 0, total_steps: int = 1) -> subprocess.CompletedProcess:
    if progress_cb:
        progress_cb(step, total_steps, f"[{desc}] 처리 중...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 오류 [{desc}]:\n{result.stderr[-2000:]}")
    return result


def check_ffmpeg():
    import shutil
    import platform

    if platform.system() == "Windows":
        extra_paths = [
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
            os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin"),
        ]
        for p in extra_paths:
            if os.path.isfile(os.path.join(p, "ffmpeg.exe")):
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
                break

    if shutil.which("ffmpeg") is None:
        if platform.system() == "Windows":
            sys.exit(
                "[오류] ffmpeg를 찾을 수 없습니다.\n"
                "  1) CMD/PowerShell 창을 닫고 새로 여세요 (PATH 갱신)\n"
                "  2) 또는 설치: winget install ffmpeg"
            )
        else:
            sys.exit("[오류] ffmpeg가 설치되어 있지 않습니다.\n  설치: sudo apt install ffmpeg")


def check_file(path: str, label: str) -> Path:
    p = Path(path)
    if not p.exists():
        sys.exit(f"[오류] {label} 파일을 찾을 수 없습니다: {path}")
    return p


def get_media_duration(path: Path) -> float:
    """ffprobe로 미디어 파일 길이(초) 반환"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 오류: {result.stderr}")
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


# ─── SRT 파싱 및 2줄 묶음 ─────────────────────────────────────────────────────
def _ms(ts: str) -> int:
    """SRT 타임스탬프 → 밀리초 (00:00:00,000)"""
    h, m, rest = ts.strip().replace(".", ",").split(":")
    s, ms = rest.split(",")
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)


def _ts(ms: int) -> str:
    """밀리초 → SRT 타임스탬프"""
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms_ = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms_:03d}"


def parse_srt(path: Path) -> list[dict]:
    """SRT → [{index, start_ms, end_ms, text}, ...]"""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    # 블록 단위 분리
    blocks = re.split(r"\n{2,}", text.strip())
    cues = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        # 첫 줄이 숫자이면 인덱스
        offset = 0
        if lines[0].strip().isdigit():
            offset = 1
        if len(lines) <= offset:
            continue
        tc_line = lines[offset]
        m = re.match(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
            tc_line,
        )
        if not m:
            continue
        text_lines = "\n".join(lines[offset + 1:]).strip()
        # HTML 태그 제거
        text_lines = re.sub(r"<[^>]+>", "", text_lines)
        cues.append({
            "start_ms": _ms(m.group(1)),
            "end_ms":   _ms(m.group(2)),
            "text":     text_lines,
        })
    return cues


def group_srt_2lines(cues: list[dict]) -> str:
    """
    SRT 큐를 2개씩 묶어 2줄 자막 SRT 생성.
    - 시작: 첫 번째 큐의 start
    - 종료: 두 번째 큐의 end (홀수 마지막은 단독)
    """
    result_blocks = []
    idx = 1
    i = 0
    while i < len(cues):
        pair = cues[i:i + 2]
        start = pair[0]["start_ms"]
        end   = pair[-1]["end_ms"]
        # 두 줄 합치기 (이미 2줄인 큐는 그대로)
        combined = "\n".join(c["text"] for c in pair)
        result_blocks.append(f"{idx}\n{_ts(start)} --> {_ts(end)}\n{combined}")
        idx += 1
        i += 2
    return "\n\n".join(result_blocks) + "\n"


# ─── 움직임 효과 필터 ─────────────────────────────────────────────────────────
def get_motion_filter(effect: str, index: int, w: int, h: int,
                      duration: float, fps: int, zoom: float) -> str:
    total_frames = int(duration * fps)
    scale = f"scale={w * 2}:{h * 2},"
    out = f":d={total_frames}:s={w}x{h}:fps={fps},setsar=1"

    if effect == "pan":
        # 좌→우 / 우→좌 교대
        sign = 1 if index % 2 == 0 else -1
        step = max(1, int(w * 0.1 / total_frames))
        x = f"'max(0,min(iw-iw/zoom,x+{sign * step}))'"
        return f"{scale}zoompan=z='1.12':x={x}:y='ih/2-(ih/zoom/2)'{out}"

    elif effect == "tilt":
        # 위→아래 / 아래→위 교대
        sign = 1 if index % 2 == 0 else -1
        step = max(1, int(h * 0.1 / total_frames))
        y = f"'max(0,min(ih-ih/zoom,y+{sign * step}))'"
        return f"{scale}zoompan=z='1.12':x='iw/2-(iw/zoom/2)':y={y}{out}"

    elif effect == "zoom_in":
        z_inc = zoom * 2 / total_frames
        z_end = 1.0 + zoom * 2
        return (f"{scale}zoompan=z='min(zoom+{z_inc:.6f},{z_end})'"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'{out}")

    elif effect == "zoom_out":
        z_dec = zoom * 2 / total_frames
        z_start = 1.0 + zoom * 2
        return (f"{scale}zoompan=z='if(eq(on,1),{z_start},max(zoom-{z_dec:.6f},1.0))'"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'{out}")

    elif effect == "shake":
        return (f"{scale}zoompan=z='1.06'"
                f":x='iw/2-(iw/zoom/2)+sin(on*0.9)*12'"
                f":y='ih/2-(ih/zoom/2)+cos(on*1.3)*8'{out}")

    else:  # ken_burns (기본)
        z_end = 1.0 + zoom
        if index % 2 == 0:
            z_expr = f"'min(zoom+{zoom / total_frames:.6f},{z_end})'"
        else:
            z_expr = f"'max(zoom-{zoom / total_frames:.6f},1.0)'"
        return (f"{scale}zoompan=z={z_expr}"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'{out}")


def fade_filter(duration: float, transition: float, fps: int) -> str:
    fade_frames = max(1, int(transition * fps / 2))
    total_frames = int(duration * fps)
    fade_out_start = total_frames - fade_frames
    return (f"fade=t=in:st=0:nb_frames={fade_frames},"
            f"fade=t=out:st={fade_out_start}:nb_frames={fade_frames}")


# ─── 클립 생성 ────────────────────────────────────────────────────────────────
def make_clip(img_path: Path, index: int, out_path: Path, cfg: dict,
              progress_cb=None, step: int = 0, total_steps: int = 1) -> Path:
    w, h = cfg["width"], cfg["height"]
    fps, dur = cfg["fps"], cfg["photo_duration"]
    motion = get_motion_filter(cfg.get("effect", "ken_burns"),
                               index, w, h, dur, fps, cfg["zoom_ratio"])
    fade = fade_filter(dur, cfg["transition"], fps)

    vf = (f"format=yuv420p,"
          f"scale='if(gt(iw/ih,{w}/{h}),{w},-2)':'if(gt(iw/ih,{w}/{h}),-2,{h})',"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
          f"{motion},{fade}")

    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(img_path),
           "-vf", vf, "-t", str(dur), "-r", str(fps), "-an",
           "-c:v", "libx264", "-preset", "fast", "-crf", str(cfg["crf"]),
           str(out_path)]
    run(cmd, f"클립 {index + 1}/{cfg.get('_total', '?')} 생성",
        progress_cb, step, total_steps)
    return out_path


def concat_clips(clip_paths: list[Path], out_path: Path,
                 progress_cb=None, step=0, total_steps=1) -> Path:
    list_file = out_path.parent / "concat_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            f.write(f"file '{str(p.resolve()).replace(chr(92), '/')}'\n")

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
           "-i", str(list_file), "-c", "copy", str(out_path)]
    run(cmd, "클립 연결", progress_cb, step, total_steps)
    return out_path


def merge_audio(video_path: Path, audio_path: Path, out_path: Path,
                normalize: bool, progress_cb=None, step=0, total_steps=1) -> Path:
    af = "loudnorm=I=-16:TP=-1.5:LRA=11,apad" if normalize else "apad"
    cmd = ["ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path),
           "-filter_complex", f"[1:a]{af}[a]",
           "-map", "0:v", "-map", "[a]", "-shortest",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out_path)]
    run(cmd, "오디오 합성", progress_cb, step, total_steps)
    return out_path


def add_subtitles(video_path: Path, sub_path: Path, out_path: Path,
                  cfg: dict, progress_cb=None, step=0, total_steps=1) -> Path:
    ext = sub_path.suffix.lower()
    style = {
        "fontname":      cfg.get("subtitle_font", SUBTITLE_STYLE["fontname"]),
        "fontsize":      cfg.get("subtitle_size", SUBTITLE_STYLE["fontsize"]),
        "primary_color": cfg.get("subtitle_color", SUBTITLE_STYLE["primary_color"]),
        "outline_color": cfg.get("subtitle_outline", SUBTITLE_STYLE["outline_color"]),
        "back_color":    cfg.get("subtitle_bg", SUBTITLE_STYLE["back_color"]),
        "bold":          cfg.get("subtitle_bold", SUBTITLE_STYLE["bold"]),
        "outline": 2, "shadow": 0,
        "margin_v":      cfg.get("subtitle_margin_v", SUBTITLE_STYLE["margin_v"]),
    }

    if ext in (".srt", ".vtt"):
        ass_path = out_path.parent / (sub_path.stem + "_conv.ass")
        run(["ffmpeg", "-y", "-i", str(sub_path), str(ass_path)],
            "자막 변환", progress_cb, step, total_steps)
        sub_path = ass_path

    _patch_ass_style(sub_path, style)

    # Windows path: forward slash for ffmpeg -vf
    sub_str = str(sub_path).replace("\\", "/").replace(":", "\\:")
    cmd = ["ffmpeg", "-y", "-i", str(video_path),
           "-vf", f"ass='{sub_str}'",
           "-c:v", "libx264", "-preset", "fast", "-crf", str(cfg["crf"]),
           "-c:a", "copy", str(out_path)]
    run(cmd, "자막 합성", progress_cb, step, total_steps)
    return out_path


def _patch_ass_style(ass_path: Path, style: dict):
    text = ass_path.read_text(encoding="utf-8", errors="replace")
    lines, new_lines, in_styles = text.splitlines(), [], False
    for line in lines:
        if line.strip().startswith("[V4+ Styles]"):
            in_styles = True
            new_lines.append(line)
            continue
        if in_styles and line.strip().startswith("Style:"):
            new_lines.append(
                f"Style: Default,{style['fontname']},{style['fontsize']},"
                f"{style['primary_color']},{style['outline_color']},"
                f"{style['back_color']},&H00000000,"
                f"{style['bold']},0,0,0,100,100,0,0,1,"
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
                 cfg: dict, thumbnail: str | None = None,
                 progress_cb=None):

    check_ffmpeg()

    img_paths  = [check_file(img, f"이미지 {i+1}") for i, img in enumerate(images[:6])]
    audio_path = check_file(audio, "오디오") if audio else None
    sub_path   = check_file(subtitle, "자막") if subtitle else None
    out_path   = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n = len(img_paths)

    # ── 오디오 길이 기반 사진 표시 시간 자동 계산 ──────────────────────────────
    if audio_path:
        try:
            audio_duration = get_media_duration(audio_path)
            cfg["photo_duration"] = round(audio_duration / n, 3)
            cfg["_audio_duration"] = audio_duration
            if progress_cb:
                progress_cb(0, 1,
                    f"오디오 길이 {audio_duration:.1f}초 → "
                    f"사진당 {cfg['photo_duration']:.2f}초 자동 설정")
        except Exception as e:
            if progress_cb:
                progress_cb(0, 1, f"오디오 길이 감지 실패, 설정값 사용: {e}")

    has_audio = audio_path is not None
    has_sub   = sub_path is not None
    total_steps = n + 1 + (1 if has_audio else 0) + (1 if has_sub else 0) + 1
    cfg["_total"] = n

    with tempfile.TemporaryDirectory(prefix="shorts_") as tmpdir:
        tmp = Path(tmpdir)

        clip_paths = []
        for i, img in enumerate(img_paths):
            clip = tmp / f"clip_{i:02d}.mp4"
            make_clip(img, i, clip, cfg, progress_cb, i, total_steps)
            clip_paths.append(clip)

        step = n
        merged = tmp / "merged.mp4"
        concat_clips(clip_paths, merged, progress_cb, step, total_steps)
        current = merged
        step += 1

        if audio_path:
            with_audio = tmp / "with_audio.mp4"
            merge_audio(merged, audio_path, with_audio,
                        cfg["audio_norm"], progress_cb, step, total_steps)
            current = with_audio
            step += 1

        if sub_path:
            # SRT/VTT → 2줄 묶음 SRT 생성
            processed_sub = sub_path
            if sub_path.suffix.lower() in (".srt", ".vtt"):
                cues = parse_srt(sub_path)
                if cues:
                    two_line_srt = tmp / "subtitle_2lines.srt"
                    two_line_srt.write_text(
                        group_srt_2lines(cues), encoding="utf-8"
                    )
                    processed_sub = two_line_srt
                    if progress_cb:
                        progress_cb(step, total_steps,
                            f"자막 2줄 묶음 완료 ({len(cues)}개 → "
                            f"{(len(cues)+1)//2}개 블록)")

            with_sub = tmp / "with_sub.mp4"
            add_subtitles(current, processed_sub, with_sub,
                          cfg, progress_cb, step, total_steps)
            current = with_sub
            step += 1

        if progress_cb:
            progress_cb(step, total_steps, "최종 인코딩 중...")

        cmd_final = [
            "ffmpeg", "-y", "-i", str(current),
            "-c:v", "libx264", "-preset", "slow",
            "-crf", str(cfg["crf"]),
            "-profile:v", "high", "-level", "4.0",
            "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k",
            "-ar", "44100", "-pix_fmt", "yuv420p",
            str(out_path),
        ]
        run(cmd_final, "최종 출력")

    size_mb = out_path.stat().st_size / 1024 / 1024
    total_sec = cfg.get("_audio_duration", n * cfg["photo_duration"])

    if progress_cb:
        progress_cb(total_steps, total_steps,
                    f"완료! ({size_mb:.1f}MB · {total_sec:.1f}초 · 오디오 동기화)")

    if thumbnail:
        _extract_thumbnail(out_path, Path(thumbnail))

    return {"size_mb": round(size_mb, 1), "duration_sec": round(total_sec, 1),
            "output": str(out_path)}


def _extract_thumbnail(video: Path, thumb: Path):
    cmd = ["ffmpeg", "-y", "-i", str(video), "-ss", "0.5",
           "-vframes", "1", "-vf", "scale=1280:720", str(thumb)]
    run(cmd, "썸네일 생성")


# ─── CLI ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="YouTube Shorts 자동 제작")
    parser.add_argument("-i", "--images", nargs="+", metavar="IMG", required=True)
    parser.add_argument("-a", "--audio",    metavar="AUDIO")
    parser.add_argument("-s", "--subtitle", metavar="SUB")
    parser.add_argument("-o", "--output",   default="shorts_output.mp4")
    parser.add_argument("--thumbnail",      metavar="THUMB")
    parser.add_argument("--config",         metavar="JSON")
    parser.add_argument("--effect",         default="ken_burns",
                        choices=["ken_burns","pan","tilt","zoom_in","zoom_out","shake"])
    parser.add_argument("--duration",   type=float)
    parser.add_argument("--transition", type=float)
    parser.add_argument("--width",      type=int)
    parser.add_argument("--height",     type=int)
    parser.add_argument("--fps",        type=int)
    parser.add_argument("--crf",        type=int)
    parser.add_argument("--no-normalize", action="store_true")

    args = parser.parse_args()
    cfg = dict(DEFAULTS)

    if args.config:
        with open(args.config, encoding="utf-8") as f:
            cfg.update(json.load(f))

    if args.effect:     cfg["effect"]         = args.effect
    if args.duration:   cfg["photo_duration"] = args.duration
    if args.transition: cfg["transition"]     = args.transition
    if args.width:      cfg["width"]          = args.width
    if args.height:     cfg["height"]         = args.height
    if args.fps:        cfg["fps"]            = args.fps
    if args.crf:        cfg["crf"]            = args.crf
    if args.no_normalize: cfg["audio_norm"]   = False

    def cli_progress(step, total, msg):
        pct = int(step / total * 100) if total else 0
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"\r[{bar}] {pct:3d}% {msg}", end="", flush=True)
        if step == total:
            print()

    result = build_shorts(
        images=args.images, audio=args.audio,
        subtitle=args.subtitle, output=args.output,
        cfg=cfg, thumbnail=args.thumbnail,
        progress_cb=cli_progress,
    )
    print(f"\n✅ 완료: {result['output']} ({result['size_mb']}MB, {result['duration_sec']:.0f}초)")


if __name__ == "__main__":
    main()
