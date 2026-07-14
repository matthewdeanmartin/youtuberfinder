"""Fetch channel statistics (subscriber counts, etc.) from the YouTube Data API.

The public RSS feeds used by :mod:`pipeline.youtube_feed` expose uploads but no
subscriber numbers, so popularity ranking needs the authenticated Data API v3
``channels`` endpoint::

    GET https://www.googleapis.com/youtube/v3/channels?part=statistics&id=UC...,UC...

The endpoint accepts up to 50 comma-separated channel ids per call, so requests
are batched. An API key is required (``YOUTUBE_API_KEY``).

Channel ids are the opaque ``UC...`` strings. Creator URLs come in several
shapes (``/channel/UC...``, ``/@handle``, ``/c/Name``, ``/user/Name``); the id
resolution for the non-direct shapes is delegated to
:func:`pipeline.youtube_feed.channel_id_from_url`, which scrapes the channel
page and caches the result on disk.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

from . import youtube_feed

API_URL = "https://www.googleapis.com/youtube/v3/channels"

# Hard API limit: at most 50 ids per channels.list call.
MAX_IDS_PER_REQUEST = 50


@dataclass(frozen=True)
class ChannelStats:
    channel_id: str
    title: str
    subscriber_count: int | None
    hidden_subscriber_count: bool
    video_count: int | None
    view_count: int | None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _chunked(items: list[str], size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def fetch_stats(channel_ids: list[str], api_key: str, *, timeout: float = 30.0) -> dict[str, ChannelStats]:
    """Return a ``{channel_id: ChannelStats}`` map for the given channel ids.

    Ids are de-duplicated and fetched in batches of 50. Channels the API does
    not return (deleted, suspended, or otherwise missing) are simply absent from
    the result; callers should treat a missing id as "no stats available".
    """
    unique = list(dict.fromkeys(cid for cid in channel_ids if cid))
    out: dict[str, ChannelStats] = {}
    for batch in _chunked(unique, MAX_IDS_PER_REQUEST):
        params = {
            "part": "snippet,statistics",
            "id": ",".join(batch),
            "key": api_key,
            "maxResults": MAX_IDS_PER_REQUEST,
        }
        response = requests.get(API_URL, params=params, timeout=timeout)
        response.raise_for_status()
        for item in response.json().get("items", []):
            stats = item.get("statistics", {})
            out[item["id"]] = ChannelStats(
                channel_id=item["id"],
                title=item.get("snippet", {}).get("title", ""),
                subscriber_count=_to_int(stats.get("subscriberCount")),
                hidden_subscriber_count=bool(stats.get("hiddenSubscriberCount")),
                video_count=_to_int(stats.get("videoCount")),
                view_count=_to_int(stats.get("viewCount")),
            )
    return out


def resolve_channel_id(youtube_url: str) -> str | None:
    """Resolve a ``UC...`` channel id from any creator YouTube URL shape.

    Thin wrapper over :func:`pipeline.youtube_feed.channel_id_from_url` so this
    module is a single entry point for stats collection.
    """
    return youtube_feed.channel_id_from_url(youtube_url)
