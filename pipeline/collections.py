"""Selection policy for Mastodon Collections.

Collections contain at most 25 native accounts that uploaded to YouTube in the
last year, posted on Mastodon in the last 90 days, and allow public automatic
Collection inclusion. Existing eligible members are retained to avoid needless
monthly churn; popularity only ranks the initial set and later vacancies.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Iterable


@dataclass(frozen=True)
class Candidate:
    creator: dict
    account: dict
    youtube_last_upload: date | None

    @property
    def account_id(self) -> str:
        return str(self.account.get("id") or "")


def parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def is_recent(value, days: int, *, now: datetime | None = None) -> bool:
    when = parse_date(value)
    if when is None:
        return False
    today = (now or datetime.now(UTC)).date()
    return today - when <= timedelta(days=days)


def allows_public_collection(account: dict) -> bool:
    """Whether the account permits automatic inclusion in a public Collection."""
    approval = account.get("feature_approval") or {}
    return "public" in (approval.get("automatic") or [])


def strength(candidate: Candidate) -> float:
    """Balanced cross-platform strength; a large value on one site cannot hide zero on the other."""
    mastodon_followers = max(0, int(candidate.account.get("followers_count") or 0))
    youtube_subscribers = max(0, int(candidate.creator.get("subscriber_count") or 0))
    return math.sqrt(math.log1p(mastodon_followers) * math.log1p(youtube_subscribers))


def ineligible_reason(
    candidate: Candidate,
    *,
    youtube_days: int,
    mastodon_days: int,
    now: datetime | None = None,
) -> str | None:
    if candidate.creator.get("account_type") != "native":
        return "not a native account"
    if not is_recent(candidate.youtube_last_upload, youtube_days, now=now):
        return "no YouTube upload in activity window"
    if not is_recent(candidate.account.get("last_status_at"), mastodon_days, now=now):
        return "no Mastodon post in activity window"
    if not allows_public_collection(candidate.account):
        return "Collection inclusion not allowed"
    if not candidate.account_id:
        return "Mastodon account ID unavailable"
    return None


def choose_members(
    candidates: Iterable[Candidate],
    existing_account_ids: Iterable[str],
    *,
    limit: int,
    youtube_days: int,
    mastodon_days: int,
    now: datetime | None = None,
) -> list[Candidate]:
    eligible = {
        candidate.account_id: candidate
        for candidate in candidates
        if ineligible_reason(
            candidate,
            youtube_days=youtube_days,
            mastodon_days=mastodon_days,
            now=now,
        )
        is None
    }
    selected: list[Candidate] = []
    for account_id in existing_account_ids:
        candidate = eligible.pop(str(account_id), None)
        if candidate is not None:
            selected.append(candidate)
    ranked = sorted(
        eligible.values(),
        key=lambda candidate: (-strength(candidate), candidate.creator.get("name", "").casefold()),
    )
    selected.extend(ranked[: max(0, limit - len(selected))])
    return selected[:limit]
