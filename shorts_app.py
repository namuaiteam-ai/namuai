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

import tts_supertonic

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


# ─── 라우트 ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/tts/voices")
def tts_voices():
    return jsonify({
        "available": tts_supertonic.is_available(),
        "voices": tts_supertonic.VOICE_STYLES + tts_supertonic.list_custom_voices(),
        "builtin_voices": tts_supertonic.VOICE_STYLES,
    })


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

    # 오디오 파일이 없고 나레이션 텍스트가 있으면 Supertonic으로 로컬 TTS 생성
    narration_text = (form.get("narration_text") or "").strip()
    if not audio and narration_text:
        if not tts_supertonic.is_available():
            return jsonify({
                "error": "로컬 TTS(Supertonic)가 설치되어 있지 않습니다. "
                         "'pip install supertonic' 실행 후 다시 시도해주세요."
            }), 400
        try:
            tts_path = job_dir / "narration_tts.wav"
            tts_supertonic.synthesize_to_file(
                narration_text, tts_path,
                voice=form.get("tts_voice", "F1"),
                lang=form.get("tts_lang", "ko"),
                speed=float(form.get("tts_speed", 1.05)),
            )
            audio = str(tts_path)
        except Exception as e:
            return jsonify({"error": f"TTS 생성 실패: {e}"}), 400
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


@app.route("/thumbnail/<job_id>")
def thumbnail(job_id: str):
    thumb = UPLOAD_DIR / job_id / "thumb.jpg"
    if not thumb.exists():
        # 영상에서 썸네일 추출
        output = UPLOAD_DIR / job_id / "output.mp4"
        if not output.exists():
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
