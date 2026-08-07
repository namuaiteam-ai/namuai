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

# ─── 이미지 프롬프트 생성 (zip 업로드 → Gemini 자동화 확장 프로그램 연동) ───────
PROMPT_DIR = Path(os.environ.get("PROMPT_UPLOAD_DIR", "prompt_jobs"))
PROMPT_DIR.mkdir(exist_ok=True)

# job_id → {job_id, items: [{id, name, prompt, source_filename, status, message}], style, ...}
PROMPT_JOBS: dict = {}
PROMPT_JOBS_LOCK = threading.Lock()


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


@app.route("/image-prompts")
def image_prompts_page():
    return render_template("image_prompts.html")


@app.route("/image-prompts/generate", methods=["POST"])
def image_prompts_generate():
    zip_file = request.files.get("zip")
    if not zip_file or not zip_file.filename:
        return jsonify({"error": "압축파일(zip)을 업로드해주세요."}), 400

    job_id = uuid.uuid4().hex[:10]
    job_dir = PROMPT_DIR / job_id
    job_dir.mkdir(parents=True)
    zip_path = job_dir / "upload.zip"
    zip_file.save(zip_path)

    style          = request.form.get("style", "photo")
    extra_keywords = request.form.get("extra_keywords", "")
    aspect_ratio   = request.form.get("aspect_ratio", "1:1")

    import prompt_gen
    try:
        items = prompt_gen.generate_prompts_from_zip(
            str(zip_path), style=style,
            extra_keywords=extra_keywords, aspect_ratio=aspect_ratio,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    with PROMPT_JOBS_LOCK:
        PROMPT_JOBS[job_id] = {
            "job_id": job_id,
            "items": items,
            "style": style,
            "extra_keywords": extra_keywords,
            "aspect_ratio": aspect_ratio,
        }

    return jsonify({"job_id": job_id, "items": items})


@app.route("/image-prompts/<job_id>/update", methods=["POST"])
def image_prompts_update(job_id):
    job = PROMPT_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "존재하지 않는 작업입니다."}), 404

    data = request.get_json(force=True, silent=True) or {}
    edited = {int(it["id"]): it.get("prompt", "") for it in data.get("items", []) if "id" in it}
    with PROMPT_JOBS_LOCK:
        for item in job["items"]:
            if item["id"] in edited:
                item["prompt"] = edited[item["id"]]

    return jsonify({"ok": True})


@app.route("/image-prompts/<job_id>/state")
def image_prompts_state(job_id):
    job = PROMPT_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "존재하지 않는 작업입니다."}), 404
    return jsonify(job)


# ─── 크롬 확장 프로그램용 API (CORS 허용) ──────────────────────────────────────
@app.after_request
def _add_cors_headers(resp):
    if request.path.startswith("/api/"):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.route("/api/jobs/<job_id>/prompts")
def api_job_prompts(job_id):
    job = PROMPT_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "존재하지 않는 작업입니다."}), 404
    return jsonify({
        "job_id": job_id,
        "items": [
            {"id": it["id"], "name": it["name"], "prompt": it["prompt"], "status": it["status"]}
            for it in job["items"]
        ],
    })


@app.route("/api/jobs/<job_id>/report", methods=["POST"])
def api_job_report(job_id):
    job = PROMPT_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "존재하지 않는 작업입니다."}), 404

    data = request.get_json(force=True, silent=True) or {}
    item_id = data.get("id")
    status  = data.get("status", "done")
    message = data.get("message", "")

    with PROMPT_JOBS_LOCK:
        for item in job["items"]:
            if item["id"] == item_id:
                item["status"] = status
                item["message"] = message
                break

    return jsonify({"ok": True})


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
