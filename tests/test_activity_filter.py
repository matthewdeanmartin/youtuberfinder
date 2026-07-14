from __future__ import annotations

import unittest
from datetime import UTC, datetime

from pipeline.publish_candidates import is_active

NOW = datetime(2026, 6, 24, tzinfo=UTC)


class ActivityFilterTests(unittest.TestCase):
    def test_recent_post_is_active(self) -> None:
        self.assertTrue(is_active("2026-06-01T00:00:00+00:00", now=NOW))

    def test_old_post_is_inactive(self) -> None:
        self.assertFalse(is_active("2024-01-01T00:00:00+00:00", now=NOW))

    def test_missing_is_inactive(self) -> None:
        self.assertFalse(is_active(None, now=NOW))
        self.assertFalse(is_active("", now=NOW))

    def test_naive_timestamp_treated_as_utc(self) -> None:
        self.assertTrue(is_active("2026-06-01", now=NOW))

    def test_accepts_datetime(self) -> None:
        self.assertTrue(is_active(datetime(2026, 5, 1, tzinfo=UTC), now=NOW))

    def test_exactly_one_year_is_active(self) -> None:
        self.assertTrue(is_active("2025-06-24T00:00:00+00:00", now=NOW))

    def test_invalid_string_is_inactive(self) -> None:
        self.assertFalse(is_active("not-a-date", now=NOW))


if __name__ == "__main__":
    unittest.main()
