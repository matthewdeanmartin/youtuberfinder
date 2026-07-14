from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from mastodon import MastodonError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import mastodon, youtuber_store

_REQUIRED_ENV = ("MASTODON_ID_TECH_BASE_URL", "MASTODON_ID_TECH_ACCESS_TOKEN")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify every source Mastodon account through its server API.")
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    if not all(os.environ.get(v) for v in _REQUIRED_ENV):
        missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
        print(f"Skipping Mastodon checks — credentials not set ({', '.join(missing)}).")
        print("Run locally with the required env vars or via `just` to enable these checks.")
        return 0

    try:
        youtubers = youtuber_store.load()
    except (OSError, ValueError) as exc:
        print(exc)
        return 1

    failures: list[str] = []
    for creator in youtubers:
        url = creator["mastodon_url"]
        try:
            profile = mastodon.lookup_profile(url, timeout=args.timeout)
            print(f"OK {creator['name']}: @{profile.acct}")
        except (ValueError, MastodonError) as exc:
            failures.append(f"{creator['name']}: {url} -> {exc}")

    if failures:
        print("\nInvalid Mastodon profiles:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"\nVerified {len(youtubers)} Mastodon profiles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
