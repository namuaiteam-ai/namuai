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


@app.route("/whisper_check")
def whisper_check():
    """Whisper 설치 여부 확인"""
    try:
        from generate_srt import check_whisper
        installed = check_whisper()
    except Exception:
        installed = False
    return jsonify({"installed": installed})


@app.route("/whisper_generate", methods=["POST"])
def whisper_generate():
    """오디오 파일 업로드 → Whisper SRT 자동 생성"""
    from generate_srt import check_whisper, generate_srt as _gen_srt

    if not check_whisper():
        return jsonify({"error": "openai-whisper 미설치. pip install openai-whisper"}), 400

    job_id  = uuid.uuid4().hex[:10]
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True)

    audio_file = request.files.get("audio")
    if not audio_file or not audio_file.filename:
        return jsonify({"error": "오디오 파일이 없습니다."}), 400

    audio_path = job_dir / Path(audio_file.filename).name
    audio_file.save(audio_path)

    model_name = request.form.get("model", "base")
    language   = request.form.get("language", "ko")
    srt_path   = job_dir / "auto_subtitle.srt"

    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "running", "progress": 0,
            "message": "Whisper 시작...", "log": [],
            "output": str(srt_path), "result": None,
        }

    def _run():
        try:
            _gen_srt(
                audio_path=str(audio_path),
                output_srt_path=str(srt_path),
                model_name=model_name,
                language=language,
                progress_cb=_progress_cb(job_id),
            )
            _update_job(job_id, status="done", progress=100,
                        message=f"자막 생성 완료 ({srt_path.name})")
        except Exception as e:
            _update_job(job_id, status="error", message=str(e))

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/download_srt/<job_id>")
def download_srt(job_id: str):
    """생성된 SRT 파일 다운로드"""
    job = JOBS.get(job_id)
    if not job or not Path(job["output"]).exists():
        return jsonify({"error": "파일 없음"}), 404
    return send_file(job["output"], as_attachment=True,
                     download_name="auto_subtitle.srt")


if __name__ == "__main__":
    import webbrowser
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  YouTube Shorts 제작 UI")
    print(f"  http://localhost:{port}\n")
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
