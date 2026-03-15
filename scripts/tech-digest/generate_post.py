#!/usr/bin/env python3
"""마크다운 본문으로부터 Hugo 포스트를 생성한다."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True, help="포스트 slug (파일명에 사용)")
    parser.add_argument("--title", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--url", required=True, help="원본 URL")
    parser.add_argument("--body", help="마크다운 본문 파일 경로 (미지정 시 stdin)")
    parser.add_argument("--repo-root", required=True)
    args = parser.parse_args()

    if args.body:
        body = Path(args.body).read_text(encoding="utf-8")
    else:
        body = sys.stdin.read()

    repo = Path(args.repo_root)
    post_path = repo / "content" / "posts" / f"tech-digest-{args.slug}.md"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+09:00")

    content = f"""---
title: "[Tech Digest] {args.title}"
date: {now}
summary: "{args.source}의 기술 아티클을 한국어로 해설합니다"
tags: ["tech-digest", "{args.tag}"]
categories: ["Tech Digest"]
series: ["Tech Digest"]
draft: false
mermaid: true
---

> 원문: [{args.source}]({args.url})

{body.strip()}

---

*이 글은 [{args.source}]({args.url})의 내용을 바탕으로 재구성한 해설입니다.*
"""

    post_path.write_text(content, encoding="utf-8")
    print(f"[generate_post] Created: {post_path}")


if __name__ == "__main__":
    main()
