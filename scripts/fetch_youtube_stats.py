"""Populate YouTube channel statistics in data/youtubers.json.

Resolves every creator's ``UC...`` channel id (caching it back as
``youtube_channel_id`` so later runs skip the page scrape), then batch-fetches
subscriber/video/view counts from the YouTube Data API v3 and writes them onto
each record:

    youtube_channel_id, subscriber_count, hidden_subscriber_count,
    video_count, view_count, stats_fetched_at

The API key is read from ``YOUTUBE_API_KEY`` (loaded from a local ``.env`` if
present). Run with ``--dry-run`` to preview without writing.

Usage::

    uv run python scripts/fetch_youtube_stats.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import youtube_stats, youtuber_store

ENV_PATH = Path(__file__).parent.parent / ".env"


def load_env(path: Path = ENV_PATH) -> None:
    """Minimal ``.env`` loader (no python-dotenv dependency).

    Sets only keys that are not already present in the environment, so a real
    environment variable always wins over the file.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def resolve_ids(youtubers: list[dict]) -> tuple[int, int]:
    """Ensure each creator has a ``youtube_channel_id``; return (resolved, failed).

    Direct ``/channel/UC...`` URLs resolve locally; other shapes are scraped via
    the cached session in pipeline.youtube_feed. Already-cached ids are reused.
    """
    resolved = failed = 0
    for creator in youtubers:
        if creator.get("youtube_channel_id"):
            continue
        url = creator.get("primary_url") or creator.get("youtube_url")
        cid = youtube_stats.resolve_channel_id(url)
        if cid:
            creator["youtube_channel_id"] = cid
            resolved += 1
        else:
            failed += 1
            print(f"  ! could not resolve channel id: {creator.get('id')} ({url})")
    return resolved, failed


def apply_stats(youtubers: list[dict], stats: dict[str, youtube_stats.ChannelStats]) -> int:
    now = _dt.date.today().isoformat()
    updated = 0
    for creator in youtubers:
        cid = creator.get("youtube_channel_id")
        s = stats.get(cid) if cid else None
        if not s:
            continue
        creator["subscriber_count"] = s.subscriber_count
        creator["hidden_subscriber_count"] = s.hidden_subscriber_count
        creator["video_count"] = s.video_count
        creator["view_count"] = s.view_count
        creator["stats_fetched_at"] = now
        updated += 1
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Resolve and fetch but do not write")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N creators (testing)")
    args = parser.parse_args()

    load_env()
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("YOUTUBE_API_KEY is not set (checked environment and .env)", file=sys.stderr)
        return 2

    youtubers = youtuber_store.load()
    scope = youtubers[: args.limit] if args.limit else youtubers
    print(f"Loaded {len(youtubers)} creators; processing {len(scope)}")

    print("Resolving channel ids…")
    resolved, failed = resolve_ids(scope)
    print(f"  resolved {resolved} new, {failed} unresolved")

    channel_ids = [c["youtube_channel_id"] for c in scope if c.get("youtube_channel_id")]
    print(f"Fetching stats for {len(channel_ids)} channels (batches of {youtube_stats.MAX_IDS_PER_REQUEST})…")
    stats = youtube_stats.fetch_stats(channel_ids, api_key)
    print(f"  API returned stats for {len(stats)} channels")

    updated = apply_stats(scope, stats)
    print(f"Applied stats to {updated} creators")

    with_subs = sum(1 for c in scope if isinstance(c.get("subscriber_count"), int))
    print(f"  {with_subs} creators now have a subscriber_count")

    if args.dry_run:
        print("Dry run: not writing data/youtubers.json")
        return 0

    youtuber_store.save(youtubers)
    print(f"Wrote {youtuber_store.YOUTUBERS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
