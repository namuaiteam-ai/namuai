from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import subprocess
import os

app = Flask(__name__)
CORS(app)

# Absolute path to the workplace
BASE_DIR = 'd:/ttttt2'
os.makedirs(os.path.join(BASE_DIR, 'video'), exist_ok=True)

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/mv')
def mv_page():
    return send_from_directory(BASE_DIR, 'mv.html')

@app.route('/video/<path:filename>')
def serve_video(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'video'), filename)

@app.route('/render', methods=['POST'])
def render_video():
    try:
        print("\n[HUB] New Production Request Received.")

        image_files = request.files.getlist('images')
        for i, file in enumerate(image_files[:6]):
            ext = os.path.splitext(file.filename)[1] or '.png'
            file.save(os.path.join(BASE_DIR, f"image{i+1}{ext}"))
            print(f" -> Saved Scene {i+1}: image{i+1}{ext}")

        if 'narration' in request.files:
            request.files['narration'].save(os.path.join(BASE_DIR, "narration.mp3"))
            print(" -> Saved Narration: narration.mp3")

        if 'subtitle' in request.files:
            request.files['subtitle'].save(os.path.join(BASE_DIR, "subtitle.srt"))
            print(" -> Saved Subtitles: subtitle.srt")

        if 'thumbnail' in request.files:
            request.files['thumbnail'].save(os.path.join(BASE_DIR, "thumbnail.jpg"))
            print(" -> Saved Thumbnail: thumbnail.jpg")

        print("[ENGINE] Launching Production...")

        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        env = os.environ.copy()
        env["SUB_FONT_SIZE"] = request.form.get('fontSize', '22')
        env["SUB_ALIGNMENT"] = request.form.get('subPos', '5')
        env["THUMB_TITLE"]   = request.form.get('thTitle', '')
        env["THUMB_DESC"]    = request.form.get('thDesc', '')

        result = subprocess.run(
            ["python", "make_video.py"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            cwd=BASE_DIR,
            env=env
        )

        if result.returncode == 0:
            print("[SUCCESS] Production Finished.")
            return jsonify({
                "status": "success",
                "log": result.stdout,
                "video_url": f"/video/{today}/output.mp4"
            })
        else:
            print("[ERROR] Engine Failure.")
            return jsonify({
                "status": "error",
                "log": result.stderr or result.stdout
            }), 500

    except Exception as e:
        print(f"[CRITICAL] Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── LRC 자동 변환 (무료, API 불필요) ─────────────────────────────────────────
def _auto_lrc(lines: list, duration: int, title: str) -> str:
    """가사 줄 목록 → LRC 형식 자동 생성 (등간격 타이밍)"""
    sec_per_line = duration / len(lines)
    current_ms   = 0
    parts = [f"[ti:{title}]", "[ar:뮤직비디오 뉴스]", ""]
    for line in lines:
        mm = int(current_ms // 60000)
        ss = int((current_ms % 60000) // 1000)
        cc = int((current_ms % 1000) // 10)
        parts.append(f"[{mm:02d}:{ss:02d}.{cc:02d}]{line}")
        current_ms += int(sec_per_line * 1000)
    return "\n".join(parts)


@app.route('/convert_lrc', methods=['POST'])
def convert_lrc():
    """가사 텍스트 → LRC 자동 변환 (무료)"""
    data        = request.get_json(force=True, silent=True) or {}
    lyrics_text = data.get("lyrics",   "").strip()
    duration    = int(data.get("duration", 60))
    title       = data.get("title",    "뮤직비디오 뉴스")

    if not lyrics_text:
        return jsonify({"error": "가사를 입력해주세요."}), 400

    # 빈 줄·섹션 태그([버스], [코러스] 등) 제외
    lines = [
        l.strip() for l in lyrics_text.splitlines()
        if l.strip() and not (l.strip().startswith("[") and l.strip().endswith("]"))
    ]
    if not lines:
        return jsonify({"error": "유효한 가사 줄이 없습니다."}), 400

    lrc = _auto_lrc(lines, duration, title)
    return jsonify({"lrc": lrc, "line_count": len(lines)})


# ─── 뮤직비디오 제작 ──────────────────────────────────────────────────────────
@app.route('/render_mv', methods=['POST'])
def render_mv():
    """수노 음악 + 사진 + LRC 가사 → 뮤직비디오 쇼츠"""
    try:
        print("\n[MV] New Music Video Request Received.")

        # 이미지 저장 (mv_image1.jpg, mv_image2.jpg, ...)
        image_files = request.files.getlist('images')
        if not image_files:
            return jsonify({"status": "error", "message": "이미지가 없습니다."}), 400

        img_names = []
        for i, file in enumerate(image_files[:6]):
            ext   = os.path.splitext(file.filename)[1] or '.jpg'
            fname = f"mv_image{i+1}{ext}"
            file.save(os.path.join(BASE_DIR, fname))
            img_names.append(fname)
            print(f" -> Saved: {fname}")

        # 음악 저장
        if 'music' not in request.files:
            return jsonify({"status": "error", "message": "음악 파일이 없습니다."}), 400
        request.files['music'].save(os.path.join(BASE_DIR, "music.mp3"))
        print(" -> Saved: music.mp3")

        # LRC 저장
        lrc_text = request.form.get("lrc_text", "")
        lrc_path = os.path.join(BASE_DIR, "lyrics.lrc")
        with open(lrc_path, "w", encoding="utf-8") as f:
            f.write(lrc_text)
        print(f" -> Saved: lyrics.lrc ({len(lrc_text)} bytes)")

        print("[MV] Launching Music Video Engine...")

        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        env = os.environ.copy()
        env["MV_IMAGES"]     = ",".join(img_names)
        env["MV_EFFECT"]     = request.form.get("effect",     "ken_burns")
        env["MV_FONT"]       = request.form.get("font",       "NanumGothic")
        env["MV_LYRIC_SIZE"] = request.form.get("lyric_size", "36")
        env["MV_LYRIC_GLOW"] = request.form.get("lyric_glow", "&H00B469FF")
        env["MV_TRANSITION"] = request.form.get("transition", "0.5")
        env["MV_WIDTH"]      = request.form.get("width",      "720")
        env["MV_HEIGHT"]     = request.form.get("height",     "1280")

        result = subprocess.run(
            ["python", "make_music_video.py"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=BASE_DIR,
            env=env
        )

        if result.returncode == 0:
            print("[MV] Success!")
            return jsonify({
                "status":    "success",
                "log":       result.stdout,
                "video_url": f"/video/{today}/mv_output.mp4"
            })
        else:
            print("[MV ERROR]", result.stderr[:500])
            return jsonify({
                "status": "error",
                "log":    result.stderr or result.stdout
            }), 500

    except Exception as e:
        print(f"[MV CRITICAL] {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    print("\n" + "="*50)
    print("  ShortsForge Hub PRO — Engine Hub Online  ")
    print("  Access Studio at: http://localhost:5000  ")
    print("="*50 + "\n")
    app.run(port=5000, host='0.0.0.0')
