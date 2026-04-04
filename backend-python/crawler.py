#!/usr/bin/env python3
"""
실시간 네이버 뉴스 크롤러
실행: python crawler.py
종료: Ctrl+C
"""

import time
import json
import hashlib
import signal
import sys
from datetime import datetime
from pathlib import Path

try:
    import feedparser
except ImportError:
    print("feedparser 설치 필요: pip install feedparser")
    sys.exit(1)

# ─── 설정 ────────────────────────────────────────────────────────────────────

POLL_INTERVAL = 60          # 폴링 간격 (초), 환경변수 POLL_INTERVAL로 덮어쓰기 가능
SAVE_TO_FILE  = True        # True이면 articles.json에 결과 저장
OUTPUT_FILE   = "articles.json"

NAVER_RSS_FEEDS = {
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

# 크롤링할 카테고리 목록 (None 이면 전체)
ACTIVE_CATEGORIES = ["속보", "정치", "경제", "사회", "IT/과학"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ─── 상태 ────────────────────────────────────────────────────────────────────

seen_ids:    set[str]  = set()
articles_db: list[dict] = []
running = True


def _signal_handler(sig, frame):
    global running
    print("\n\n크롤러 종료 중...")
    running = False


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# ─── 핵심 함수 ────────────────────────────────────────────────────────────────

def _make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def _parse_pub_time(entry) -> str:
    if getattr(entry, "published_parsed", None):
        try:
            return datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fetch_rss(category: str, url: str) -> list[dict]:
    """RSS 피드를 파싱해 새 기사만 반환."""
    try:
        feed = feedparser.parse(url, request_headers=HEADERS)
        if feed.bozo and not feed.entries:
            raise ValueError(feed.bozo_exception)

        new_articles = []
        for entry in feed.entries:
            link = entry.get("link") or entry.get("id", "")
            article_id = _make_id(link)
            if article_id in seen_ids:
                continue

            source = "네이버뉴스"
            if hasattr(entry, "source") and isinstance(entry.source, dict):
                source = entry.source.get("title", source)

            summary = entry.get("summary", "")
            # HTML 태그 간단 제거
            import re
            summary = re.sub(r"<[^>]+>", "", summary).strip()

            new_articles.append({
                "id":         article_id,
                "category":   category,
                "title":      entry.get("title", "").strip(),
                "link":       link,
                "summary":    summary[:300],
                "published":  _parse_pub_time(entry),
                "source":     source,
                "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

        return new_articles

    except Exception as e:
        print(f"  [오류] {category} RSS 파싱 실패: {e}")
        return []


def print_article(article: dict):
    """기사 한 건을 콘솔에 출력."""
    divider = "─" * 60
    print(f"\n{divider}")
    print(f"  [{article['category']}]  {article['published']}  |  {article['source']}")
    print(f"  {article['title']}")
    print(f"  {article['link']}")
    if article["summary"]:
        preview = article["summary"][:120].replace("\n", " ")
        print(f"  {preview}{'...' if len(article['summary']) > 120 else ''}")
    print(divider)


def save_articles():
    if not SAVE_TO_FILE:
        return
    output_path = Path(__file__).parent / OUTPUT_FILE
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(articles_db, f, ensure_ascii=False, indent=2)


def crawl_once():
    """카테고리 전체를 한 번 크롤링."""
    now = datetime.now().strftime("%H:%M:%S")
    categories = ACTIVE_CATEGORIES or list(NAVER_RSS_FEEDS.keys())
    print(f"\n[{now}] 크롤링 시작 ({len(categories)}개 카테고리)...")

    new_count = 0
    for category in categories:
        url = NAVER_RSS_FEEDS.get(category)
        if not url:
            print(f"  [경고] '{category}' 카테고리 URL 없음, 건너뜀")
            continue

        articles = fetch_rss(category, url)
        for article in articles:
            seen_ids.add(article["id"])
            articles_db.append(article)
            print_article(article)
            new_count += 1

    if new_count:
        save_articles()
        print(f"\n  → 새 기사 {new_count}개 발견 (누적 {len(articles_db)}개)")
    else:
        print(f"  → 새 기사 없음 (누적 {len(articles_db)}개)")

# ─── 진입점 ──────────────────────────────────────────────────────────────────

def main():
    interval = int(__import__("os").environ.get("POLL_INTERVAL", POLL_INTERVAL))

    print("=" * 60)
    print("  실시간 네이버 뉴스 크롤러")
    print(f"  폴링 간격 : {interval}초")
    cats = ACTIVE_CATEGORIES or list(NAVER_RSS_FEEDS.keys())
    print(f"  카테고리  : {', '.join(cats)}")
    if SAVE_TO_FILE:
        print(f"  저장 파일 : {Path(__file__).parent / OUTPUT_FILE}")
    print("  종료      : Ctrl+C")
    print("=" * 60)

    while running:
        crawl_once()
        if not running:
            break
        print(f"\n  다음 크롤링까지 {interval}초 대기 중... (Ctrl+C로 종료)")
        for _ in range(interval):
            if not running:
                break
            time.sleep(1)

    print(f"\n총 {len(articles_db)}개 기사 수집 완료.")
    if SAVE_TO_FILE and articles_db:
        save_articles()
        print(f"결과 저장: {Path(__file__).parent / OUTPUT_FILE}")


if __name__ == "__main__":
    main()
