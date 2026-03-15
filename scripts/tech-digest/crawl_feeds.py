#!/usr/bin/env python3
"""RSS 피드에서 새 아티클을 수집하여 queue.json에 추가한다."""

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import feedparser
import yaml


SCRIPT_DIR = Path(__file__).parent
FEEDS_FILE = SCRIPT_DIR / "feeds.yaml"
QUEUE_FILE = SCRIPT_DIR / "queue.json"
HISTORY_FILE = SCRIPT_DIR / "history.json"


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:80].strip("-")


def load_json(path: Path) -> list:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def save_json(path: Path, data: list):
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_known_urls(queue: list, history: list) -> set:
    return {item["url"] for item in queue} | {item["url"] for item in history}


def parse_feed(feed_config: dict, cutoff: datetime, known_urls: set) -> list:
    articles = []
    print(f"  Fetching: {feed_config['name']} ...")
    try:
        feed = feedparser.parse(feed_config["url"])
        for entry in feed.entries:
            url = entry.get("link", "")
            if not url or url in known_urls:
                continue

            published = None
            for date_field in ("published_parsed", "updated_parsed"):
                t = entry.get(date_field)
                if t:
                    published = datetime(*t[:6], tzinfo=timezone.utc)
                    break

            if published and published < cutoff:
                continue

            title = entry.get("title", "Untitled")
            articles.append({
                "title": title,
                "url": url,
                "source": feed_config["name"],
                "tag": feed_config["tag"],
                "slug": slugify(title),
                "published": published.isoformat() if published else datetime.now(timezone.utc).isoformat(),
                "queued_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        print(f"    [ERROR] {feed_config['name']}: {e}")
    return articles


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1, help="최근 N일 이내 글만 수집")
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    with open(FEEDS_FILE) as f:
        config = yaml.safe_load(f)

    queue = load_json(QUEUE_FILE)
    history = load_json(HISTORY_FILE)
    known_urls = get_known_urls(queue, history)

    print(f"[crawl_feeds] cutoff={cutoff.isoformat()}, known_urls={len(known_urls)}")

    new_articles = []
    for feed_config in config["feeds"]:
        articles = parse_feed(feed_config, cutoff, known_urls)
        new_articles.extend(articles)

    if new_articles:
        queue.extend(new_articles)
        save_json(QUEUE_FILE, queue)
        print(f"\n[crawl_feeds] {len(new_articles)}개 새 아티클 추가됨:")
        for a in new_articles:
            print(f"  - [{a['source']}] {a['title']}")
    else:
        save_json(QUEUE_FILE, queue)
        print("\n[crawl_feeds] 새 글 없음")


if __name__ == "__main__":
    main()
