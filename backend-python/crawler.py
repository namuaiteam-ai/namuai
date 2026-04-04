#!/usr/bin/env python3
"""
네이버 뉴스 크롤러 엔진
- CLI 단독 실행: python crawler.py
- Flask 앱에서 import: from crawler import CrawlerEngine
"""

import hashlib
import json
import re
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable

try:
    import feedparser
except ImportError:
    print("feedparser 설치 필요: pip install feedparser")
    sys.exit(1)

# ─── 상수 ────────────────────────────────────────────────────────────────────

NAVER_RSS_FEEDS: dict[str, str] = {
    "속보":      "https://news.naver.com/main/rss/breaking.nhn",
    "정치":      "https://news.naver.com/main/rss/politics.nhn",
    "경제":      "https://news.naver.com/main/rss/economic.nhn",
    "사회":      "https://news.naver.com/main/rss/society.nhn",
    "생활/문화": "https://news.naver.com/main/rss/life.nhn",
    "세계":      "https://news.naver.com/main/rss/world.nhn",
    "IT/과학":   "https://news.naver.com/main/rss/it.nhn",
    "연예":      "https://news.naver.com/main/rss/entertain.nhn",
    "스포츠":    "https://news.naver.com/main/rss/sports.nhn",
}

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ─── 엔진 ────────────────────────────────────────────────────────────────────

class CrawlerEngine:
    """RSS 폴링 크롤러 엔진.

    Parameters
    ----------
    categories:
        크롤링할 카테고리 이름 목록. None 이면 전체.
    interval:
        폴링 간격(초).
    on_article:
        새 기사가 발견될 때마다 호출되는 콜백 ``(article: dict) -> None``.
    """

    def __init__(
        self,
        categories: list[str] | None = None,
        interval: int = 60,
        on_article: Callable[[dict], None] | None = None,
    ):
        self.categories  = categories or list(NAVER_RSS_FEEDS.keys())
        self.interval    = interval
        self.on_article  = on_article

        self._seen:     set[str]   = set()
        self._articles: list[dict] = []
        self._lock      = Lock()
        self._stop_evt  = Event()
        self._thread: Thread | None = None

        # 상태
        self.last_crawl: str | None  = None
        self.total_count: int        = 0
        self.status: str             = "idle"   # idle | running | stopped

    # ── 공개 메서드 ───────────────────────────────────────────────────────────

    def start(self):
        """백그라운드 스레드에서 폴링 시작."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.status = "running"

    def stop(self):
        """폴링 중단."""
        self._stop_evt.set()
        self.status = "stopped"

    def crawl_now(self) -> int:
        """즉시 한 번 크롤링 (동기). 새 기사 수 반환."""
        return self._crawl_once()

    def get_articles(
        self,
        category: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        with self._lock:
            items = self._articles
            if category:
                items = [a for a in items if a["category"] == category]
            # 최신순
            items = list(reversed(items))
            return items[offset : offset + limit]

    def info(self) -> dict:
        return {
            "status":      self.status,
            "total":       self.total_count,
            "last_crawl":  self.last_crawl,
            "interval":    self.interval,
            "categories":  self.categories,
        }

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop_evt.is_set():
            self._crawl_once()
            self._stop_evt.wait(timeout=self.interval)

    def _crawl_once(self) -> int:
        self.last_crawl = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_count = 0
        for cat in self.categories:
            url = NAVER_RSS_FEEDS.get(cat)
            if not url:
                continue
            for article in self._fetch_rss(cat, url):
                with self._lock:
                    self._seen.add(article["id"])
                    self._articles.append(article)
                    self.total_count += 1
                new_count += 1
                if self.on_article:
                    self.on_article(article)
        return new_count

    def _fetch_rss(self, category: str, url: str) -> list[dict]:
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": _UA})
            if feed.bozo and not feed.entries:
                raise ValueError(feed.bozo_exception)

            results = []
            for entry in feed.entries:
                link = entry.get("link") or entry.get("id", "")
                aid  = hashlib.md5(link.encode()).hexdigest()
                if aid in self._seen:
                    continue

                pub = ""
                if getattr(entry, "published_parsed", None):
                    try:
                        pub = datetime(*entry.published_parsed[:6]).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    except Exception:
                        pass
                pub = pub or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                source = "네이버뉴스"
                if hasattr(entry, "source") and isinstance(entry.source, dict):
                    source = entry.source.get("title", source)

                summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()

                results.append({
                    "id":         aid,
                    "category":   category,
                    "title":      entry.get("title", "").strip(),
                    "link":       link,
                    "summary":    summary[:300],
                    "published":  pub,
                    "source":     source,
                    "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
            return results

        except Exception as e:
            print(f"  [오류] {category}: {e}")
            return []


# ─── CLI 진입점 ───────────────────────────────────────────────────────────────

def _cli():
    import os

    interval   = int(os.environ.get("POLL_INTERVAL", 60))
    categories = os.environ.get("CATEGORIES", "").split(",") if os.environ.get("CATEGORIES") else None
    save_file  = Path(__file__).parent / "articles.json"

    def on_article(a: dict):
        print(f"\n{'─'*60}")
        print(f"  [{a['category']}] {a['published']} | {a['source']}")
        print(f"  {a['title']}")
        print(f"  {a['link']}")
        if a["summary"]:
            print(f"  {a['summary'][:120]}{'...' if len(a['summary'])>120 else ''}")
        print("─" * 60)

    engine = CrawlerEngine(
        categories=categories,
        interval=interval,
        on_article=on_article,
    )

    print("=" * 60)
    print("  실시간 네이버 뉴스 크롤러")
    print(f"  폴링 간격 : {interval}초")
    print(f"  카테고리  : {', '.join(engine.categories)}")
    print(f"  저장 파일 : {save_file}")
    print("  종료      : Ctrl+C")
    print("=" * 60)

    running = True

    def _stop(sig, frame):
        nonlocal running
        print("\n\n크롤러 종료 중...")
        running = False

    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    while running:
        now = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{now}] 크롤링 시작...")
        n = engine.crawl_now()
        print(f"  → 새 기사 {n}개 (누적 {engine.total_count}개)")

        if engine.total_count:
            with open(save_file, "w", encoding="utf-8") as f:
                json.dump(engine.get_articles(limit=10000), f, ensure_ascii=False, indent=2)

        if not running:
            break
        print(f"  다음 크롤링까지 {interval}초 대기... (Ctrl+C로 종료)")
        for _ in range(interval):
            if not running:
                break
            time.sleep(1)

    print(f"\n총 {engine.total_count}개 기사 수집 완료.")


if __name__ == "__main__":
    _cli()
