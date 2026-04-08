#!/usr/bin/env python3
"""
YouTube Shorts 영상 제작 - Flask Web UI
실행: python shorts_app.py
접속: http://localhost:5000
"""

import json
import os
import sys
import threading
import uuid
from pathlib import Path

from flask import (Flask, Response, jsonify, render_template,
                   request, send_file, stream_with_context)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB

UPLOAD_DIR = Path(os.environ.get("SHORTS_UPLOAD_DIR", "shorts_jobs"))
UPLOAD_DIR.mkdir(exist_ok=True)

# job_id → {status, progress, total, message, output, error, log}
JOBS: dict = {}
JOBS_LOCK = threading.Lock()


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────
def save_upload(file_obj, dest_dir: Path) -> Path | None:
    if not file_obj or not file_obj.filename:
        return None
    safe = Path(file_obj.filename).name
    path = dest_dir / safe
    file_obj.save(path)
    return path


def _update_job(job_id: str, **kwargs):
    with JOBS_LOCK:
        JOBS[job_id].update(kwargs)


def _progress_cb(job_id: str):
    def cb(step: int, total: int, msg: str):
        pct = int(step / total * 100) if total else 0
        with JOBS_LOCK:
            JOBS[job_id]["progress"] = pct
            JOBS[job_id]["message"] = msg
            JOBS[job_id]["log"].append({"pct": pct, "msg": msg})
    return cb


def _run_job(job_id: str, images: list, audio, subtitle, output: str, cfg: dict):
    try:
        _update_job(job_id, status="running", progress=0, message="시작 중...")
        sys.path.insert(0, str(Path(__file__).parent))
        import make_shorts
        result = make_shorts.build_shorts(
            images=images, audio=audio, subtitle=subtitle,
            output=output, cfg=cfg,
            progress_cb=_progress_cb(job_id),
        )
        _update_job(job_id, status="done", progress=100,
                    message=f"완료! {result['size_mb']}MB · {result['duration_sec']:.0f}초",
                    result=result)
    except Exception as e:
        _update_job(job_id, status="error", message=str(e))


def _run_mv_job(job_id: str, images: list, music: str,
                lrc_text: str, output: str, cfg: dict):
    try:
        _update_job(job_id, status="running", progress=0, message="뮤직비디오 제작 시작...")
        sys.path.insert(0, str(Path(__file__).parent))
        import make_music_video
        result = make_music_video.build_music_video(
            images=images, audio=music, lrc_text=lrc_text,
            output=output, cfg=cfg,
            progress_cb=_progress_cb(job_id),
        )
        _update_job(job_id, status="done", progress=100,
                    message=f"뮤직비디오 완료! {result['size_mb']}MB · {result['duration_sec']:.0f}초",
                    result=result)
    except Exception as e:
        import traceback
        _update_job(job_id, status="error",
                    message=str(e) + "\n" + traceback.format_exc())


# ─── 라우트 ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    job_id = uuid.uuid4().hex[:10]
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True)

    # 이미지 (최대 6장)
    images = []
    for i in range(6):
        p = save_upload(request.files.get(f"image_{i}"), job_dir)
        if p:
            images.append(str(p))

    if not images:
        return jsonify({"error": "이미지를 1장 이상 업로드해주세요."}), 400

    audio    = str(save_upload(request.files.get("audio"),    job_dir) or "") or None
    subtitle = str(save_upload(request.files.get("subtitle"), job_dir) or "") or None

    form = request.form
    cfg = {
        "width":          int(form.get("width",  720)),
        "height":         int(form.get("height", 1280)),
        "fps":            30,
        "photo_duration": float(form.get("duration",   4.0)),
        "transition":     float(form.get("transition", 0.6)),
        "zoom_ratio":     0.04,
        "crf":            int(form.get("crf", 23)),
        "audio_norm":     True,
        "effect":         form.get("effect", "ken_burns"),
        "subtitle_font":  form.get("subtitle_font",  "Arial"),
        "subtitle_size":  int(form.get("subtitle_size", 22)),
        "subtitle_color": form.get("subtitle_color",   "&H00FFFFFF"),
        "subtitle_bold":  int(form.get("subtitle_bold", 1)),
        "subtitle_margin_v": 60,
    }

    output = str(job_dir / "output.mp4")

    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "queued", "progress": 0, "message": "대기 중...",
            "output": output, "log": [], "result": None,
        }

    t = threading.Thread(
        target=_run_job,
        args=(job_id, images, audio, subtitle, output, cfg),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify({k: v for k, v in job.items() if k != "log"})


@app.route("/progress/<job_id>")
def progress_sse(job_id: str):
    """Server-Sent Events 진행 상황 스트림"""

    def stream():
        import time
        sent = 0
        while True:
            job = JOBS.get(job_id)
            if not job:
                yield "data: {\"error\": \"not found\"}\n\n"
                break
            with JOBS_LOCK:
                new_logs = job["log"][sent:]
                sent = len(job["log"])
            for entry in new_logs:
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
            if job["status"] in ("done", "error"):
                final = {"pct": job["progress"], "msg": job["message"],
                         "status": job["status"]}
                yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
                break
            time.sleep(0.4)

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/download/<job_id>")
def download(job_id: str):
    job = JOBS.get(job_id)
    if not job or not Path(job["output"]).exists():
        return jsonify({"error": "파일 없음"}), 404
    return send_file(job["output"], as_attachment=True,
                     download_name="shorts_output.mp4")


@app.route("/generate_lyrics", methods=["POST"])
def generate_lyrics_api():
    """Claude AI로 뉴스 기사 → 가사 생성 (ANTHROPIC_API_KEY 필요)"""
    data = request.get_json(force=True, silent=True) or {}
    article = data.get("article", "").strip()
    style   = data.get("style",   "kpop")
    duration = int(data.get("duration", 60))

    if not article:
        return jsonify({"error": "기사 내용을 입력해주세요."}), 400

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import lyrics_generator
        result = lyrics_generator.generate_lyrics(article, style, duration)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/convert_lrc", methods=["POST"])
def convert_lrc():
    """가사 텍스트 → LRC 자동 변환 (무료, API 불필요)"""
    data = request.get_json(force=True, silent=True) or {}
    lyrics_text = data.get("lyrics", "").strip()
    duration    = int(data.get("duration", 60))
    title       = data.get("title", "뮤직비디오 뉴스")

    if not lyrics_text:
        return jsonify({"error": "가사를 입력해주세요."}), 400

    # 빈 줄·섹션 태그([버스], [코러스] 등) 제외
    lines = [
        l.strip() for l in lyrics_text.splitlines()
        if l.strip() and not (l.strip().startswith("[") and l.strip().endswith("]"))
    ]
    if not lines:
        return jsonify({"error": "유효한 가사 줄이 없습니다."}), 400

    sys.path.insert(0, str(Path(__file__).parent))
    from lyrics_generator import _auto_lrc
    lrc = _auto_lrc(lines, duration, title)
    return jsonify({"lrc": lrc, "line_count": len(lines)})


@app.route("/generate_mv", methods=["POST"])
def generate_mv():
    """뮤직비디오형 쇼츠 생성"""
    job_id  = uuid.uuid4().hex[:10]
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True)

    # 이미지 (최대 6장)
    images = []
    for i in range(6):
        p = save_upload(request.files.get(f"mv_image_{i}"), job_dir)
        if p:
            images.append(str(p))

    if not images:
        return jsonify({"error": "이미지를 1장 이상 업로드해주세요."}), 400

    music = save_upload(request.files.get("mv_music"), job_dir)
    if not music:
        return jsonify({"error": "수노 음악 파일을 업로드해주세요."}), 400

    lrc_text = request.form.get("lrc_text", "")

    form = request.form
    cfg = {
        "width":         int(form.get("mv_width",  720)),
        "height":        int(form.get("mv_height", 1280)),
        "fps":           30,
        "photo_duration": 4.0,
        "transition":    float(form.get("mv_transition", 0.6)),
        "zoom_ratio":    0.04,
        "crf":           int(form.get("mv_crf", 23)),
        "audio_norm":    False,
        "effect":        form.get("mv_effect", "ken_burns"),
        "lyric_font":    form.get("mv_font",   "NanumGothic"),
        "lyric_size":    int(form.get("mv_lyric_size", 36)),
        "lyric_color":   form.get("mv_lyric_color", "&H00FFFFFF"),
        "lyric_glow":    form.get("mv_lyric_glow",  "&H00B469FF"),
    }

    output = str(job_dir / "mv_output.mp4")

    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "queued", "progress": 0, "message": "대기 중...",
            "output": output, "log": [], "result": None, "type": "mv",
        }

    t = threading.Thread(
        target=_run_mv_job,
        args=(job_id, images, str(music), lrc_text, output, cfg),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/thumbnail/<job_id>")
def thumbnail(job_id: str):
    thumb = UPLOAD_DIR / job_id / "thumb.jpg"
    if not thumb.exists():
        # output.mp4 또는 mv_output.mp4 찾기
        output = None
        for fname in ("output.mp4", "mv_output.mp4"):
            candidate = UPLOAD_DIR / job_id / fname
            if candidate.exists():
                output = candidate
                break
        if not output:
            return jsonify({"error": "없음"}), 404
        import subprocess
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(output), "-ss", "0.5",
             "-vframes", "1", "-vf", "scale=360:640", str(thumb)],
            capture_output=True,
        )
    if thumb.exists():
        return send_file(thumb, mimetype="image/jpeg")
    return jsonify({"error": "썸네일 생성 실패"}), 500


if __name__ == "__main__":
    import webbrowser
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  YouTube Shorts 제작 UI")
    print(f"  http://localhost:{port}\n")
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
