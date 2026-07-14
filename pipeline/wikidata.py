"""
Wikidata as a discovery source.

Wikidata records, for many notable creators and organisations, both their
YouTube channel ID (property P2397) and their Mastodon address (property P4033,
stored as ``user@host``). That makes it a *YouTube-first* seed source that
complements the Mastodon-first ``account_search`` discovery: instead of guessing
topical search terms, we get a curated list of accounts already cross-referenced
to a YouTube channel.

We only keep items that have *both* a YouTube channel and a Mastodon handle —
those are the ones we can feed into the existing pipeline, which resolves the
Mastodon handle to a live profile and applies the usual activity / English /
channel-link gates at publish time. The Wikidata YouTube channel ID is carried
along as fallback evidence so a creator whose Mastodon bio omits their channel
still surfaces.

Uses only the standard library so the pipeline gains no new dependency.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

WIKIDATA_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
DEFAULT_CACHE_PATH = Path(__file__).parent.parent / ".cache" / "wikidata_creators.json"
USER_AGENT = "tech-youtubers-discovery/1.0 (https://github.com/matthewdeanmartin/youtuberfinder; matthewdeanmartin@gmail.com)"

# P2397 = YouTube channel ID, P4033 = Mastodon address (user@host).
# We require both so every row is actionable by the Mastodon-first pipeline.
# Paged with LIMIT/OFFSET; the label service resolves ?itemLabel to English.
QUERY_TEMPLATE = """
SELECT ?item ?itemLabel ?youtubeChannelId ?mastodon WHERE {{
  ?item wdt:P2397 ?youtubeChannelId .
  ?item wdt:P4033 ?mastodon .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
ORDER BY ?item
LIMIT {limit}
OFFSET {offset}
"""


@dataclass(frozen=True)
class WikidataCreator:
    """One Wikidata item carrying a YouTube channel and a Mastodon address."""

    qid: str
    label: str
    youtube_channel_id: str
    mastodon_acct: str

    @property
    def youtube_url(self) -> str:
        return f"https://www.youtube.com/channel/{self.youtube_channel_id}"


def _run_query(query: str, *, timeout: float) -> list[dict]:
    params = urllib.parse.urlencode({"query": query, "format": "json"})
    request = urllib.request.Request(
        f"{WIKIDATA_SPARQL_ENDPOINT}?{params}",
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["results"]["bindings"]


def _parse_binding(row: dict) -> WikidataCreator | None:
    try:
        item_uri = row["item"]["value"]
        channel = row["youtubeChannelId"]["value"].strip()
        acct = row["mastodon"]["value"].strip().lstrip("@")
    except KeyError:
        return None
    if not channel or "@" not in acct:
        return None
    qid = item_uri.rsplit("/", 1)[-1]
    label = (row.get("itemLabel") or {}).get("value") or qid
    return WikidataCreator(qid=qid, label=label, youtube_channel_id=channel, mastodon_acct=acct)


def fetch_creators(
    *,
    page_size: int = 500,
    max_items: int | None = None,
    timeout: float = 60.0,
    pause: float = 1.0,
) -> list[WikidataCreator]:
    """Page through Wikidata for items with a YouTube channel and Mastodon address.

    Deduplicates on (mastodon_acct, youtube_channel_id); a single Mastodon
    handle can legitimately appear once per channel it is linked to.
    """
    creators: dict[tuple[str, str], WikidataCreator] = {}
    offset = 0
    while True:
        query = QUERY_TEMPLATE.format(limit=page_size, offset=offset)
        rows = _run_query(query, timeout=timeout)
        if not rows:
            break
        for row in rows:
            creator = _parse_binding(row)
            if creator is None:
                continue
            creators[(creator.mastodon_acct.casefold(), creator.youtube_channel_id)] = creator
        offset += page_size
        if len(rows) < page_size:
            break
        if max_items is not None and len(creators) >= max_items:
            break
        time.sleep(pause)  # be polite to the public endpoint
    result = list(creators.values())
    return result[:max_items] if max_items is not None else result


def cache_creators(creators: list[WikidataCreator], path: Path = DEFAULT_CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([creator.__dict__ for creator in creators], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_cached(path: Path = DEFAULT_CACHE_PATH) -> list[WikidataCreator]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [WikidataCreator(**entry) for entry in data]
