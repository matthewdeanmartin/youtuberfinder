from __future__ import annotations

import sqlite3
import unittest

from pipeline import mastodon_discovery, wikidata


class WikidataParsingTests(unittest.TestCase):
    def _binding(self, **overrides) -> dict:
        row = {
            "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q42"},
            "itemLabel": {"type": "literal", "value": "Example Creator"},
            "youtubeChannelId": {"type": "literal", "value": "UCabcdEFGHijklmnopqrstuv"},
            "mastodon": {"type": "literal", "value": "example@mastodon.social"},
        }
        row.update(overrides)
        return row

    def test_parse_binding_extracts_qid_and_channel_url(self) -> None:
        creator = wikidata._parse_binding(self._binding())
        assert creator is not None
        self.assertEqual(creator.qid, "Q42")
        self.assertEqual(creator.label, "Example Creator")
        self.assertEqual(creator.mastodon_acct, "example@mastodon.social")
        self.assertEqual(
            creator.youtube_url,
            "https://www.youtube.com/channel/UCabcdEFGHijklmnopqrstuv",
        )

    def test_parse_binding_strips_leading_at_from_handle(self) -> None:
        creator = wikidata._parse_binding(
            self._binding(mastodon={"value": "@example@mastodon.social"})
        )
        assert creator is not None
        self.assertEqual(creator.mastodon_acct, "example@mastodon.social")

    def test_parse_binding_rejects_handle_without_host(self) -> None:
        self.assertIsNone(
            wikidata._parse_binding(self._binding(mastodon={"value": "example"}))
        )

    def test_parse_binding_falls_back_to_qid_label(self) -> None:
        row = self._binding()
        del row["itemLabel"]
        creator = wikidata._parse_binding(row)
        assert creator is not None
        self.assertEqual(creator.label, "Q42")


class ExtraLinksTests(unittest.TestCase):
    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(mastodon_discovery.SCHEMA)
        return db

    def _stored_links(self, db: sqlite3.Connection, acct: str) -> list[tuple[str, str]]:
        rows = db.execute(
            "SELECT youtube_url, evidence_source FROM youtube_links WHERE acct = ?", (acct,)
        ).fetchall()
        return sorted((r["youtube_url"], r["evidence_source"]) for r in rows)

    def test_extra_link_fills_gap_when_profile_has_no_channel(self) -> None:
        db = self._db()
        account = {
            "id": "1",
            "acct": "creator@mastodon.social",
            "url": "https://mastodon.social/@creator",
            "username": "creator",
            "display_name": "Creator",
            "note": "<p>No links in bio.</p>",
        }
        acct, count = mastodon_discovery.store_account(
            db,
            account,
            source_instance="wikidata",
            extra_links=[
                ("https://www.youtube.com/channel/UCxyz", "wikidata:Q1", "youtube")
            ],
        )
        self.assertEqual(count, 1)
        self.assertEqual(
            self._stored_links(db, acct),
            [("https://www.youtube.com/channel/UCxyz", "wikidata:Q1")],
        )

    def test_profile_link_wins_over_duplicate_extra_link(self) -> None:
        db = self._db()
        account = {
            "id": "2",
            "acct": "creator@mastodon.social",
            "url": "https://mastodon.social/@creator",
            "username": "creator",
            "display_name": "Creator",
            "note": '<p><a href="https://www.youtube.com/@creator">channel</a></p>',
        }
        acct, count = mastodon_discovery.store_account(
            db,
            account,
            source_instance="wikidata",
            extra_links=[
                # Same canonical URL the profile yields — must not duplicate.
                ("https://www.youtube.com/@creator", "wikidata:Q2", "youtube")
            ],
        )
        self.assertEqual(count, 1)
        self.assertEqual(
            self._stored_links(db, acct),
            [("https://www.youtube.com/@creator", "bio")],
        )


if __name__ == "__main__":
    unittest.main()
