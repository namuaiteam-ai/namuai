#!/usr/bin/env python3
"""
Gemini 이미지 프롬프트 자동 입력 - Flask Web UI
실행: python gemini_app.py
접속: http://localhost:5001
"""

import json
import os
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context

sys.path.insert(0, str(Path(__file__).parent))
import gemini_image_prompt_automation as gemini_auto

app = Flask(__name__)

JOB_DIR = Path(os.environ.get("GEMINI_JOB_DIR", "gemini_jobs"))
JOB_DIR.mkdir(exist_ok=True)

# job_id → {status, progress, message, log, results, stop_requested}
JOBS: dict = {}
JOBS_LOCK = threading.Lock()


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────
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


def _should_stop(job_id: str):
    def check():
        with JOBS_LOCK:
            return JOBS[job_id].get("stop_requested", False)
    return check


def _run_job(job_id: str, prompts: list, opts: dict):
    try:
        _update_job(job_id, status="running", progress=0, message="시작 중...")
        images_dir = JOB_DIR / job_id / "images"
        results = gemini_auto.run_prompts(
            prompts,
            profile_dir=opts["profile_dir"],
            headless=opts["headless"],
            driver_manager=opts["driver_manager"],
            download_dir=str(images_dir),
            delay=opts["delay"],
            response_timeout=opts["response_timeout"],
            progress_cb=_progress_cb(job_id),
            should_stop=_should_stop(job_id),
        )
        total_images = sum(len(r["images"]) for r in results)
        _update_job(
            job_id, status="done", progress=100,
            message=f"완료! 프롬프트 {len(results)}개 · 이미지 {total_images}장",
            results=results,
        )
    except Exception as e:
        _update_job(job_id, status="error", message=str(e))


def _parse_prompts(form, files) -> list:
    prompts = []
    text = (form.get("prompts") or "").strip()
    if text:
        prompts.extend([line.strip() for line in text.splitlines() if line.strip()])

    f = files.get("prompts_file")
    if f and f.filename:
        content = f.read().decode("utf-8", errors="ignore")
        prompts.extend([line.strip() for line in content.splitlines() if line.strip()])

    return prompts


# ─── 라우트 ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("gemini.html")


@app.route("/start", methods=["POST"])
def start():
    prompts = _parse_prompts(request.form, request.files)
    if not prompts:
        return jsonify({"error": "프롬프트를 1개 이상 입력하거나 파일을 업로드해주세요."}), 400

    form = request.form
    opts = {
        "profile_dir": form.get("profile_dir", "gemini_chrome_profile") or "gemini_chrome_profile",
        "headless": form.get("headless") == "on",
        "driver_manager": form.get("driver_manager", "auto"),
        "delay": float(form.get("delay", 5.0)),
        "response_timeout": float(form.get("response_timeout", 180.0)),
    }

    job_id = uuid.uuid4().hex[:10]
    (JOB_DIR / job_id).mkdir(parents=True, exist_ok=True)

    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "queued", "progress": 0, "message": "대기 중...",
            "log": [], "results": None, "stop_requested": False,
            "prompt_count": len(prompts),
        }

    t = threading.Thread(target=_run_job, args=(job_id, prompts, opts), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/stop/<job_id>", methods=["POST"])
def stop(job_id: str):
    if job_id not in JOBS:
        return jsonify({"error": "not found"}), 404
    _update_job(job_id, stop_requested=True)
    return jsonify({"ok": True})


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
                final = {"pct": job["progress"], "msg": job["message"], "status": job["status"]}
                yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
                break
            time.sleep(0.4)

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/image/<job_id>/<path:filename>")
def image(job_id: str, filename: str):
    path = JOB_DIR / job_id / "images" / filename
    if not path.exists():
        return jsonify({"error": "없음"}), 404
    return send_file(path)


@app.route("/download_zip/<job_id>")
def download_zip(job_id: str):
    images_dir = JOB_DIR / job_id / "images"
    if not images_dir.exists() or not any(images_dir.iterdir()):
        return jsonify({"error": "다운로드할 이미지가 없습니다."}), 404
    zip_base = JOB_DIR / job_id / "gemini_images"
    zip_path = shutil.make_archive(str(zip_base), "zip", images_dir)
    return send_file(zip_path, as_attachment=True, download_name="gemini_images.zip")


if __name__ == "__main__":
    import webbrowser
    port = int(os.environ.get("PORT", 5001))
    print(f"\n  Gemini 이미지 프롬프트 자동화 UI")
    print(f"  http://localhost:{port}\n")
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
