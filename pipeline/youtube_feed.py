"""Build-time fetch of recent YouTube uploads via public channel RSS feeds.

YouTube exposes a per-channel Atom feed at::

    https://www.youtube.com/feeds/videos.xml?channel_id=UC...

The feed needs the opaque ``channel_id`` (``UC...``).  Creator URLs in
``data/youtubers.json`` come in several shapes:

    https://www.youtube.com/channel/UCxxxx   -> id is right there
    https://www.youtube.com/@handle          -> must scrape the channel page
    https://www.youtube.com/c/CustomName     -> must scrape the channel page
    https://www.youtube.com/user/LegacyName   -> must scrape the channel page

Resolution and feed responses are cached on disk (``.cache/youtube.sqlite``)
so repeated builds are fast and resilient.  Every network path degrades
gracefully: any failure yields an empty result rather than breaking the build,
because the site must keep building (and CI staying green) even when YouTube
is unreachable or rate-limiting.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

try:
    import requests_cache

    _SESSION: "requests_cache.CachedSession | None" = None
except Exception:  # pragma: no cover - requests-cache should be installed
    requests_cache = None
    _SESSION = None

CACHE_PATH = Path(__file__).parent.parent / ".cache" / "youtube"
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
USER_AGENT = "tech-youtubers-static-site (+https://matthewdeanmartin.github.io/youtuberfinder/)"

# Feed responses change a few times a day at most; resolution basically never.
_CACHE_EXPIRE_SECONDS = 60 * 60 * 6  # 6 hours

_ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}

_CHANNEL_ID_RE = re.compile(r"UC[0-9A-Za-z_-]{22}")


_VIDEO_ID_RE = re.compile(r"[?&]v=([0-9A-Za-z_-]{11})")


def video_id_from_url(url: str) -> str | None:
    """Extract the 11-char YouTube video id from a watch / youtu.be URL."""
    if not url:
        return None
    match = _VIDEO_ID_RE.search(url)
    if match:
        return match.group(1)
    # youtu.be/<id> short form.
    path = urlparse(url).path.strip("/")
    if len(path) == 11 and re.fullmatch(r"[0-9A-Za-z_-]{11}", path):
        return path
    return None


@dataclass(frozen=True)
class Video:
    title: str
    url: str
    published: str  # ISO date (YYYY-MM-DD) for display

    @property
    def video_id(self) -> str | None:
        return video_id_from_url(self.url)


def _session():
    """Return a shared on-disk-cached HTTP session, or None if unavailable."""
    global _SESSION
    if requests_cache is None:
        return None
    if _SESSION is None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SESSION = requests_cache.CachedSession(
            str(CACHE_PATH),
            backend="sqlite",
            expire_after=_CACHE_EXPIRE_SECONDS,
            stale_if_error=True,
        )
        _SESSION.headers.update({"User-Agent": USER_AGENT})
    return _SESSION


def _get(url: str, timeout: float = 12.0):
    session = _session()
    if session is None:
        return None
    try:
        response = session.get(url, timeout=timeout)
    except Exception:
        return None
    if not response.ok:
        return None
    return response


def channel_id_from_url(youtube_url: str) -> str | None:
    """Resolve a channel_id (UC...) from any YouTube channel URL shape.

    Direct ``/channel/UC...`` URLs are parsed locally. Handle/custom/user URLs
    require fetching the channel page and scraping the embedded channel id.
    Returns ``None`` if it cannot be determined.
    """
    if not youtube_url:
        return None

    path = urlparse(youtube_url).path.strip("/")
    parts = path.split("/")

    # https://www.youtube.com/channel/UCxxxx
    if len(parts) >= 2 and parts[0] == "channel":
        match = _CHANNEL_ID_RE.fullmatch(parts[1])
        if match:
            return parts[1]

    # Anything else (@handle, /c/Name, /user/Name): scrape the channel page.
    response = _get(youtube_url)
    if response is None:
        return None
    # The channel page embeds the canonical id in several places; the
    # "externalId":"UC..." / "channelId":"UC..." JSON blobs are the most stable.
    for pattern in (r'"channelId":"(UC[0-9A-Za-z_-]{22})"', r'"externalId":"(UC[0-9A-Za-z_-]{22})"'):
        found = re.search(pattern, response.text)
        if found:
            return found.group(1)
    # Fall back to the canonical <link rel="canonical"> URL.
    canonical = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[0-9A-Za-z_-]{22})"', response.text)
    if canonical:
        return canonical.group(1)
    return None


def _parse_feed(xml_text: str, limit: int) -> list[Video]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    videos: list[Video] = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        title_el = entry.find("atom:title", _ATOM_NS)
        link_el = entry.find("atom:link", _ATOM_NS)
        published_el = entry.find("atom:published", _ATOM_NS)
        if title_el is None or title_el.text is None:
            continue
        url = link_el.get("href") if link_el is not None else ""
        published = ""
        if published_el is not None and published_el.text:
            try:
                published = datetime.fromisoformat(published_el.text).date().isoformat()
            except ValueError:
                published = published_el.text[:10]
        videos.append(Video(title=title_el.text.strip(), url=url or "", published=published))
        if len(videos) >= limit:
            break
    return videos


def recent_videos(youtube_url: str, limit: int = 5) -> list[Video]:
    """Return up to ``limit`` most recent videos for a creator's channel.

    Always returns a list; on any resolution or network failure it returns
    ``[]`` so the caller can simply omit the widget.
    """
    channel_id = channel_id_from_url(youtube_url)
    if not channel_id:
        return []
    response = _get(FEED_URL.format(channel_id=channel_id))
    if response is None:
        return []
    return _parse_feed(response.text, limit)
