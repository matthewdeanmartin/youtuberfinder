from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) in sys.path:
    sys.path.remove(str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT))

# Creator labels and handles routinely contain non-Latin-1 characters (e.g. the
# "ć" in "Volt España" or accented German names). On Windows the console
# defaults to cp1252, so printing such a label raises UnicodeEncodeError and can
# crash a long discovery run. Force UTF-8 on our streams; errors="replace" keeps
# us alive even on a stream that still can't encode a stray character.
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")

from mastodon import MastodonAPIError, MastodonError
from pipeline import (
    categorize,
    mastodon,
    mastodon_discovery,
    publish_candidates,
    wikidata,
    youtuber_store,
)

DEFAULT_QUERIES = [
    "youtube",
    "youtuber",
    "video creator youtube",
    "gaming youtube",
    "vtuber youtube",
    "music youtube",
    "art youtube",
    "science youtube",
    "math youtube",
    "mathematics youtube",
    "physics youtube",
    "engineering youtube",
    "comedy youtube",
    "maker youtube",
    "education youtube",
    "history youtube",
    "news youtube",
    "politics youtube",
    "film youtube",
    "travel youtube",
    "photography youtube",
    "cooking youtube",
    "programming youtube",
    "linux youtube",
    "cybersecurity youtube",
    "hardware youtube",
    # Twitch streamers and PeerTube (the Fediverse video platform) creators are
    # now first-class evidence alongside YouTube.
    "twitch",
    "twitch streamer",
    "gaming twitch",
    "live streamer",
    "peertube",
    "peertube creator",
    "video creator fediverse",
]

# Well-known creators whose Mastodon handle/display-name is NOT topical, so
# Mastodon's account_search (which matches handle + display name, never bio
# text) misses them under topic queries. We look these up directly by address.
# They still have to pass the normal gates at publish time: a YouTube channel
# link in the profile, recent activity, and English-language detection. This is
# a discovery aid, not a force-include — a handle here that fails the evidence
# or activity check simply won't be published.
KNOWN_CREATOR_HANDLES = [
    "standupmaths@mathstodon.xyz",   # Matt Parker — verified, links to youtube.com/standupmaths
    # Add more verified handles here as they're confirmed. Entries that don't
    # exist (404) or lack a YouTube channel link are skipped automatically, so
    # it's safe to leave aspirational handles in — but keep this list curated to
    # avoid noise. Many big YouTubers simply aren't on Mastodon, or post under a
    # handle that doesn't match their channel name.
]


def collect(args: argparse.Namespace) -> int:
    api = mastodon.client_from_env()
    source_instance = mastodon.parse_profile_url(
        f"{api.api_base_url}/@placeholder"
    )[0]
    db = mastodon_discovery.connect(args.db)
    queries = args.query or DEFAULT_QUERIES
    stored = youtube_profiles = 0

    for query in queries:
        for page in range(args.pages):
            offset = page * args.limit
            try:
                accounts = list(
                    api.account_search(
                        query,
                        limit=args.limit,
                        offset=offset,
                        resolve=False,
                    )
                )
            except (MastodonAPIError, MastodonError) as exc:
                print(f"WARN search {query!r} offset {offset}: {exc}", file=sys.stderr)
                break
            if not accounts:
                break
            for account in accounts:
                _, link_count = mastodon_discovery.store_account(
                    db,
                    account,
                    source_instance=source_instance,
                    query=query,
                    result_offset=offset,
                )
                stored += 1
                youtube_profiles += bool(link_count)
            db.commit()
            print(f"{query!r} offset={offset}: {len(accounts)} profiles")
            if len(accounts) < args.limit:
                break

    totals = mastodon_discovery.stats(db)
    print(
        f"Stored {stored} search results ({youtube_profiles} with channel links this run). "
        f"Database: {totals['profiles']} unique profiles, "
        f"{totals['profiles_with_youtube']} with YouTube channel evidence."
    )
    return 0


def seed(args: argparse.Namespace) -> int:
    api = mastodon.client_from_env()
    db = mastodon_discovery.connect(args.db)
    creators = youtuber_store.load()
    failures = 0
    for creator in creators:
        try:
            account = mastodon.lookup_account(api, creator["mastodon_url"])
            acct, links = mastodon_discovery.store_account(
                db, account, source_instance="seed", query="existing-directory"
            )
            print(f"{creator['name']}: @{acct} ({links} YouTube channel link(s))")
        except (MastodonError, ValueError) as exc:
            failures += 1
            print(f"WARN {creator['name']}: {exc}", file=sys.stderr)
    db.commit()
    print(f"Seeded {len(creators) - failures}/{len(creators)} existing creators.")
    return 1 if failures else 0


def seed_known(args: argparse.Namespace) -> int:
    """Look up curated well-known creators by address and store them.

    Bypasses fuzzy account_search (which can't see bio text) so creators whose
    handle isn't topical — e.g. Matt Parker @standupmaths — are still found.
    """
    api = mastodon.client_from_env()
    db = mastodon_discovery.connect(args.db)
    handles = args.handle or KNOWN_CREATOR_HANDLES
    found = with_links = 0
    for handle in handles:
        try:
            account = api.account_lookup(handle)
        except (MastodonError, ValueError) as exc:
            print(f"WARN {handle}: lookup failed: {exc}", file=sys.stderr)
            continue
        acct, links = mastodon_discovery.store_account(
            db, account, source_instance="seed-known", query="known-creator"
        )
        found += 1
        with_links += bool(links)
        note = f"{links} channel link(s)" if links else "no channel link — won't publish"
        print(f"{handle}: @{acct} ({note})")
    db.commit()
    print(f"Looked up {found}/{len(handles)} known creators; {with_links} have channel evidence.")
    return 0


def seed_wikidata(args: argparse.Namespace) -> int:
    """Seed from Wikidata: items with both a YouTube channel (P2397) and a
    Mastodon address (P4033).

    Wikidata is a YouTube-first source — every item is already cross-referenced
    to a channel — so it complements topical ``account_search``. Each Mastodon
    handle is resolved to a live profile (like ``seed-known``) and stored, with
    the Wikidata channel carried as fallback evidence so creators who omit their
    channel from their bio still surface. The usual activity / English / channel
    gates still apply at publish time.
    """
    if args.refresh or not wikidata.DEFAULT_CACHE_PATH.exists():
        print("Fetching creators from Wikidata SPARQL endpoint…")
        creators = wikidata.fetch_creators(max_items=args.max_items)
        wikidata.cache_creators(creators)
        print(f"Cached {len(creators)} Wikidata creators to {wikidata.DEFAULT_CACHE_PATH}")
    else:
        creators = wikidata.load_cached()
        print(f"Loaded {len(creators)} cached Wikidata creators (pass --refresh to re-fetch).")

    if args.max_items is not None:
        creators = creators[: args.max_items]

    api = mastodon.client_from_env()
    db = mastodon_discovery.connect(args.db)
    found = with_links = failed = 0
    for index, creator in enumerate(creators, start=1):
        try:
            account = api.account_lookup(creator.mastodon_acct)
            acct, links = mastodon_discovery.store_account(
                db,
                account,
                source_instance="wikidata",
                query=f"wikidata:{creator.qid}",
                extra_links=[(creator.youtube_url, f"wikidata:{creator.qid}", "youtube")],
            )
        except (MastodonError, ValueError) as exc:
            # One unresolvable or malformed account must never abort a run of
            # ~1,700 — log it and keep going.
            failed += 1
            print(f"WARN {creator.mastodon_acct} ({creator.label}): {exc}", file=sys.stderr)
            continue
        found += 1
        with_links += bool(links)
        print(f"{creator.mastodon_acct}: @{acct} ({links} channel link(s)) [{creator.label}]")
        # Commit periodically so a crash or interrupt never discards a long run's
        # progress (the previous end-only commit lost ~1,600 lookups on a print
        # crash). Pacing the Mastodon API makes the run long; checkpoint often.
        if index % 25 == 0:
            db.commit()
    db.commit()
    print(
        f"Resolved {found}/{len(creators)} Wikidata creators "
        f"({failed} lookup failures); {with_links} have channel evidence."
    )
    return 0


def audit(args: argparse.Namespace) -> int:
    api = mastodon.client_from_env()
    db = mastodon_discovery.connect(args.db)
    creators = youtuber_store.load()
    kept: list[dict] = []
    removed: list[tuple[dict, str]] = []

    for creator in creators:
        try:
            account = mastodon.lookup_account(api, creator["mastodon_url"])
            mastodon_discovery.store_account(
                db, account, source_instance="audit", query="existing-directory"
            )
            links = mastodon_discovery.youtube_links(account)
            if not links:
                removed.append((creator, "Mastodon profile has no direct YouTube channel link"))
                continue
            if not publish_candidates.is_active(account.get("last_status_at")):
                removed.append((creator, "No Mastodon post in the last year (inactive)"))
                continue
            kept.append(creator)
        except (MastodonError, ValueError) as exc:
            removed.append((creator, f"Mastodon lookup failed: {exc}"))

    db.commit()
    for creator, reason in removed:
        print(f"REMOVE {creator['name']}: {reason}")
    print(f"Keep {len(kept)}; remove {len(removed)}.")

    if args.write:
        youtuber_store.save(kept)
        print(f"Wrote {youtuber_store.YOUTUBERS_PATH}")
    elif removed:
        print("Dry run only; pass --write to replace the published dataset.")
    return 0


def report(args: argparse.Namespace) -> int:
    db = mastodon_discovery.connect(args.db)
    totals = mastodon_discovery.stats(db)
    print(json.dumps(totals, indent=2))
    for item in mastodon_discovery.candidates(db, args.limit):
        print(
            f"{item.followers_count:>9}  @{item.acct:<40}  "
            f"{item.youtube_url}  [{item.evidence_source}]"
        )
    return 0


def classify(args: argparse.Namespace) -> int:
    db = mastodon_discovery.connect(args.db)
    counts = categorize.classify_database(db)
    print(f"Classified {sum(counts.values())} profiles:")
    for category in categorize.CATEGORY_SORTORDER:
        print(f"  {categorize.CATEGORY_LABELS[category]}: {counts.get(category, 0)}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Mastodon-first discovery of profiles that link to YouTube channels."
    )
    root.add_argument(
        "--db",
        type=Path,
        default=mastodon_discovery.DEFAULT_DB_PATH,
        help="SQLite candidate database (default: data/mastodon_candidates.sqlite)",
    )
    commands = root.add_subparsers(dest="command", required=True)

    collect_parser = commands.add_parser("collect", help="Search Mastodon and store profile candidates.")
    collect_parser.add_argument("--query", action="append", help="Search query; may be repeated.")
    collect_parser.add_argument("--pages", type=int, default=10, help="Pages per query.")
    collect_parser.add_argument("--limit", type=int, default=40, choices=range(1, 41))
    collect_parser.set_defaults(func=collect)

    seed_parser = commands.add_parser("seed", help="Fetch current directory profiles into SQLite.")
    seed_parser.set_defaults(func=seed)

    seed_known_parser = commands.add_parser(
        "seed-known", help="Look up curated well-known creators by address (bypasses fuzzy search)."
    )
    seed_known_parser.add_argument("--handle", action="append", help="user@instance; may be repeated.")
    seed_known_parser.set_defaults(func=seed_known)

    wikidata_parser = commands.add_parser(
        "seed-wikidata",
        help="Seed from Wikidata items that have both a YouTube channel and a Mastodon address.",
    )
    wikidata_parser.add_argument(
        "--refresh", action="store_true", help="Re-fetch from Wikidata instead of using the cache."
    )
    wikidata_parser.add_argument(
        "--max-items", type=int, default=None, help="Cap the number of Wikidata creators processed."
    )
    wikidata_parser.set_defaults(func=seed_wikidata)

    audit_parser = commands.add_parser(
        "audit", help="Keep only directory entries whose Mastodon profile links to YouTube."
    )
    audit_parser.add_argument("--write", action="store_true", help="Replace data/youtubers.json.")
    audit_parser.set_defaults(func=audit)

    report_parser = commands.add_parser("report", help="Show discovered profiles with YouTube evidence.")
    report_parser.add_argument("--limit", type=int, default=100)
    report_parser.set_defaults(func=report)

    classify_parser = commands.add_parser(
        "classify", help="Categorize every profile with YouTube channel evidence."
    )
    classify_parser.set_defaults(func=classify)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
