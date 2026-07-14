"""Refresh the public Mastodon Collections owned by @youtuberfinder.

Dry-run is the default. Pass --apply to create or mutate live Collections.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import collections as policy
from pipeline import youtuber_store, youtube_feed

DEFAULT_CONFIG = ROOT / "data" / "mastodon_collections.json"


class MastodonAPIError(RuntimeError):
    pass


class MastodonAPI:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "youtuberfinder-collections/1.0"})
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def request(self, method: str, path: str, **kwargs):
        response = self.session.request(method, self.base_url + path, timeout=30, **kwargs)
        if response.status_code == 429:
            reset = response.headers.get("X-RateLimit-Reset")
            wait = 60
            if reset:
                try:
                    from datetime import UTC, datetime

                    wait = max(1, int((datetime.fromisoformat(reset).astimezone(UTC) - datetime.now(UTC)).total_seconds()) + 1)
                except ValueError:
                    pass
            print(f"Rate limited by Mastodon; waiting {wait}s…")
            time.sleep(wait)
            response = self.session.request(method, self.base_url + path, timeout=30, **kwargs)
        if not response.ok:
            detail = response.text[:500]
            raise MastodonAPIError(f"{method} {path}: HTTP {response.status_code}: {detail}")
        return response.json() if response.content else None

    def lookup(self, acct: str) -> dict:
        return self.request("GET", "/api/v1/accounts/lookup", params={"acct": acct})

    def verify_credentials(self) -> dict:
        return self.request("GET", "/api/v1/accounts/verify_credentials")

    def instance(self) -> dict:
        return self.request("GET", "/api/v2/instance")

    def collections_for(self, account_id: str) -> list[dict]:
        payload = self.request("GET", f"/api/v1/accounts/{account_id}/collections", params={"limit": 80})
        return payload.get("collections", [])

    def collection(self, collection_id: str) -> dict:
        return self.request("GET", f"/api/v1/collections/{collection_id}").get("collection", {})

    def create_collection(self, metadata: dict) -> dict:
        return self.request("POST", "/api/v1/collections", json=metadata).get("collection", {})

    def update_collection(self, collection_id: str, metadata: dict) -> dict:
        return self.request("PATCH", f"/api/v1/collections/{collection_id}", json=metadata).get("collection", {})

    def add_item(self, collection_id: str, account_id: str) -> None:
        self.request("POST", f"/api/v1/collections/{collection_id}/items", json={"account_id": account_id})

    def remove_item(self, collection_id: str, item_id: str) -> None:
        self.request("DELETE", f"/api/v1/collections/{collection_id}/items/{item_id}")


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(path: Path, config: dict) -> None:
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collection_metadata(item: dict) -> dict:
    return {
        "name": item["name"],
        "description": item["description"],
        "language": "en",
        "tag_name": item["tag_name"],
        "sensitive": False,
        "discoverable": True,
    }


def youtube_last_upload(creator: dict):
    published, observed = youtube_feed.latest_upload_observation(
        creator["youtube_url"], creator.get("youtube_channel_id")
    )
    return policy.parse_date(published), observed


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize topic Collections on Mastodon.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--apply", action="store_true", help="Apply changes; otherwise only print the plan")
    parser.add_argument("--limit-creators", type=int, help="Development-only limit before API lookups")
    args = parser.parse_args()
    if args.apply and args.limit_creators:
        parser.error("--limit-creators is for dry-run development only and cannot be combined with --apply")

    config = load_config(args.config)
    token = os.environ.get("MASTODON_ACCESS_TOKEN") or os.environ.get("MASTODON_ID_TECH_ACCESS_TOKEN")
    if args.apply and not token:
        parser.error("--apply requires MASTODON_ACCESS_TOKEN")
    api = MastodonAPI(os.environ.get("MASTODON_BASE_URL", config["base_url"]), token)

    api_version = int(api.instance().get("api_versions", {}).get("mastodon", 0))
    if api_version < 10:
        raise RuntimeError("The configured Mastodon server does not support Collections (API version 10+ required).")

    if token:
        owner = api.verify_credentials()
        expected = config["account"].split("@", 1)[0].casefold()
        if str(owner.get("username", "")).casefold() != expected:
            raise RuntimeError(f"Access token belongs to @{owner.get('username')}, expected @{expected}")
        collection_limit = int((owner.get("role") or {}).get("collection_limit") or 10)
        if collection_limit < len(config["collections"]):
            raise RuntimeError(f"Account role permits {collection_limit} Collections; {len(config['collections'])} are configured")
    else:
        owner = api.lookup(config["account"])

    remote_by_id = {item["id"]: item for item in api.collections_for(str(owner["id"]))}
    remote_by_name = {item["name"]: item for item in remote_by_id.values()}
    remote_details = {
        collection_id: api.collection(str(collection_id)) for collection_id in remote_by_id
    }
    existing_account_ids = {
        str(item["account_id"])
        for collection in remote_details.values()
        for item in collection.get("items", [])
        if item.get("account_id")
    }

    creators = [item for item in youtuber_store.load() if item.get("account_type") == "native"]
    if args.limit_creators:
        creators = creators[: args.limit_creators]
    print(f"Refreshing Mastodon activity for {len(creators)} native creators…")
    accounts: dict[str, dict] = {}
    skipped = Counter()
    lookup_failures = []
    for index, creator in enumerate(creators, 1):
        try:
            account = api.lookup(creator["mastodon_acct"])
        except MastodonAPIError as exc:
            skipped["Mastodon lookup failed"] += 1
            lookup_failures.append(creator["mastodon_acct"])
            print(f"  warning: {creator['mastodon_acct']}: {exc}")
            continue
        accounts[creator["mastodon_acct"].casefold()] = account
        if index % 100 == 0:
            print(f"  checked {index}/{len(creators)}")
    if lookup_failures:
        raise RuntimeError(
            f"Aborting safely after {len(lookup_failures)} Mastodon lookup failure(s); no Collections changed"
        )

    candidates: list[policy.Candidate] = []
    mastodon_eligible: list[tuple[dict, dict]] = []
    for creator in creators:
        account = accounts.get(creator["mastodon_acct"].casefold())
        if not account:
            continue
        if not policy.is_recent(account.get("last_status_at"), config["mastodon_active_days"]):
            skipped["Mastodon inactive"] += 1
        elif not policy.allows_public_collection(account):
            skipped["Collection consent unavailable"] += 1
        else:
            mastodon_eligible.append((creator, account))

    print(f"Fetching YouTube RSS for {len(mastodon_eligible)} Mastodon-active, consenting creators…")
    for index, (creator, account) in enumerate(mastodon_eligible, 1):
        latest, observed = youtube_last_upload(creator)
        if not observed:
            skipped["YouTube activity unavailable"] += 1
            # Preserve an incumbent when the feed cannot be checked. New
            # candidates wait for a later successful observation.
            if str(account.get("id")) not in existing_account_ids:
                continue
            from datetime import UTC, datetime

            latest = datetime.now(UTC).date()
        candidate = policy.Candidate(creator, account, latest)
        candidates.append(candidate)
        if not policy.is_recent(latest, config["youtube_active_days"]):
            skipped["YouTube inactive"] += 1
        if index % 50 == 0:
            print(f"  checked {index}/{len(mastodon_eligible)}")

    changed_config = False
    for spec in config["collections"]:
        remote = remote_by_id.get(str(spec.get("id"))) if spec.get("id") else None
        remote = remote or remote_by_name.get(spec["name"])
        existing_items = (remote_details.get(str(remote["id"]), {}).get("items", []) if remote else [])
        existing_ids = [str(item.get("account_id")) for item in existing_items if item.get("account_id")]
        category_candidates = [c for c in candidates if c.creator.get("category") == spec["category"]]
        selected = policy.choose_members(
            category_candidates,
            existing_ids,
            limit=int(config["max_size"]),
            youtube_days=int(config["youtube_active_days"]),
            mastodon_days=int(config["mastodon_active_days"]),
        )
        selected_ids = [candidate.account_id for candidate in selected]
        selected_names = {candidate.account_id: candidate.creator["name"] for candidate in selected}
        remove = [item for item in existing_items if str(item.get("account_id")) not in selected_ids]
        add = [account_id for account_id in selected_ids if account_id not in existing_ids]
        action = "create" if not remote else "update"
        print(f"\n{spec['name']}: {action}; keep {len(existing_ids) - len(remove)}, remove {len(remove)}, add {len(add)} -> {len(selected)}")
        for item in remove:
            print(f"  - account {item.get('account_id')}")
        for account_id in add:
            print(f"  + {selected_names[account_id]}")

        if not args.apply:
            continue
        metadata = collection_metadata(spec)
        if not remote:
            remote = api.create_collection(metadata)
        else:
            api.update_collection(str(remote["id"]), metadata)
        # Remove first so a full Collection has room for replacements.
        for item in remove:
            api.remove_item(str(remote["id"]), str(item["id"]))
        for account_id in add:
            api.add_item(str(remote["id"]), account_id)
        if spec.get("id") != remote.get("id") or spec.get("url") != remote.get("url"):
            spec["id"] = remote.get("id")
            spec["url"] = remote.get("url")
            changed_config = True

    if skipped:
        print("\nSkipped: " + ", ".join(f"{reason}: {count}" for reason, count in sorted(skipped.items())))
    if args.apply and changed_config:
        save_config(args.config, config)
        print(f"Saved Collection IDs and URLs to {args.config}")
    print("\nApplied live changes." if args.apply else "\nDry run only; no Mastodon Collections were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
