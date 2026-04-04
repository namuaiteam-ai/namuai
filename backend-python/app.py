#!/usr/bin/env python3
"""
네이버 뉴스 실시간 크롤러 - Flask 웹 UI
실행: python app.py
접속: http://localhost:5000
"""

import json
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from crawler import NAVER_RSS_FEEDS, CrawlerEngine

app = Flask(__name__)

# ─── 크롤러 초기화 ────────────────────────────────────────────────────────────

DEFAULT_CATEGORIES = ["속보", "정치", "경제", "사회", "IT/과학"]
POLL_INTERVAL      = int(os.environ.get("POLL_INTERVAL", 60))

# SSE 구독자 큐 목록
_subscribers: list[list] = []


def _broadcast(article: dict):
    """새 기사를 모든 SSE 구독자에게 전달."""
    for q in _subscribers:
        q.append(article)


engine = CrawlerEngine(
    categories=DEFAULT_CATEGORIES,
    interval=POLL_INTERVAL,
    on_article=_broadcast,
)
engine.start()

# ─── 라우트 ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template(
        "index.html",
        categories=list(NAVER_RSS_FEEDS.keys()),
        active=engine.categories,
        interval=engine.interval,
    )


@app.route("/api/info")
def api_info():
    return jsonify(engine.info())


@app.route("/api/articles")
def api_articles():
    category = request.args.get("category") or None
    limit    = int(request.args.get("limit", 50))
    offset   = int(request.args.get("offset", 0))
    return jsonify(engine.get_articles(category=category, limit=limit, offset=offset))


@app.route("/api/crawl", methods=["POST"])
def api_crawl():
    """즉시 크롤링 트리거."""
    n = engine.crawl_now()
    return jsonify({"new": n, "total": engine.total_count})


@app.route("/api/settings", methods=["POST"])
def api_settings():
    """카테고리·폴링 간격 변경."""
    data = request.get_json(force=True)
    cats     = data.get("categories")
    interval = data.get("interval")

    if cats and isinstance(cats, list):
        engine.categories = [c for c in cats if c in NAVER_RSS_FEEDS]
    if interval and isinstance(interval, int) and interval >= 10:
        engine.interval = interval

    return jsonify(engine.info())


@app.route("/stream")
def stream():
    """Server-Sent Events — 새 기사를 실시간으로 푸시."""
    queue: list = []
    _subscribers.append(queue)

    def generate():
        import time
        try:
            # 최근 20개 기사 먼저 전송
            for a in engine.get_articles(limit=20):
                yield f"data: {json.dumps(a, ensure_ascii=False)}\n\n"

            while True:
                if queue:
                    article = queue.pop(0)
                    yield f"data: {json.dumps(article, ensure_ascii=False)}\n\n"
                else:
                    # heartbeat (연결 유지)
                    yield ": ping\n\n"
                    time.sleep(1)
        finally:
            _subscribers.remove(queue)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":   "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":      "keep-alive",
        },
    )


# ─── 진입점 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import webbrowser
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  네이버 뉴스 실시간 크롤러 UI")
    print(f"  http://localhost:{port}\n")
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
