from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from mastodon import Mastodon


@dataclass(frozen=True)
class MastodonProfile:
    url: str
    acct: str


def parse_profile_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if parsed.scheme != "https" or not parsed.hostname or len(parts) != 1 or not parts[0].startswith("@"):
        raise ValueError("expected https://server/@username")
    username = parts[0][1:]
    if not username:
        raise ValueError("username is empty")
    return parsed.hostname, username


def account_address(url: str) -> str:
    host, username = parse_profile_url(url)
    return f"{username}@{host}"


def client_from_env() -> Mastodon:
    base_url = os.environ.get("MASTODON_ID_TECH_BASE_URL")
    access_token = os.environ.get("MASTODON_ID_TECH_ACCESS_TOKEN")
    if not base_url or not access_token:
        raise RuntimeError(
            "MASTODON_ID_TECH_BASE_URL and MASTODON_ID_TECH_ACCESS_TOKEN are required; "
            "run through `just` or export the variables first"
        )
    return Mastodon(
        api_base_url=base_url,
        client_id=os.environ.get("MASTODON_ID_TECH_CLIENT_ID"),
        client_secret=os.environ.get("MASTODON_ID_TECH_CLIENT_SECRET"),
        access_token=access_token,
        ratelimit_method="pace",
        user_agent="tech-youtubers-discovery/1.0",
    )


def lookup_account(api: Mastodon, url: str):
    return api.account_lookup(account_address(url))


def lookup_profile(url: str, timeout: float = 12.0) -> MastodonProfile:
    # timeout is retained for compatibility with the link-checking CLI. Mastodon.py
    # owns its HTTP session and timeout behavior.
    del timeout
    account = lookup_account(client_from_env(), url)
    if account.get("suspended"):
        raise ValueError("account is suspended")
    canonical_url = account.get("url")
    acct = account.get("acct")
    if not canonical_url or not acct:
        raise ValueError("server returned an incomplete account")
    if "@" not in acct:
        host, _ = parse_profile_url(canonical_url)
        acct = f"{acct}@{host}"
    return MastodonProfile(url=canonical_url, acct=acct)
