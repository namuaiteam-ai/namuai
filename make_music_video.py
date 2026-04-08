#!/usr/bin/env python3
"""
뮤직비디오형 뉴스 쇼츠 제작기
D:\\ttttt2 에서 server.py가 subprocess로 호출합니다.

환경변수 (server.py → subprocess):
  MV_IMAGES     : 콤마 구분 이미지 파일명 (예: mv_image1.jpg,mv_image2.jpg)
  MV_EFFECT     : ken_burns | pan | tilt | zoom_in | zoom_out | shake
  MV_FONT       : NanumGothic | Malgun Gothic | Arial
  MV_LYRIC_SIZE : 가사 폰트 크기 (기본 36)
  MV_LYRIC_GLOW : ASS 글로우 색상 (기본 &H00B469FF)
  MV_TRANSITION : 전환 길이(초) (기본 0.5)
  MV_WIDTH      : 영상 너비 (기본 720)
  MV_HEIGHT     : 영상 높이 (기본 1280)

입력 파일 (cwd = BASE_DIR):
  mv_image1.jpg, mv_image2.jpg, ...  (뉴스 사진)
  music.mp3                          (수노 음악)
  lyrics.lrc                         (가사, 없으면 자막 없이 제작)

출력: video/YYYY-MM-DD/mv_output.mp4
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


# ─── 설정 ────────────────────────────────────────────────────────────────────
def _e(key, default): return os.environ.get(key, default)

CWD    = Path(os.getcwd())
TODAY  = datetime.now().strftime("%Y-%m-%d")
OUT_DIR = CWD / "video" / TODAY
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT = str(OUT_DIR / "mv_output.mp4")

CFG = {
    "width":          int(_e("MV_WIDTH",      "720")),
    "height":         int(_e("MV_HEIGHT",     "1280")),
    "fps":            30,
    "transition":     float(_e("MV_TRANSITION", "0.5")),
    "zoom_ratio":     0.04,
    "crf":            23,
    "effect":         _e("MV_EFFECT",     "ken_burns"),
    "lyric_font":     _e("MV_FONT",       "NanumGothic"),
    "lyric_size":     int(_e("MV_LYRIC_SIZE", "36")),
    "lyric_color":    "&H00FFFFFF",
    "lyric_glow":     _e("MV_LYRIC_GLOW", "&H00B469FF"),
    "lyric_outline":  3,
    "lyric_shadow":   2,
    "lyric_margin_v": 90,
    "lyric_fade_ms":  200,
}


# ─── ffmpeg 유틸 ──────────────────────────────────────────────────────────────
def run_cmd(cmd: list, desc: str = ""):
    print(f"  [{desc}]", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 오류 [{desc}]:\n{r.stderr[-3000:]}")
    return r


def get_duration(path: Path) -> float:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_format", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {r.stderr}")
    return float(json.loads(r.stdout)["format"]["duration"])


# ─── LRC 파서 ─────────────────────────────────────────────────────────────────
def parse_lrc(text: str) -> list:
    cues = []
    for line in text.splitlines():
        m = re.match(r"\[(\d{1,2}):(\d{2})\.(\d{2,3})\](.*)", line.strip())
        if m:
            mm, ss = int(m.group(1)), int(m.group(2))
            cc_str = m.group(3)
            ms_frac = int(cc_str) if len(cc_str) == 3 else int(cc_str) * 10
            time_ms = mm * 60000 + ss * 1000 + ms_frac
            lyric = m.group(4).strip()
            if lyric:
                cues.append({"time_ms": time_ms, "text": lyric})
    cues.sort(key=lambda c: c["time_ms"])
    return cues


def add_end_times(cues: list, total_ms: int) -> list:
    for i, cue in enumerate(cues):
        cue["end_ms"] = cues[i + 1]["time_ms"] if i + 1 < len(cues) else total_ms
    return cues


# ─── 뮤직비디오 스타일 ASS 자막 ───────────────────────────────────────────────
def make_lyric_ass(cues: list, cfg: dict) -> str:
    w, h      = cfg["width"], cfg["height"]
    font      = cfg["lyric_font"]
    size      = cfg["lyric_size"]
    color     = cfg["lyric_color"]
    glow      = cfg["lyric_glow"]
    outline   = cfg["lyric_outline"]
    shadow    = cfg["lyric_shadow"]
    margin_v  = cfg["lyric_margin_v"]
    fade_ms   = cfg["lyric_fade_ms"]
    cx        = w // 2
    y_pos     = h - margin_v

    def tc(ms):
        h_, r = divmod(max(0, ms), 3600000)
        m_, r = divmod(r, 60000)
        s_, f = divmod(r, 1000)
        return f"{h_}:{m_:02d}:{s_:02d}.{f // 10:02d}"

    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {w}\nPlayResY: {h}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Lyric,{font},{size},{color},&H000000FF,{glow},"
        f"&H80000000,1,0,0,0,100,100,1,0,1,{outline},{shadow},"
        f"2,0,0,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, "
        "MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    for cue in cues:
        s, e = cue["time_ms"], cue["end_ms"]
        text = cue["text"].replace("\n", "\\N").strip()
        if not text:
            continue
        if e - s <= fade_ms * 2:
            events.append(
                f"Dialogue: 0,{tc(s)},{tc(e)},Lyric,,0,0,0,,"
                f"{{\\an2\\pos({cx},{y_pos})\\fad({fade_ms},{fade_ms})}}{text}"
            )
        else:
            events.append(
                f"Dialogue: 0,{tc(s)},{tc(e)},Lyric,,0,0,0,,"
                f"{{\\an2\\pos({cx},{y_pos})"
                f"\\fad({fade_ms},{fade_ms})"
                f"\\fscx90\\fscy90"
                f"\\t(0,{fade_ms},\\fscx100\\fscy100)}}{text}"
            )
    return header + "\n".join(events) + "\n"


# ─── 영상 클립 생성 (make_shorts.py 재사용 or 독립 구현) ─────────────────────
def _motion_filter(effect, idx, w, h, dur, fps, zoom):
    frames = int(dur * fps)
    scale  = f"scale={w * 2}:{h * 2},"
    tail   = f":d={frames}:s={w}x{h}:fps={fps},setsar=1"

    if effect == "pan":
        sign = 1 if idx % 2 == 0 else -1
        step = max(1, int(w * 0.1 / frames))
        return f"{scale}zoompan=z='1.12':x='max(0,min(iw-iw/zoom,x+{sign*step}))':y='ih/2-(ih/zoom/2)'{tail}"
    elif effect == "tilt":
        sign = 1 if idx % 2 == 0 else -1
        step = max(1, int(h * 0.1 / frames))
        return f"{scale}zoompan=z='1.12':x='iw/2-(iw/zoom/2)':y='max(0,min(ih-ih/zoom,y+{sign*step}))'{tail}"
    elif effect == "zoom_in":
        zi = zoom * 2 / frames
        return f"{scale}zoompan=z='min(zoom+{zi:.6f},{1+zoom*2})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'{tail}"
    elif effect == "zoom_out":
        zd = zoom * 2 / frames
        return f"{scale}zoompan=z='if(eq(on,1),{1+zoom*2},max(zoom-{zd:.6f},1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'{tail}"
    elif effect == "shake":
        return f"{scale}zoompan=z='1.06':x='iw/2-(iw/zoom/2)+sin(on*0.9)*12':y='ih/2-(ih/zoom/2)+cos(on*1.3)*8'{tail}"
    else:  # ken_burns
        z_end = 1.0 + zoom
        z_expr = (f"'min(zoom+{zoom/frames:.6f},{z_end})'"
                  if idx % 2 == 0 else f"'max(zoom-{zoom/frames:.6f},1.0)'")
        return f"{scale}zoompan=z={z_expr}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'{tail}"


def make_clip(img: Path, idx: int, out: Path, cfg: dict, total: int) -> Path:
    w, h   = cfg["width"], cfg["height"]
    fps    = cfg["fps"]
    dur    = cfg["photo_duration"]
    zoom   = cfg["zoom_ratio"]
    trans  = cfg["transition"]
    effect = cfg["effect"]

    fade_f  = max(1, int(trans * fps / 2))
    total_f = int(dur * fps)
    fade_out_start = total_f - fade_f

    motion = _motion_filter(effect, idx, w, h, dur, fps, zoom)
    fade   = (f"fade=t=in:st=0:nb_frames={fade_f},"
              f"fade=t=out:st={fade_out_start}:nb_frames={fade_f}")
    vf = (f"format=yuv420p,"
          f"scale='if(gt(iw/ih,{w}/{h}),{w},-2)':'if(gt(iw/ih,{w}/{h}),-2,{h})',"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
          f"{motion},{fade}")

    run_cmd(["ffmpeg", "-y", "-loop", "1", "-i", str(img),
             "-vf", vf, "-t", str(dur), "-r", str(fps), "-an",
             "-c:v", "libx264", "-preset", "fast", "-crf", str(cfg["crf"]),
             str(out)],
            f"클립 {idx+1}/{total}")
    return out


# ─── 메인 파이프라인 ──────────────────────────────────────────────────────────
def main():
    print("[MV] 뮤직비디오 제작 시작")

    # 이미지 파일 목록
    img_env = _e("MV_IMAGES", "")
    if img_env:
        img_paths = [CWD / n.strip() for n in img_env.split(",") if n.strip()]
    else:
        img_paths = []
        for i in range(1, 7):
            for ext in (".jpg", ".jpeg", ".png", ".webp"):
                p = CWD / f"mv_image{i}{ext}"
                if p.exists():
                    img_paths.append(p)
                    break

    img_paths = [p for p in img_paths if p.exists()]
    if not img_paths:
        print("[ERROR] 이미지 파일을 찾을 수 없습니다. (mv_image1.jpg, ...)")
        sys.exit(1)
    print(f"  이미지 {len(img_paths)}장 확인")

    # 음악 파일
    music_path = CWD / "music.mp3"
    if not music_path.exists():
        print("[ERROR] music.mp3를 찾을 수 없습니다.")
        sys.exit(1)

    # LRC 가사
    lrc_path = CWD / "lyrics.lrc"
    lrc_text = lrc_path.read_text(encoding="utf-8") if lrc_path.exists() else ""

    # 오디오 길이 → 사진 표시 시간 자동 계산
    audio_dur = get_duration(music_path)
    n = len(img_paths)
    CFG["photo_duration"] = round(audio_dur / n + 1.0, 3)
    print(f"  음악 {audio_dur:.1f}초 → 사진당 {CFG['photo_duration']:.1f}초")

    # LRC 파싱
    lrc_cues = []
    if lrc_text.strip():
        lrc_cues = parse_lrc(lrc_text)
        lrc_cues = add_end_times(lrc_cues, int(audio_dur * 1000))
        print(f"  LRC 가사 {len(lrc_cues)}줄 파싱")

    with tempfile.TemporaryDirectory(prefix="mv_") as tmpdir:
        tmp = Path(tmpdir)

        # 클립 생성
        clips = []
        for i, img in enumerate(img_paths):
            clip = tmp / f"clip_{i:02d}.mp4"
            make_clip(img, i, clip, CFG, n)
            clips.append(clip)

        # 클립 연결
        list_f = tmp / "list.txt"
        list_f.write_text(
            "\n".join(f"file '{str(c.resolve()).replace(chr(92), '/')}'"
                      for c in clips),
            encoding="utf-8"
        )
        merged = tmp / "merged.mp4"
        run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(list_f), "-c", "copy", str(merged)], "클립 연결")

        # 음악 합성 (노멀라이즈 없음)
        with_audio = tmp / "with_audio.mp4"
        run_cmd(["ffmpeg", "-y",
                 "-i", str(merged), "-i", str(music_path),
                 "-filter_complex", "[1:a]anull[a]",
                 "-map", "0:v", "-map", "[a]",
                 "-shortest", "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "192k",
                 str(with_audio)], "음악 합성")
        current = with_audio

        # 가사 자막 합성
        if lrc_cues:
            ass_content = make_lyric_ass(lrc_cues, CFG)
            ass_path = tmp / "lyrics.ass"
            ass_path.write_text(ass_content, encoding="utf-8")
            sub_str = str(ass_path).replace("\\", "/").replace(":", "\\:")
            with_sub = tmp / "with_sub.mp4"
            run_cmd(["ffmpeg", "-y", "-i", str(current),
                     "-vf", f"ass='{sub_str}'",
                     "-c:v", "libx264", "-preset", "fast",
                     "-crf", str(CFG["crf"]), "-c:a", "copy",
                     str(with_sub)], "가사 자막 합성")
            current = with_sub

        # 최종 인코딩
        run_cmd(["ffmpeg", "-y", "-i", str(current),
                 "-t", f"{audio_dur:.3f}",
                 "-c:v", "libx264", "-preset", "slow",
                 "-crf", str(CFG["crf"]),
                 "-profile:v", "high", "-level", "4.0",
                 "-movflags", "+faststart",
                 "-c:a", "aac", "-b:a", "192k",
                 "-ar", "44100", "-pix_fmt", "yuv420p",
                 OUTPUT], "최종 인코딩")

    size_mb = Path(OUTPUT).stat().st_size / 1024 / 1024
    print(f"[MV] 완료: {OUTPUT} ({size_mb:.1f}MB · {audio_dur:.1f}초)")


if __name__ == "__main__":
    main()
