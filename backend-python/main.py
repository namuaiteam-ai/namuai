import os, math, time, json, asyncio, sys
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

DB_PATH  = "d:/newfinder/database/newfinder.db"
API_PORT = int(os.getenv("PYTHON_PORT", 8000))

Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="NewFinder API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# 템플릿 디렉터리 (index.html 서빙)
TEMPLATE_DIR = Path(__file__).parent / "templates"

# ─── SSE 브로드캐스트 ──────────────────────────────────────────────────────────

_sse_queues: list[asyncio.Queue] = []


async def _broadcast(articles: list[dict]):
    for q in _sse_queues:
        for a in articles:
            await q.put(a)

# ─── DB ───────────────────────────────────────────────────────────────────────

def calc_score(views, comments, published_at):
    raw       = views * 0.4 + comments * 0.6
    hours_ago = (time.time() * 1000 - published_at) / 3600000
    decay     = 1 / (1 + math.pow(hours_ago / 12, 1.5))
    return round(raw * decay, 2), round(decay * 100)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                title        TEXT    NOT NULL,
                category     TEXT    NOT NULL DEFAULT 'general',
                views        INTEGER NOT NULL DEFAULT 0,
                comments     INTEGER NOT NULL DEFAULT 0,
                published_at INTEGER NOT NULL,
                created_at   INTEGER NOT NULL DEFAULT (unixepoch('now') * 1000),
                url          TEXT,
                source       TEXT,
                url_hash     TEXT UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_published ON articles(published_at DESC);
        """)
        cursor = await conn.execute("PRAGMA table_info(articles)")
        existing_cols = {row[1] for row in await cursor.fetchall()}
        for col, ddl in [("url", 'TEXT DEFAULT ""'), ("source", 'TEXT DEFAULT ""'), ("url_hash", "TEXT")]:
            if col not in existing_cols:
                await conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {ddl}")
        await conn.commit()


async def _get_all_hashes() -> set:
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute("SELECT url_hash FROM articles WHERE url_hash IS NOT NULL")
        return {r[0] for r in await cur.fetchall()}


async def _fetch_by_hashes(hashes: set) -> list[dict]:
    if not hashes:
        return []
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        placeholders = ",".join("?" * len(hashes))
        cur = await conn.execute(
            f"SELECT id,title,category,source,url,published_at,views,comments "
            f"FROM articles WHERE url_hash IN ({placeholders}) ORDER BY published_at DESC",
            list(hashes),
        )
        return [dict(r) for r in await cur.fetchall()]

# ─── 크론 작업 ────────────────────────────────────────────────────────────────

async def simulate_update():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            UPDATE articles
            SET views    = views    + ABS(RANDOM() % 800 + 50),
                comments = comments + ABS(RANDOM() % 80  + 2)
        """)
        await conn.commit()
    print("[CRON] stats updated")


async def run_crawler_job():
    print("[CRON] Starting crawler...")
    before = await _get_all_hashes()
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "crawler.py",
            cwd=str(Path(__file__).parent),
        )
        await process.communicate()
        print(f"[CRON] Crawler done (exit {process.returncode})")
    except Exception as e:
        print(f"[CRON] Crawler error: {e}")
        return

    after   = await _get_all_hashes()
    new_ids = after - before
    if new_ids:
        new_articles = await _fetch_by_hashes(new_ids)
        print(f"[CRON] 새 기사 {len(new_articles)}건 → SSE 브로드캐스트")
        await _broadcast(new_articles)


scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup():
    await init_db()
    scheduler.add_job(simulate_update,   "interval", minutes=1)
    scheduler.add_job(run_crawler_job,   "interval", minutes=10)
    scheduler.start()
    print(f"Python API  → http://localhost:{API_PORT}")
    print(f"Swagger UI  → http://localhost:{API_PORT}/docs")
    asyncio.create_task(run_crawler_job())


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()

# ─── UI 라우트 ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = TEMPLATE_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>templates/index.html 파일이 없습니다.</h2>")

# ─── SSE ──────────────────────────────────────────────────────────────────────

@app.get("/stream")
async def stream_articles():
    """새 기사를 Server-Sent Events로 실시간 푸시."""
    queue: asyncio.Queue = asyncio.Queue()
    _sse_queues.append(queue)

    # 최근 30개 먼저 전송
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT id,title,category,source,url,published_at,views,comments "
            "FROM articles ORDER BY published_at DESC LIMIT 30"
        )
        recent = [dict(r) for r in await cur.fetchall()]

    async def generator():
        for a in recent:
            yield f"data: {json.dumps(a, ensure_ascii=False)}\n\n"
        try:
            while True:
                try:
                    article = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(article, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            if queue in _sse_queues:
                _sse_queues.remove(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )

# ─── REST API ────────────────────────────────────────────────────────────────

@app.get("/api/articles")
async def get_articles(
    category: Optional[str] = Query(None),
    source:   Optional[str] = Query(None),
    q:        Optional[str] = Query(None),
    limit:    int           = Query(50, ge=1, le=200),
    offset:   int           = Query(0,  ge=0),
):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        where, params = [], []
        if category: where.append("category = ?"); params.append(category)
        if source:   where.append("source = ?");   params.append(source)
        if q:        where.append("title LIKE ?"); params.append(f"%{q}%")
        sql = ("SELECT id,title,category,source,url,published_at,views,comments FROM articles"
               + (" WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY published_at DESC LIMIT ? OFFSET ?")
        cur = await conn.execute(sql, params + [limit, offset])
        rows = [dict(r) for r in await cur.fetchall()]
    return {"ok": True, "data": rows, "count": len(rows)}


@app.get("/api/articles/top")
async def get_top(
    sort:     str           = Query("score", enum=["score", "views", "comments"]),
    limit:    int           = Query(10, ge=1, le=50),
    category: Optional[str] = Query(None),
):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        sql = "SELECT * FROM articles" + (" WHERE category = ?" if category else "")
        cur = await conn.execute(sql, (category,) if category else ())
        rows = [dict(r) for r in await cur.fetchall()]
    for r in rows:
        r["score"], r["decay_pct"] = calc_score(r["views"], r["comments"], r["published_at"])
    key = {"score": lambda x: x["score"], "views": lambda x: x["views"], "comments": lambda x: x["comments"]}
    rows.sort(key=key[sort], reverse=True)
    return {"ok": True, "data": rows[:limit]}


@app.get("/api/articles/{article_id}")
async def get_article(article_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("UPDATE articles SET views = views + 1 WHERE id = ?", (article_id,))
        await conn.commit()
        cur = await conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    r = dict(row)
    r["score"], r["decay_pct"] = calc_score(r["views"], r["comments"], r["published_at"])
    return {"ok": True, "data": r}


@app.post("/api/articles", status_code=201)
async def create_article(body: BaseModel):
    pub = getattr(body, "published_at", None) or int(time.time() * 1000)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO articles (title,category,views,comments,published_at) VALUES (?,?,?,?,?)",
            (body.title, body.category, body.views, body.comments, pub),
        )
        await conn.commit()
    return {"ok": True}


@app.post("/api/crawl")
async def trigger_crawl():
    """즉시 크롤링 트리거."""
    asyncio.create_task(run_crawler_job())
    return {"ok": True, "message": "크롤링 시작됨"}


@app.get("/api/stats")
async def get_stats():
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("""
            SELECT COUNT(*) AS total_articles,
                   SUM(views) AS total_views,
                   SUM(comments) AS total_comments
            FROM articles
        """)
        row = dict(await cur.fetchone())
    return {"ok": True, "data": row}
