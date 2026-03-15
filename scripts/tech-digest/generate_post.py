#!/usr/bin/env python3
"""시각화 HTML로부터 Hugo 포스트를 생성한다."""

import argparse
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True, help="시각화 HTML 상대 경로 (static/ 기준)")
    parser.add_argument("--title", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--url", required=True, help="원본 URL")
    parser.add_argument("--repo-root", required=True)
    args = parser.parse_args()

    repo = Path(args.repo_root)
    slug = Path(args.html).stem
    post_path = repo / "content" / "posts" / f"tech-digest-{slug}.md"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+09:00")
    html_url = f"/{args.html}"

    content = f"""---
title: "[테크 다이제스트] {args.title}"
date: {now}
summary: "{args.source}의 기술 아티클을 시각적으로 해설합니다"
tags: ["tech-digest", "{args.tag}"]
categories: ["Tech Digest"]
series: ["테크 다이제스트"]
draft: false
---

> 원문: [{args.source}]({args.url})

이 글은 **{args.source}**에서 발행된 기술 아티클을 시각적으로 해설한 콘텐츠입니다.

{{{{< rawhtml >}}}}
<iframe src="{html_url}" style="width:100%;height:80vh;border:none;border-radius:8px;" loading="lazy"></iframe>
{{{{< /rawhtml >}}}}

---

📎 [원문 보기]({args.url}) | 🗂️ 시리즈: 테크 다이제스트
"""

    post_path.write_text(content, encoding="utf-8")
    print(f"[generate_post] Created: {post_path}")

    # Ensure rawhtml shortcode exists
    shortcode_dir = repo / "layouts" / "shortcodes"
    shortcode_dir.mkdir(parents=True, exist_ok=True)
    rawhtml_path = shortcode_dir / "rawhtml.html"
    if not rawhtml_path.exists():
        rawhtml_path.write_text("{{ .Inner }}", encoding="utf-8")
        print(f"[generate_post] Created rawhtml shortcode: {rawhtml_path}")


if __name__ == "__main__":
    main()
