#!/usr/bin/env python3
"""
뮤직비디오형 뉴스 쇼츠 제작기
- 뉴스 사진 + 수노 음악(MP3) + LRC 가사 → MP4 (720×1280)
- 가사가 음악 타이밍에 맞춰 뮤직비디오 스타일로 표시됨
- make_shorts.py의 영상/오디오 파이프라인 재사용
"""

import re
import tempfile
from pathlib import Path

from make_shorts import (
    DEFAULTS,
    check_ffmpeg,
    check_file,
    concat_clips,
    get_media_duration,
    make_clip,
    merge_audio,
    run,
)

# 뮤직비디오 기본 설정 (나레이션 쇼츠와 다른 값)
MV_DEFAULTS = {
    **DEFAULTS,
    "audio_norm": False,       # 음악은 노멀라이즈 안 함 (원음 유지)
    "lyric_font": "NanumGothic",
    "lyric_size": 36,
    "lyric_color": "&H00FFFFFF",    # 흰색
    "lyric_glow": "&H00B469FF",     # 핑크 (K-pop 기본)
    "lyric_outline": 3,
    "lyric_shadow": 2,
    "lyric_margin_v": 90,
    "lyric_fade_ms": 200,
}


# ─── LRC 파서 ─────────────────────────────────────────────────────────────────

def parse_lrc(text: str) -> list:
    """
    LRC 텍스트 파싱 → [{time_ms, text}, ...]
    메타데이터 태그([ti:], [ar:] 등)는 무시.
    """
    cues = []
    for line in text.splitlines():
        line = line.strip()
        # [mm:ss.cc] 또는 [mm:ss.xx] 형식
        m = re.match(r"\[(\d{1,2}):(\d{2})\.(\d{2})\](.*)", line)
        if not m:
            # [mm:ss:cc] 콜론 구분도 허용
            m = re.match(r"\[(\d{1,2}):(\d{2}):(\d{2,3})\](.*)", line)
        if m:
            mm, ss, cc = int(m.group(1)), int(m.group(2)), int(m.group(3))
            # cc가 3자리면 ms, 2자리면 cs(×10)
            ms_frac = cc if len(m.group(3)) == 3 else cc * 10
            time_ms = mm * 60000 + ss * 1000 + ms_frac
            lyric = m.group(4).strip()
            if lyric:
                cues.append({"time_ms": time_ms, "text": lyric})

    # 시간순 정렬
    cues.sort(key=lambda c: c["time_ms"])
    return cues


def _add_end_times(cues: list, total_ms: int) -> list:
    """각 큐에 end_ms 추가 (다음 큐의 시작 시간 또는 총 길이)"""
    for i, cue in enumerate(cues):
        if i + 1 < len(cues):
            cue["end_ms"] = cues[i + 1]["time_ms"]
        else:
            cue["end_ms"] = total_ms
    return cues


# ─── 뮤직비디오 스타일 ASS 생성 ───────────────────────────────────────────────

def make_lyric_ass(cues: list, w: int, h: int, cfg: dict) -> str:
    """
    LRC 큐 목록 → 뮤직비디오 스타일 ASS 자막
    - 큰 폰트, 하단 중앙 배치
    - 컬러 글로우 테두리
    - 팝인(90→100% 스케일) + 페이드인/아웃
    """
    font      = cfg.get("lyric_font",     MV_DEFAULTS["lyric_font"])
    size      = int(cfg.get("lyric_size", MV_DEFAULTS["lyric_size"]))
    color     = cfg.get("lyric_color",    MV_DEFAULTS["lyric_color"])
    glow      = cfg.get("lyric_glow",     MV_DEFAULTS["lyric_glow"])
    outline   = int(cfg.get("lyric_outline", MV_DEFAULTS["lyric_outline"]))
    shadow    = int(cfg.get("lyric_shadow",  MV_DEFAULTS["lyric_shadow"]))
    margin_v  = int(cfg.get("lyric_margin_v", MV_DEFAULTS["lyric_margin_v"]))
    fade_ms   = int(cfg.get("lyric_fade_ms",  MV_DEFAULTS["lyric_fade_ms"]))

    cx    = w // 2
    y_pos = h - margin_v

    def tc(ms: int) -> str:
        h_, r = divmod(max(0, ms), 3600000)
        m_, r = divmod(r, 60000)
        s_, f = divmod(r, 1000)
        return f"{h_}:{m_:02d}:{s_:02d}.{f // 10:02d}"

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
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
        s    = cue["time_ms"]
        e    = cue["end_ms"]
        text = cue["text"].replace("\n", "\\N").strip()

        if not text:
            continue

        dur = e - s
        if dur <= fade_ms * 2:
            # 짧은 큐: 페이드만
            events.append(
                f"Dialogue: 0,{tc(s)},{tc(e)},Lyric,,0,0,0,,"
                f"{{\\an2\\pos({cx},{y_pos})\\fad({fade_ms},{fade_ms})}}{text}"
            )
        else:
            # 팝인(스케일 90→100%) + 페이드인/아웃
            events.append(
                f"Dialogue: 0,{tc(s)},{tc(e)},Lyric,,0,0,0,,"
                f"{{\\an2\\pos({cx},{y_pos})"
                f"\\fad({fade_ms},{fade_ms})"
                f"\\fscx90\\fscy90"
                f"\\t(0,{fade_ms},\\fscx100\\fscy100)}}{text}"
            )

    return header + "\n".join(events) + "\n"


# ─── ASS 자막 오버레이 ─────────────────────────────────────────────────────────

def _burn_ass(video_path: Path, ass_path: Path, out_path: Path,
              crf: int, progress_cb=None, step=0, total_steps=1) -> Path:
    """ASS 자막을 영상에 합성 (ffmpeg ass 필터)"""
    sub_str = str(ass_path).replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"ass='{sub_str}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
        "-c:a", "copy",
        str(out_path),
    ]
    run(cmd, "가사 자막 합성", progress_cb, step, total_steps)
    return out_path


# ─── 메인 파이프라인 ──────────────────────────────────────────────────────────

def build_music_video(images: list, audio: str,
                      lrc_text: str, output: str,
                      cfg: dict, progress_cb=None) -> dict:
    """
    뮤직비디오형 쇼츠 제작 메인 파이프라인

    Args:
        images:   뉴스 사진 경로 목록 (최대 6장)
        audio:    수노 음악 MP3 경로 (필수)
        lrc_text: LRC 형식 가사 텍스트 (선택)
        output:   출력 MP4 경로
        cfg:      설정 딕셔너리
        progress_cb: 진행 콜백 (step, total, msg)
    """
    check_ffmpeg()

    # 설정값 병합
    full_cfg = {**MV_DEFAULTS, **cfg}

    img_paths  = [check_file(img, f"이미지 {i + 1}") for i, img in enumerate(images[:6])]
    audio_path = check_file(audio, "음악")
    out_path   = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n = len(img_paths)

    # ── 오디오 길이 → 사진 표시 시간 자동 계산 ─────────────────────────────
    audio_duration = get_media_duration(audio_path)
    full_cfg["photo_duration"] = round(audio_duration / n + 1.0, 3)
    full_cfg["_audio_duration"] = audio_duration
    full_cfg["_total"] = n

    if progress_cb:
        progress_cb(0, 1,
            f"음악 {audio_duration:.1f}초 → "
            f"사진당 {full_cfg['photo_duration']:.1f}초")

    # ── LRC 파싱 ───────────────────────────────────────────────────────────
    lrc_cues = []
    if lrc_text and lrc_text.strip():
        lrc_cues = parse_lrc(lrc_text)
        lrc_cues = _add_end_times(lrc_cues, int(audio_duration * 1000))
        if progress_cb:
            progress_cb(0, 1, f"LRC 가사 {len(lrc_cues)}줄 파싱 완료")

    has_lyrics = bool(lrc_cues)
    total_steps = n + 1 + 1 + (1 if has_lyrics else 0) + 1
    # (clips + concat + audio + lyrics + final)

    with tempfile.TemporaryDirectory(prefix="mv_") as tmpdir:
        tmp = Path(tmpdir)

        # ── 사진 클립 생성 ──────────────────────────────────────────────
        clip_paths = []
        for i, img in enumerate(img_paths):
            clip = tmp / f"clip_{i:02d}.mp4"
            make_clip(img, i, clip, full_cfg, progress_cb, i, total_steps)
            clip_paths.append(clip)

        step = n

        # ── 클립 연결 ──────────────────────────────────────────────────
        merged = tmp / "merged.mp4"
        concat_clips(clip_paths, merged, progress_cb, step, total_steps)
        current = merged
        step += 1

        # ── 음악 합성 (노멀라이즈 없이) ────────────────────────────────
        with_audio = tmp / "with_audio.mp4"
        merge_audio(merged, audio_path, with_audio,
                    normalize=full_cfg["audio_norm"],
                    audio_duration=audio_duration,
                    progress_cb=progress_cb, step=step, total_steps=total_steps)
        current = with_audio
        step += 1

        # ── 가사 자막 합성 ──────────────────────────────────────────────
        if has_lyrics:
            ass_content = make_lyric_ass(
                lrc_cues, full_cfg["width"], full_cfg["height"], full_cfg
            )
            ass_path = tmp / "lyrics.ass"
            ass_path.write_text(ass_content, encoding="utf-8")

            with_sub = tmp / "with_lyrics.mp4"
            _burn_ass(current, ass_path, with_sub,
                      full_cfg["crf"], progress_cb, step, total_steps)
            current = with_sub
            step += 1

        # ── 최종 인코딩 (정확한 길이 트림) ─────────────────────────────
        if progress_cb:
            progress_cb(step, total_steps, "최종 인코딩 중...")

        cmd_final = [
            "ffmpeg", "-y", "-i", str(current),
            "-t", f"{audio_duration:.3f}",
            "-c:v", "libx264", "-preset", "slow",
            "-crf", str(full_cfg["crf"]),
            "-profile:v", "high", "-level", "4.0",
            "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k",
            "-ar", "44100", "-pix_fmt", "yuv420p",
            str(out_path),
        ]
        run(cmd_final, f"최종 출력 ({audio_duration:.1f}초)")

    size_mb = out_path.stat().st_size / 1024 / 1024

    if progress_cb:
        progress_cb(total_steps, total_steps,
                    f"뮤직비디오 완료! ({size_mb:.1f}MB · {audio_duration:.1f}초)")

    return {
        "size_mb": round(size_mb, 1),
        "duration_sec": round(audio_duration, 1),
        "output": str(out_path),
        "lyric_count": len(lrc_cues),
    }
