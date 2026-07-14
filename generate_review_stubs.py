"""
Generate stub bio articles for all unreviewed creators.

Creates content/articles/{slug}.md for every YouTuber in data/youtubers.json
that doesn't already have a review.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import youtuber_store

ARTICLES_DIR = Path(__file__).parent / "content" / "articles"
ARTICLES_DIR.mkdir(parents=True, exist_ok=True)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def generate_stub_content(y: dict) -> str:
    name = y.get("name", "")
    youtube = y.get("youtube_url") or ""
    mastodon = y.get("mastodon_url") or "None"
    bluesky = y.get("bluesky_url") or "None"
    stack = y.get("tech_stack", "general")
    subs = y.get("subscribers") or "Unknown"
    desc = y.get("description") or "TODO: Add creator description."

    return f"""Title: Creator Profile: {name}
Date: 2026-06-20
Category: Reviews
Slug: {y.get('review_slug') or slugify(name)}
Tech_Stack: {stack}
Summary: Profile and links for {name}, a YouTube creator specializing in {stack}.

## Creator Overview

- **YouTube Channel**: <a href="{youtube}" target="_blank" rel="noopener noreferrer">{youtube}</a>
- **Mastodon Profile**: {mastodon if mastodon == "None" else f'<a href="{mastodon}" target="_blank" rel="noopener noreferrer">{mastodon}</a>'}
- **Bluesky Profile**: {bluesky if bluesky == "None" else f'<a href="{bluesky}" target="_blank" rel="noopener noreferrer">{bluesky}</a>'}
- **Primary Tech Stack**: `{stack}`
- **Subscribers**: {subs}

---

## Channel Profile

{desc}

### Focus Areas
- TODO: Add specific tech focus (e.g., frontend frameworks, system design, lo-fi coding).
- TODO: Add typical video formats (e.g., coding vlogs, speedruns, tutorials).

### Popular Content / Recommendations
- TODO: Add links to 1-2 highly recommended videos or playlists.
- TODO: Add notable projects or community work.

### Why Follow Them?
- TODO: Add why someone should follow them on Mastodon or Bluesky (e.g., frequent updates, tech discussions, memes, tips).
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate YouTuber review stubs")
    parser.add_argument("--dry-run", action="store_true", help="Print stubs without writing")
    parser.add_argument("--overwrite", action="store_true", help="Force overwrite existing stub files")
    args = parser.parse_args()

    youtubers = youtuber_store.load()
    print(f"Loaded {len(youtubers)} YouTubers")

    created = 0
    for y in youtubers:
        slug = y.get("review_slug") or slugify(y.get("name", ""))
        # Set review_slug if not set
        if not y.get("review_slug"):
            y["review_slug"] = slug

        file_path = ARTICLES_DIR / f"{slug}.md"
        if file_path.exists() and not args.overwrite:
            continue

        content = generate_stub_content(y)
        if args.dry_run:
            print(f"\n--- Would write {file_path} ---")
            print(content[:200] + "...")
        else:
            file_path.write_text(content, encoding="utf-8")
            print(f"Created stub for {y.get('name')} at {file_path}")
            created += 1

    # Save to update any new review_slug values
    if not args.dry_run:
        youtuber_store.save(youtubers)
        print(f"Saved database updates. Created {created} stubs.")


if __name__ == "__main__":
    main()
