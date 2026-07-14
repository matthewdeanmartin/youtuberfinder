from __future__ import annotations

import unittest
from datetime import UTC, date, datetime

from pipeline.collections import Candidate, allows_public_collection, choose_members, strength

NOW = datetime(2026, 7, 14, tzinfo=UTC)


def candidate(
    account_id: str,
    *,
    youtube: date = date(2026, 7, 1),
    mastodon: str = "2026-07-01",
    followers: int = 100,
    subscribers: int = 1000,
    approval: list[str] | None = None,
) -> Candidate:
    return Candidate(
        creator={
            "name": f"Creator {account_id}",
            "account_type": "native",
            "subscriber_count": subscribers,
        },
        account={
            "id": account_id,
            "last_status_at": mastodon,
            "followers_count": followers,
            "feature_approval": {"automatic": approval if approval is not None else ["public"]},
        },
        youtube_last_upload=youtube,
    )


class CollectionPolicyTests(unittest.TestCase):
    def test_public_automatic_consent_is_required(self) -> None:
        self.assertTrue(allows_public_collection(candidate("1").account))
        self.assertFalse(allows_public_collection(candidate("2", approval=[]).account))
        self.assertFalse(allows_public_collection(candidate("3", approval=["followers"]).account))

    def test_requires_both_activity_windows(self) -> None:
        candidates = [
            candidate("good"),
            candidate("old-youtube", youtube=date(2024, 1, 1)),
            candidate("old-mastodon", mastodon="2025-01-01"),
        ]
        chosen = choose_members(candidates, [], limit=25, youtube_days=365, mastodon_days=90, now=NOW)
        self.assertEqual([item.account_id for item in chosen], ["good"])

    def test_eligible_incumbents_are_stable(self) -> None:
        incumbent = candidate("incumbent", followers=1, subscribers=1)
        star = candidate("star", followers=1_000_000, subscribers=1_000_000)
        chosen = choose_members(
            [star, incumbent], ["incumbent"], limit=1, youtube_days=365, mastodon_days=90, now=NOW
        )
        self.assertEqual([item.account_id for item in chosen], ["incumbent"])

    def test_cross_platform_strength_fills_vacancies(self) -> None:
        balanced = candidate("balanced", followers=10_000, subscribers=10_000)
        tiny = candidate("tiny", followers=10, subscribers=10)
        self.assertGreater(strength(balanced), strength(tiny))
        chosen = choose_members(
            [tiny, balanced], [], limit=1, youtube_days=365, mastodon_days=90, now=NOW
        )
        self.assertEqual([item.account_id for item in chosen], ["balanced"])


if __name__ == "__main__":
    unittest.main()
