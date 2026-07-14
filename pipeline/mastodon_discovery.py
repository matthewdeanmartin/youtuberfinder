from __future__ import annotations

import html
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

from pipeline.mastodon import parse_profile_url

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "mastodon_candidates.sqlite"
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
TWITCH_HOSTS = {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}
# PeerTube — the federated "Fediverse YouTube clone" — runs on hundreds of
# independent instances, so we can't enumerate hosts. We recognise it by the
# stable channel/account path shapes PeerTube uses, on any host. Well-known
# flagship instances are listed to bias detection, but the path heuristic is
# what actually generalises.
PEERTUBE_HOSTS = {
    "framatube.org", "tilvids.com", "video.ploud.fr", "peertube.tv",
    "tube.tchncs.de", "diode.zone", "makertube.net", "spectra.video",
}
# A non-video Twitch path we should ignore (directory/category pages, not a channel).
TWITCH_RESERVED = {"directory", "videos", "p", "settings", "subscriptions", "wallet", "downloads"}
# YouTube app routes that look like a one-segment vanity URL (youtube.com/<x>)
# but are NOT a channel. Everything else of that shape is a legacy custom URL
# (e.g. youtube.com/standupmaths) and is accepted as a channel.
YOUTUBE_RESERVED = {
    "watch", "playlist", "results", "feed", "shorts", "live", "embed", "hashtag",
    "channel", "c", "user", "premium", "gaming", "music", "movies", "about",
    "account", "upload", "redirect", "playables", "podcasts", "source", "@",
}
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def _strip_path(parsed) -> str:
    return re.sub(r"/+", "/", parsed.path).rstrip("/")


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.append(html.unescape(href))


def _urls_from_html(value: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(value or "")
    return parser.hrefs + URL_RE.findall(html.unescape(value or ""))


def canonical_youtube_url(url: str) -> str | None:
    candidate = html.unescape(url).strip().rstrip(".,;:!?)")
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        return None

    if host in {"youtu.be", "www.youtu.be"}:
        # A short video URL is evidence that the person uses YouTube, but it is not
        # a stable channel URL suitable for the directory.
        return None

    path = _strip_path(parsed)
    if not path:
        return None
    segments = [s for s in path.split("/") if s]
    first = segments[0].lower() if segments else ""

    if path.startswith("/@") or first in {"channel", "c", "user"}:
        # Modern handle (/@name) or explicit /channel|/c|/user channel URL.
        canonical_path = path
    elif len(segments) == 1 and first not in YOUTUBE_RESERVED:
        # Legacy vanity URL: youtube.com/<name> (e.g. youtube.com/standupmaths).
        # Single non-reserved segment is a custom channel URL.
        canonical_path = "/" + segments[0]
    else:
        return None

    clean = parsed._replace(
        scheme="https", netloc="www.youtube.com", path=canonical_path, params="", query="", fragment=""
    )
    return urlunparse(clean)


def canonical_twitch_url(url: str) -> str | None:
    candidate = html.unescape(url).strip().rstrip(".,;:!?)")
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if host not in TWITCH_HOSTS:
        return None
    path = _strip_path(parsed)
    if not path:
        return None
    segments = [s for s in path.split("/") if s]
    # A channel is twitch.tv/<name> — a single path segment that isn't a
    # reserved app route.
    if len(segments) != 1 or segments[0].lower() in TWITCH_RESERVED:
        return None
    clean = parsed._replace(
        scheme="https", netloc="www.twitch.tv", path=f"/{segments[0]}", params="", query="", fragment=""
    )
    return urlunparse(clean)


def _looks_like_peertube_path(segments: list[str]) -> bool:
    """PeerTube channel/account permalinks: /c/<h>, /a/<h>, /video-channels/<h>,
    or /accounts/<h> (optionally followed by /videos)."""
    if not segments:
        return False
    head = segments[0].lower()
    if head in {"c", "a", "video-channels", "accounts"} and len(segments) >= 2:
        return True
    return False


def canonical_peertube_url(url: str) -> str | None:
    candidate = html.unescape(url).strip().rstrip(".,;:!?)")
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    path = _strip_path(parsed)
    segments = [s for s in path.split("/") if s]
    # Accept either a known flagship instance or any host whose path matches
    # PeerTube's channel/account permalink shape.
    if host not in PEERTUBE_HOSTS and not _looks_like_peertube_path(segments):
        return None
    if not _looks_like_peertube_path(segments):
        return None
    # Normalise to the channel/account permalink, dropping a trailing /videos.
    if segments[-1].lower() == "videos":
        segments = segments[:-1]
    clean = parsed._replace(
        scheme="https", netloc=host, path="/" + "/".join(segments), params="", query="", fragment=""
    )
    return urlunparse(clean)


# Platform name -> canonicaliser. YouTube stays first so it wins for the
# common case and remains the directory's primary platform.
PLATFORM_CANONICALIZERS = (
    ("youtube", canonical_youtube_url),
    ("twitch", canonical_twitch_url),
    ("peertube", canonical_peertube_url),
)


def canonical_channel_url(url: str) -> tuple[str, str] | None:
    """Return ``(platform, canonical_url)`` for a recognised video channel link."""
    for platform, canonicalize in PLATFORM_CANONICALIZERS:
        result = canonicalize(url)
        if result:
            return platform, result
    return None


def youtube_links(account: dict) -> list[tuple[str, str, str]]:
    """Return ``(channel_url, evidence_source, platform)`` for every recognised
    video-channel link (YouTube, Twitch, or PeerTube) in the profile.

    The name is kept for historical reasons; the directory now treats any of
    these platforms as evidence that the account belongs to a video creator.
    """
    evidence: list[tuple[str, str, str]] = []
    sources = [("bio", account.get("note") or "")]
    for field in account.get("fields") or []:
        field_name = field.get("name") or "profile field"
        sources.append((f"field:{field_name}", field.get("value") or ""))

    seen: set[str] = set()
    for source, value in sources:
        for raw_url in _urls_from_html(value):
            match = canonical_channel_url(raw_url)
            if match and match[1].casefold() not in seen:
                platform, channel_url = match
                seen.add(channel_url.casefold())
                evidence.append((channel_url, source, platform))
    return evidence


def canonical_acct(account: dict) -> str:
    acct = str(account.get("acct") or "")
    if "@" in acct:
        return acct
    profile_url = str(account.get("url") or "")
    host, _ = parse_profile_url(profile_url)
    return f"{acct}@{host}"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS profiles (
    acct TEXT PRIMARY KEY COLLATE NOCASE,
    account_id TEXT NOT NULL,
    profile_url TEXT NOT NULL,
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    bio_html TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    followers_count INTEGER,
    following_count INTEGER,
    statuses_count INTEGER,
    last_status_at TEXT,
    source_instance TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_links (
    acct TEXT NOT NULL COLLATE NOCASE,
    youtube_url TEXT NOT NULL,
    evidence_source TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'youtube',
    discovered_at TEXT NOT NULL,
    PRIMARY KEY (acct, youtube_url),
    FOREIGN KEY (acct) REFERENCES profiles(acct) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS search_hits (
    acct TEXT NOT NULL COLLATE NOCASE,
    query TEXT NOT NULL,
    result_offset INTEGER NOT NULL,
    discovered_at TEXT NOT NULL,
    PRIMARY KEY (acct, query),
    FOREIGN KEY (acct) REFERENCES profiles(acct) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS classifications (
    acct TEXT PRIMARY KEY COLLATE NOCASE,
    category TEXT NOT NULL,
    confidence TEXT NOT NULL,
    matched_terms_json TEXT NOT NULL,
    account_type TEXT NOT NULL,
    classified_at TEXT NOT NULL,
    FOREIGN KEY (acct) REFERENCES profiles(acct) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_profiles_followers ON profiles(followers_count DESC);
CREATE INDEX IF NOT EXISTS idx_youtube_links_acct ON youtube_links(acct);
"""


def connect(path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    db.executescript(SCHEMA)
    _migrate(db)
    return db


def _migrate(db: sqlite3.Connection) -> None:
    """Apply forward-only schema tweaks to pre-existing databases."""
    columns = {row["name"] for row in db.execute("PRAGMA table_info(youtube_links)")}
    if "platform" not in columns:
        db.execute(
            "ALTER TABLE youtube_links ADD COLUMN platform TEXT NOT NULL DEFAULT 'youtube'"
        )
        db.commit()


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def store_account(
    db: sqlite3.Connection,
    account: dict,
    *,
    source_instance: str,
    query: str | None = None,
    result_offset: int = 0,
    extra_links: list[tuple[str, str, str]] | None = None,
) -> tuple[str, int]:
    """Store a Mastodon profile and its video-channel evidence.

    ``extra_links`` lets a caller contribute ``(channel_url, evidence_source,
    platform)`` evidence that doesn't appear in the profile itself — e.g. a
    YouTube channel cross-referenced from Wikidata. Links already discovered in
    the profile win, so an extra link only fills a gap.
    """
    acct = canonical_acct(account)
    now = utc_now()
    last_status = account.get("last_status_at")
    if isinstance(last_status, datetime):
        last_status = last_status.isoformat()
    fields = account.get("fields") or []
    links = youtube_links(account)
    if extra_links:
        seen = {url.casefold() for url, _, _ in links}
        for url, source, platform in extra_links:
            if url.casefold() not in seen:
                links.append((url, source, platform))
                seen.add(url.casefold())
    db.execute(
        """
        INSERT INTO profiles (
            acct, account_id, profile_url, username, display_name, bio_html,
            fields_json, followers_count, following_count, statuses_count,
            last_status_at, source_instance, first_seen_at, last_seen_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(acct) DO UPDATE SET
            account_id=excluded.account_id,
            profile_url=excluded.profile_url,
            username=excluded.username,
            display_name=excluded.display_name,
            bio_html=excluded.bio_html,
            fields_json=excluded.fields_json,
            followers_count=excluded.followers_count,
            following_count=excluded.following_count,
            statuses_count=excluded.statuses_count,
            last_status_at=excluded.last_status_at,
            source_instance=excluded.source_instance,
            last_seen_at=excluded.last_seen_at,
            raw_json=excluded.raw_json
        """,
        (
            acct,
            str(account.get("id") or ""),
            str(account.get("url") or ""),
            str(account.get("username") or ""),
            str(account.get("display_name") or ""),
            str(account.get("note") or ""),
            json.dumps(fields, ensure_ascii=False, default=_json_default),
            account.get("followers_count"),
            account.get("following_count"),
            account.get("statuses_count"),
            last_status,
            source_instance,
            now,
            now,
            json.dumps(dict(account), ensure_ascii=False, default=_json_default),
        ),
    )
    db.execute("DELETE FROM youtube_links WHERE acct = ?", (acct,))
    db.executemany(
        "INSERT INTO youtube_links (acct, youtube_url, evidence_source, platform, discovered_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [(acct, url, source, platform, now) for url, source, platform in links],
    )
    if query:
        db.execute(
            """
            INSERT INTO search_hits (acct, query, result_offset, discovered_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(acct, query) DO UPDATE SET
                result_offset=excluded.result_offset,
                discovered_at=excluded.discovered_at
            """,
            (acct, query, result_offset, now),
        )
    return acct, len(links)


@dataclass(frozen=True)
class Candidate:
    acct: str
    display_name: str
    profile_url: str
    youtube_url: str
    evidence_source: str
    platform: str
    followers_count: int


def candidates(db: sqlite3.Connection, limit: int | None = None) -> list[Candidate]:
    sql = """
        SELECT p.acct, p.display_name, p.profile_url, y.youtube_url,
               y.evidence_source, y.platform,
               COALESCE(p.followers_count, 0) AS followers_count
        FROM profiles p
        JOIN youtube_links y USING (acct)
        ORDER BY followers_count DESC, p.acct COLLATE NOCASE
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    return [Candidate(**dict(row)) for row in db.execute(sql, params)]


def stats(db: sqlite3.Connection) -> dict[str, int]:
    return {
        "profiles": db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0],
        "profiles_with_youtube": db.execute(
            "SELECT COUNT(DISTINCT acct) FROM youtube_links"
        ).fetchone()[0],
        "search_hits": db.execute("SELECT COUNT(*) FROM search_hits").fetchone()[0],
    }


def unwrap_youtube_redirect(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in {"youtube.com", "www.youtube.com"} and parsed.path == "/redirect":
        return parse_qs(parsed.query).get("q", [url])[0]
    return url
