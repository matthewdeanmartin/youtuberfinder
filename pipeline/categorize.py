from __future__ import annotations

import html
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser

CATEGORY_LABELS = {
    "technology": "Technology & Computing",
    "gaming": "Gaming & VTubers",
    "science-education": "Science & Education",
    "music": "Music",
    "art-making": "Art, Design & Making",
    "news-society": "News, Politics & Society",
    "culture-entertainment": "Culture & Entertainment",
    "lifestyle-hobbies": "Lifestyle, Travel & Hobbies",
    "other": "Other",
}

CATEGORY_SORTORDER = list(CATEGORY_LABELS)

TERMS = {
    "technology": {
        "linux": 5, "software": 5, "programming": 5, "coding": 5, "developer": 4,
        "cyber": 5, "infosec": 5, "security": 4, "technology": 4, "tech": 3,
        "computer": 4, "hardware": 5, "open source": 5, "opensource": 5,
        "self-host": 5, "homelab": 5, "server": 3, "cloud": 4, "devops": 5,
        "engineering": 3, "javascript": 5, "python": 5, "graphics programming": 6,
        "mobile": 2, "gadget": 3, "keyboard": 3, "pc": 2, "informatik": 4,
        # Vocabulary the Wikidata corpus surfaced: apps, electronics, FOSS
        # projects, the open-data / open-web world. Kept to whole, low-ambiguity
        # words to avoid false substring hits.
        "free software": 5, "fediverse": 4, "self-hosted": 5, "fedora": 4,
        "ubuntu": 4, "debian": 4, "distro": 5, "operating system": 5,
        "electronics": 5, "consumer electronics": 6, "app for": 4,
        "the app": 4, "search engine": 5, "web browser": 5, "data privacy": 4,
        "privacy": 3, "encryption": 5, "internet archive": 5, "digital library": 4,
        "openstreetmap": 5, "open data": 4, "open culture": 4, "open standards": 5,
        "api": 3, "self hosting": 5, "raspberry pi": 5, "microcontroller": 5,
        # Second pass: ad/privacy tooling, front-end, chip/ARM, security
        # programs, hack/maker spaces, and dev-meetup vocabulary.
        "ad blocker": 5, "blocks ads": 5, "vpn": 4, "front-end": 5,
        "frontend": 5, "back-end": 5, "web development": 5, "codepen": 5,
        "arm": 3, "semiconductor": 5, "chip": 3, "common weakness": 6,
        "vulnerability": 5, "malware": 5, "hackspace": 5, "hackerspace": 6,
        "makerspace": 5, "fablab": 5, "fab lab": 5, "digital infrastructure": 4,
        "digital transformation": 4, "digitalisierung": 4, "it security": 5,
        # Named FOSS projects/tools that appear bare in bios.
        "curl": 5, "golang": 6, "go language": 6, "emulator": 5,
        "office suite": 5, "productivity suite": 5, "compiler": 5,
        "kernel": 5, "command line": 5, "terminal": 3, "git": 3,
        "プログラミング": 5, "ソフトウェア": 5, "ゲーム制作": 3,
    },
    "gaming": {
        "gaming": 5, "gamer": 5, "gameplay": 5, "video game": 5, "speedrun": 6,
        "minecraft": 5, "geoguessr": 5, "vtuber": 6, "virtual youtuber": 6,
        "hololive": 6, "streamer": 3, "twitch": 2, "ゲーム": 5, "ゲーム実況": 6,
        "ゲーム配信": 6, "バーチャル": 4, "配信": 2, "実況": 3, "ポケモン": 5,
        "任天堂": 5, "playstation": 5, "capcom": 5, "カプコン": 5,
        # Tabletop counts as gaming here — the Wikidata set includes board-game
        # publishers and TTRPG creators.
        "board game": 5, "boardgame": 5, "tabletop": 5, "ttrpg": 6,
        "dungeons & dragons": 6, "role-playing game": 5, "tabletop game": 6,
        # Game press/wikis/communities and VR social platforms.
        "rock paper shotgun": 6, "game series": 5, "game wiki": 6,
        "esports": 5, "speedrunning": 6, "vr platform": 5, "metaverse": 4,
        "game studio": 5, "indie game": 5, "game dev": 5, "gamedev": 5,
    },
    "science-education": {
        "science": 5, "physics": 5, "math": 5, "maths": 5, "research": 3,
        "teaching": 4, "teacher": 4, "education": 5, "educates": 4, "lecturer": 4,
        "tutorial": 3, "history": 4, "latin": 5, "classics": 4, "学習": 4,
        # Universities, institutes, libraries and learned societies are heavily
        # represented in Wikidata and almost all are science/education.
        "university": 4, "université": 4, "universität": 4, "universiteit": 4,
        "institute": 3, "institut": 3, "academy of": 4, "academy": 3,
        "library": 4, "bibliothek": 4, "bibliothèque": 4, "biblioteca": 4,
        "scientific": 4, "scientist": 4, "scholarship": 3, "academic": 3,
        "biology": 5, "chemistry": 5, "astronomy": 5, "geography": 4,
        "geology": 5, "ecology": 4, "professor": 4, "phd": 3, "doctoral": 4,
        "researcher": 4, "knowledge": 2, "learning": 3, "lifelong learning": 5,
        "研究": 3, "教育": 5,
    },
    "music": {
        "music": 5, "musician": 5, "concert": 5, "band": 4, "guitar": 4,
        "audio": 3, "radio": 3, "record label": 5, "dj": 4, "singing": 3,
        "singer": 4, "歌": 4, "音楽": 5, "ギター": 4, "dtmer": 4, "作曲": 4,
    },
    "art-making": {
        "artist": 5, "illustrator": 5, "illustration": 5, "drawing": 4,
        "design": 4, "designer": 4, "photography": 5, "photographer": 5,
        "maker": 4, "tinkerer": 3, "3d": 3, "animation": 4, "anime": 3,
        "art": 3, "craft": 4, "絵": 4, "イラスト": 5, "写真": 5, "漫画": 4,
        "アニメ": 4, "動画編集": 3,
    },
    "news-society": {
        "news": 6, "journalism": 5, "journalist": 5, "politics": 5,
        "political": 5, "political party": 5, "digital rights": 4,
        "human rights": 4, "society": 3, "law": 4,
        "reuters": 6, "bbc news": 6, "nhk": 5, "ニュース": 6, "新聞": 6,
        # Elected officials, parties, NGOs, advocacy and government accounts —
        # a large slice of the Wikidata corpus. Role/office words are strong
        # signals even when "politics" itself never appears.
        "senator": 5, "member of parliament": 6, "parliament": 4,
        "congress": 4, "politician": 5, "minister": 4, "ministry": 4,
        "government": 4, "council": 3, "mayor": 4, "democracy": 4,
        "activist": 4, "advocacy": 4, "campaign": 3, "nonprofit": 3,
        "ngo": 4, "civil rights": 5, "public policy": 5, "policy": 3,
        "green party": 5, "social democrat": 5, "trade union": 5, "labour": 3,
        # Watchdogs, foundations, regulators and satire/news outlets.
        "anti-corruption": 5, "transparency": 4, "corruption": 4,
        "foundation": 3, "stiftung": 3, "regulator": 4, "regulatory": 4,
        "think tank": 5, "satire": 4, "newspaper": 5, "magazine": 2,
        "press": 2, "current affairs": 5, "public broadcaster": 5,
        "共産党": 6, "民主党": 6, "弁護士": 5, "報道": 6,
    },
    "culture-entertainment": {
        "podcast": 5, "film": 4, "movie": 4, "television": 4, "tv": 3,
        "media": 3, "comedy": 4, "writer": 3, "author": 3, "story": 3,
        "entertainment": 5, "映画": 5, "小説": 4, "朗読": 4, "特撮": 5,
        # Publishers, theatres, museums and the books world.
        "publisher": 4, "publishing": 4, "verlag": 4, "book": 3, "books": 3,
        "novel": 4, "literature": 4, "theatre": 4, "theater": 4,
        "museum": 4, "gallery": 3, "festival": 3, "magazine": 4,
    },
    "lifestyle-hobbies": {
        "travel": 5, "outdoors": 5, "cycling": 4, "food": 4, "cooking": 4,
        "beauty": 4, "fitness": 4, "horse": 4, "equestrian": 5, "camera": 3,
        "asmr": 3, "散歩": 4, "旅行": 5, "競馬": 5, "卓球": 5, "カメラ": 3,
        "gardening": 5, "hiking": 5, "recipe": 4, "vegan": 4, "knitting": 5,
        "public transport": 4, "urbanism": 4, "urbanist": 5, "transit": 3,
        "sustainability": 3, "climate": 3, "environment": 3,
    },
}


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(value: str) -> str:
    parser = TextExtractor()
    parser.feed(value or "")
    return " ".join(html.unescape(" ".join(parser.parts)).split())


def classification_text(account: dict) -> str:
    fields = account.get("fields") or []
    pieces = [
        str(account.get("display_name") or ""),
        plain_text(str(account.get("note") or "")),
    ]
    for field in fields:
        pieces.extend([plain_text(str(field.get("name") or "")), plain_text(str(field.get("value") or ""))])
    return unicodedata.normalize("NFKC", " ".join(pieces)).casefold()


def account_type(account: dict) -> str:
    acct = str(account.get("acct") or "").casefold()
    text = classification_text(account)
    if "rss-mstdn.studiofreesia.com" in acct or "rssフィードの内容を投稿するbot" in text:
        return "rss-feed"
    if "feedsin.space" in acct:
        return "channel-feed"
    if "brid.gy" in acct or "bridged from" in text:
        return "bridge"
    if account.get("bot"):
        return "bot"
    return "native"


@dataclass(frozen=True)
class Classification:
    category: str
    confidence: str
    matched_terms: tuple[str, ...]
    account_type: str


def classify(account: dict) -> Classification:
    text = classification_text(account)
    scores: dict[str, int] = {}
    matches: dict[str, list[str]] = {}
    for category, weighted_terms in TERMS.items():
        for term, weight in weighted_terms.items():
            if term in text:
                scores[category] = scores.get(category, 0) + weight
                matches.setdefault(category, []).append(term)

    if not scores:
        return Classification("other", "low", (), account_type(account))

    ranked = sorted(scores.items(), key=lambda item: (-item[1], CATEGORY_SORTORDER.index(item[0])))
    category, score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    margin = score - runner_up
    confidence = "high" if score >= 8 and margin >= 3 else "medium" if score >= 4 else "low"
    return Classification(category, confidence, tuple(matches.get(category, ())), account_type(account))


def classify_database(db: sqlite3.Connection) -> dict[str, int]:
    rows = db.execute(
        "SELECT acct, raw_json FROM profiles WHERE acct IN (SELECT DISTINCT acct FROM youtube_links)"
    ).fetchall()
    now = datetime.now(UTC).isoformat()
    counts: dict[str, int] = {}
    for row in rows:
        account = json.loads(row["raw_json"])
        result = classify(account)
        db.execute(
            """
            INSERT INTO classifications (
                acct, category, confidence, matched_terms_json, account_type, classified_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(acct) DO UPDATE SET
                category=excluded.category,
                confidence=excluded.confidence,
                matched_terms_json=excluded.matched_terms_json,
                account_type=excluded.account_type,
                classified_at=excluded.classified_at
            """,
            (
                row["acct"],
                result.category,
                result.confidence,
                json.dumps(result.matched_terms, ensure_ascii=False),
                result.account_type,
                now,
            ),
        )
        counts[result.category] = counts.get(result.category, 0) + 1
    db.commit()
    return counts
