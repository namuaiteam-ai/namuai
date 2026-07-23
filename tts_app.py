#!/usr/bin/env python3
"""
Supertonic 3 로컬 TTS 나레이션 생성 - 독립 웹 UI (영상 제작과 무관)
실행: python tts_app.py
접속: http://localhost:5001
"""

import os
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

import tts_supertonic

app = Flask(__name__)

OUTPUT_DIR = Path(os.environ.get("TTS_OUTPUT_DIR", "tts_output"))
OUTPUT_DIR.mkdir(exist_ok=True)


@app.route("/")
def index():
    voices = tts_supertonic.VOICE_STYLES + tts_supertonic.list_custom_voices()
    return render_template("tts_index.html", voices=voices,
                           builtin_voices=set(tts_supertonic.VOICE_STYLES))


@app.route("/generate", methods=["POST"])
def generate():
    if not tts_supertonic.is_available():
        return jsonify({
            "error": "Supertonic이 설치되어 있지 않습니다. 'pip install supertonic' 실행 후 다시 시도해주세요."
        }), 400

    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "대본을 입력해주세요."}), 400

    voice = data.get("voice", "F1")
    lang = data.get("lang", "ko")
    speed = float(data.get("speed", 1.05))
    with_subtitle = bool(data.get("with_subtitle", True))

    file_id = uuid.uuid4().hex[:10]
    out_path = OUTPUT_DIR / f"{file_id}.wav"
    srt_path = OUTPUT_DIR / f"{file_id}.srt"

    try:
        if with_subtitle:
            lines = tts_supertonic.split_script_lines(text)
            tts_supertonic.synthesize_with_srt(
                lines, out_path, srt_path, voice=voice, lang=lang, speed=speed)
        else:
            tts_supertonic.synthesize_to_file(text, out_path, voice=voice, lang=lang, speed=speed)
    except Exception as e:
        return jsonify({"error": f"음성 생성 실패: {e}"}), 400

    return jsonify({"file_id": file_id, "has_subtitle": with_subtitle and srt_path.exists()})


@app.route("/audio/<file_id>")
def audio(file_id: str):
    path = OUTPUT_DIR / f"{file_id}.wav"
    if not path.exists():
        return jsonify({"error": "파일 없음"}), 404
    return send_file(path, mimetype="audio/wav")


@app.route("/download/<file_id>")
def download(file_id: str):
    path = OUTPUT_DIR / f"{file_id}.wav"
    if not path.exists():
        return jsonify({"error": "파일 없음"}), 404
    return send_file(path, mimetype="audio/wav", as_attachment=True,
                      download_name="narration.wav")


@app.route("/subtitle/<file_id>")
def subtitle_download(file_id: str):
    path = OUTPUT_DIR / f"{file_id}.srt"
    if not path.exists():
        return jsonify({"error": "파일 없음"}), 404
    return send_file(path, mimetype="text/srt", as_attachment=True,
                      download_name="narration.srt")


if __name__ == "__main__":
    import webbrowser
    port = int(os.environ.get("PORT", 5001))
    print(f"\n  Supertonic 3 로컬 TTS 나레이션 생성기")
    print(f"  http://localhost:{port}\n")
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
