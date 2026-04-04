#!/usr/bin/env python3
"""
NewFinder 뉴스 크롤러 - Flask 웹 UI
실행: python app.py
접속: http://localhost:5000
"""

import json
import os
import sqlite3
import threading
import time
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from crawler import DB_PATH, init_db, run_all

app = Flask(__name__)

# ─── 설정 ─────────────────────────────────────────────────────────────────────

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 10 * 60))  # 기본 10분

SOURCES = ["kbs", "mbc", "ytн", "sbs", "yonhap", "daum"]
CATEGORIES = ["정치", "경제", "사회", "세계", "연예", "스포츠", "일반"]

# ─── 상태 ─────────────────────────────────────────────────────────────────────

_state = {
    "last_crawl":  None,
    "last_new":    0,
    "total":       0,
    "is_crawling": False,
}
_state_lock = threading.Lock()

# SSE 구독자 큐 (새 기사 전달용)
_subscribers: list[list] = []


def _broadcast(articles: list[dict]):
    for q in _subscribers:
        for a in articles:
            q.append(a)


# ─── 크롤러 백그라운드 스레드 ─────────────────────────────────────────────────

def _get_latest_ids() -> set:
    """현재 DB의 url_hash 전체 반환 (크롤 전 스냅샷용)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT url_hash FROM articles").fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


def _fetch_new_articles(before_ids: set) -> list[dict]:
    """크롤 후 새로 추가된 기사 목록 반환."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, title, category, source, url, published_at, views, comments
            FROM articles
            ORDER BY id DESC
            LIMIT 100
        """).fetchall()
        conn.close()
        new = []
        for r in rows:
            if r["url_hash"] if "url_hash" in r.keys() else None:
                pass
            new.append(dict(r))
        # url_hash 없이 id 기반 필터
        conn2 = sqlite3.connect(DB_PATH)
        conn2.row_factory = sqlite3.Row
        all_hashes = {rr[0] for rr in conn2.execute("SELECT url_hash FROM articles").fetchall()}
        new_hashes = all_hashes - before_ids
        if not new_hashes:
            conn2.close()
            return []
        placeholders = ",".join("?" * len(new_hashes))
        rows2 = conn2.execute(f"""
            SELECT id, title, category, source, url, published_at, views, comments, url_hash
            FROM articles
            WHERE url_hash IN ({placeholders})
            ORDER BY id DESC
        """, list(new_hashes)).fetchall()
        conn2.close()
        return [dict(r) for r in rows2]
    except Exception as e:
        print(f"[app] 새 기사 조회 오류: {e}")
        return []


def _crawler_loop():
    """백그라운드 크롤러 루프."""
    while True:
        with _state_lock:
            _state["is_crawling"] = True

        before = _get_latest_ids()
        try:
            run_all()
        except Exception as e:
            print(f"[app] 크롤링 오류: {e}")

        new_articles = _fetch_new_articles(before)

        with _state_lock:
            _state["last_crawl"]  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _state["last_new"]    = len(new_articles)
            _state["is_crawling"] = False
            _state["total"]       = _count_total()

        if new_articles:
            _broadcast(new_articles)

        time.sleep(POLL_INTERVAL)


def _count_total() -> int:
    try:
        conn = sqlite3.connect(DB_PATH)
        n = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


# ─── 초기화 ───────────────────────────────────────────────────────────────────

init_db()
with _state_lock:
    _state["total"] = _count_total()

_t = threading.Thread(target=_crawler_loop, daemon=True)
_t.start()

# ─── DB 조회 헬퍼 ─────────────────────────────────────────────────────────────

def query_articles(
    category: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        where, params = [], []

        if category:
            where.append("category = ?")
            params.append(category)
        if source:
            where.append("source = ?")
            params.append(source)
        if keyword:
            where.append("title LIKE ?")
            params.append(f"%{keyword}%")

        sql = "SELECT id, title, category, source, url, published_at, views, comments FROM articles"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY published_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]

        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[app] 조회 오류: {e}")
        return []


# ─── 라우트 ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html",
                           categories=CATEGORIES,
                           sources=SOURCES,
                           interval=POLL_INTERVAL)


@app.route("/api/info")
def api_info():
    with _state_lock:
        info = dict(_state)
    return jsonify(info)


@app.route("/api/articles")
def api_articles():
    cat     = request.args.get("category") or None
    src     = request.args.get("source")   or None
    kw      = request.args.get("q")        or None
    limit   = int(request.args.get("limit",  50))
    offset  = int(request.args.get("offset", 0))
    articles = query_articles(cat, src, kw, limit, offset)
    return jsonify(articles)


@app.route("/api/crawl", methods=["POST"])
def api_crawl():
    """즉시 크롤링 트리거 (별도 스레드)."""
    with _state_lock:
        if _state["is_crawling"]:
            return jsonify({"message": "이미 크롤링 중입니다."}), 409

    def _once():
        with _state_lock:
            _state["is_crawling"] = True
        before = _get_latest_ids()
        try:
            run_all()
        except Exception as e:
            print(f"[crawl_now] {e}")
        new_articles = _fetch_new_articles(before)
        with _state_lock:
            _state["last_crawl"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _state["last_new"]   = len(new_articles)
            _state["is_crawling"] = False
            _state["total"]      = _count_total()
        if new_articles:
            _broadcast(new_articles)

    threading.Thread(target=_once, daemon=True).start()
    return jsonify({"message": "크롤링 시작됨"})


@app.route("/stream")
def stream():
    """Server-Sent Events — 새 기사 실시간 푸시."""
    queue: list = []
    _subscribers.append(queue)

    def generate():
        # 최근 30개 먼저 전송
        recent = query_articles(limit=30)
        for a in recent:
            yield f"data: {json.dumps(a, ensure_ascii=False)}\n\n"

        try:
            while True:
                if queue:
                    article = queue.pop(0)
                    yield f"data: {json.dumps(article, ensure_ascii=False)}\n\n"
                else:
                    yield ": ping\n\n"
                    time.sleep(1)
        finally:
            if queue in _subscribers:
                _subscribers.remove(queue)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ─── 진입점 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import webbrowser
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  NewFinder 뉴스 크롤러 UI")
    print(f"  http://localhost:{port}")
    print(f"  폴링 간격: {POLL_INTERVAL // 60}분\n")
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
