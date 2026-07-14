from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pipeline import categorize, mastodon_discovery, youtuber_store
from pipeline.language import detect_language

CATEGORY_OVERRIDES_PATH = Path(__file__).parent.parent / "data" / "category_overrides.json"

# An account with no post in this window is treated as "not really on Mastodon"
# and excluded from the directory.
INACTIVE_AFTER = timedelta(days=365)


def is_active(last_status_at, *, now: datetime | None = None) -> bool:
    """True if the account posted within INACTIVE_AFTER. A missing/blank/invalid
    last_status_at counts as inactive (never observed posting). Accepts either an
    ISO string or a datetime (mastodon.py returns datetimes)."""
    if not last_status_at:
        return False
    if isinstance(last_status_at, datetime):
        when = last_status_at
    else:
        try:
            when = datetime.fromisoformat(str(last_status_at))
        except ValueError:
            return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    return (now - when) <= INACTIVE_AFTER


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return slug or "creator"


def clean_name(value: str, acct: str) -> str:
    name = re.sub(r":\w+:", "", value or "")
    name = " ".join(name.split()).strip()
    return name or acct.split("@", 1)[0]


def description(account: dict) -> str:
    text = categorize.plain_text(str(account.get("note") or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:300] + ("…" if len(text) > 300 else "")


def profile_url(account: dict) -> str:
    return str(account.get("url") or "")


def choose_youtube(rows: list[sqlite3.Row]) -> sqlite3.Row:
    return sorted(
        rows,
        key=lambda row: (
            # Prefer a YouTube channel — the directory's primary platform —
            # over Twitch/PeerTube links when an account lists several.
            row["platform"] != "youtube",
            not row["youtube_url"].split("/")[-1].startswith("@"),
            len(row["youtube_url"]),
        ),
    )[0]


def build_catalog(db: sqlite3.Connection) -> list[dict]:
    categorize.classify_database(db)
    overrides = (
        json.loads(CATEGORY_OVERRIDES_PATH.read_text(encoding="utf-8"))
        if CATEGORY_OVERRIDES_PATH.exists()
        else {}
    )
    rows = db.execute(
        """
        SELECT p.*, y.youtube_url, y.evidence_source, y.platform, c.category, c.confidence,
               c.matched_terms_json, c.account_type
        FROM profiles p
        JOIN youtube_links y USING (acct)
        JOIN classifications c USING (acct)
        ORDER BY p.acct COLLATE NOCASE, y.youtube_url
        """
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["acct"], []).append(row)

    existing_by_mastodon = {
        item["mastodon_url"].casefold(): item
        for item in youtuber_store.load()
    }
    used_ids: set[str] = set()
    catalog: list[dict] = []
    inactive_dropped = 0
    for acct, account_rows in grouped.items():
        row = choose_youtube(account_rows)
        # Exclude accounts with no post in the last year — if they haven't
        # posted, they aren't really reachable on Mastodon. A manual language
        # override can't rescue these; inactivity is judged purely on activity.
        if not is_active(row["last_status_at"]):
            inactive_dropped += 1
            continue
        account = json.loads(row["raw_json"])
        override = overrides.get(acct, {})
        category = override.get("category", row["category"])
        if category not in categorize.CATEGORY_LABELS:
            raise ValueError(f"{acct}: unknown category override {category!r}")
        mastodon_url = profile_url(account)
        old = existing_by_mastodon.get(mastodon_url.casefold(), {})
        name = clean_name(str(account.get("display_name") or ""), acct)
        base_id = old.get("id") or slugify(name)
        creator_id = base_id
        suffix = 2
        while creator_id in used_ids:
            creator_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(creator_id)
        entry = {
            "id": creator_id,
            "name": old.get("name") or name,
            "category": category,
            "category_confidence": "curated" if override else row["confidence"],
            "category_evidence": (
                [override["reason"]]
                if override.get("reason")
                else json.loads(row["matched_terms_json"])
            ),
            "account_type": row["account_type"],
            "platform": row["platform"],
            "youtube_url": row["youtube_url"],
            "primary_url": row["youtube_url"],
            "youtube_evidence_source": row["evidence_source"],
            "mastodon_url": mastodon_url,
            "mastodon_acct": acct,
            "description": old.get("description") or description(account),
            "followers": row["followers_count"],
            "reviewed": old.get("reviewed", False),
            "review_slug": old.get("review_slug", creator_id),
        }
        # A manual language override on the existing entry wins; otherwise detect.
        entry["language"] = old.get("language") or detect_language(entry)
        catalog.append(entry)

    # Executive decision: the directory is English-only. Most visitors read one
    # language, so non-English accounts are suppressed at the source rather than
    # merely hidden client-side. Manual `language` overrides in youtubers.json
    # are respected, so an account can be force-kept by setting "language": "en".
    if inactive_dropped:
        print(f"Dropped {inactive_dropped} inactive accounts (no post in the last year).")

    english_only = [item for item in catalog if item.get("language") == "en"]
    dropped = len(catalog) - len(english_only)
    if dropped:
        print(f"Dropped {dropped} non-English accounts (English-only directory).")
    return sorted(
        english_only,
        key=lambda item: (
            categorize.CATEGORY_SORTORDER.index(item["category"]),
            item["account_type"] != "native",
            item["name"].casefold(),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish categorized YouTube-linked Mastodon profiles.")
    parser.add_argument("--db", type=Path, default=mastodon_discovery.DEFAULT_DB_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    db = mastodon_discovery.connect(args.db)
    catalog = build_catalog(db)
    if args.dry_run:
        counts: dict[tuple[str, str], int] = {}
        for item in catalog:
            key = (item["category"], item["account_type"])
            counts[key] = counts.get(key, 0) + 1
        print(json.dumps({f"{k[0]}:{k[1]}": v for k, v in counts.items()}, indent=2))
    else:
        youtuber_store.save(catalog)
        print(f"Published {len(catalog)} categorized profiles to {youtuber_store.YOUTUBERS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
