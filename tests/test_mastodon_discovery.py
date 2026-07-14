from __future__ import annotations

import unittest

from pipeline.mastodon_discovery import (
    canonical_channel_url,
    canonical_peertube_url,
    canonical_twitch_url,
    canonical_youtube_url,
    youtube_links,
)
from pipeline.categorize import classify


class YouTubeEvidenceTests(unittest.TestCase):
    def test_extracts_channel_from_profile_field(self) -> None:
        account = {
            "note": "<p>Tech videos and Linux things.</p>",
            "fields": [
                {
                    "name": "YouTube",
                    "value": '<a href="https://www.youtube.com/@ExampleTech">videos</a>',
                }
            ],
        }
        self.assertEqual(
            youtube_links(account),
            [("https://www.youtube.com/@ExampleTech", "field:YouTube", "youtube")],
        )

    def test_twitch_and_peertube_links_are_evidence(self) -> None:
        account = {
            "note": '<p>Streams on <a href="https://twitch.tv/SomeStreamer">Twitch</a>.</p>',
            "fields": [
                {
                    "name": "PeerTube",
                    "value": '<a href="https://tilvids.com/c/mychannel/videos">PeerTube</a>',
                }
            ],
        }
        self.assertEqual(
            youtube_links(account),
            [
                ("https://www.twitch.tv/SomeStreamer", "bio", "twitch"),
                ("https://tilvids.com/c/mychannel", "field:PeerTube", "peertube"),
            ],
        )

    def test_text_claim_without_link_is_not_evidence(self) -> None:
        account = {
            "note": "<p>I make YouTube videos.</p>",
            "fields": [],
        }
        self.assertEqual(youtube_links(account), [])

    def test_video_link_is_not_mistaken_for_channel(self) -> None:
        self.assertIsNone(canonical_youtube_url("https://youtu.be/dQw4w9WgXcQ"))
        self.assertIsNone(canonical_youtube_url("https://www.youtube.com/watch?v=abc"))

    def test_channel_forms_are_accepted(self) -> None:
        self.assertEqual(
            canonical_youtube_url("http://youtube.com/channel/UC123?view_as=subscriber"),
            "https://www.youtube.com/channel/UC123",
        )
        self.assertEqual(
            canonical_youtube_url("https://m.youtube.com/@SomeCreator/videos"),
            "https://www.youtube.com/@SomeCreator/videos",
        )

    def test_legacy_vanity_url_is_accepted(self) -> None:
        # youtube.com/<name> is a legacy custom channel URL (e.g. Matt Parker).
        self.assertEqual(
            canonical_youtube_url("http://youtube.com/standupmaths"),
            "https://www.youtube.com/standupmaths",
        )
        self.assertEqual(
            canonical_youtube_url("https://youtube.com/standupmaths"),
            "https://www.youtube.com/standupmaths",
        )

    def test_reserved_single_segment_paths_are_not_channels(self) -> None:
        for url in (
            "https://youtube.com/results",
            "https://youtube.com/shorts",
            "https://youtube.com/feed",
            "https://youtube.com/premium",
        ):
            self.assertIsNone(canonical_youtube_url(url), url)

    def test_vanity_url_in_bio_is_evidence(self) -> None:
        account = {
            "note": '<p>Videos: <a href="http://youtube.com/standupmaths">youtube.com/standupmaths</a></p>',
            "fields": [],
        }
        self.assertEqual(
            youtube_links(account),
            [("https://www.youtube.com/standupmaths", "bio", "youtube")],
        )

    def test_twitch_channel_vs_reserved_routes(self) -> None:
        self.assertEqual(
            canonical_twitch_url("https://twitch.tv/SomeStreamer"),
            "https://www.twitch.tv/SomeStreamer",
        )
        # App routes and multi-segment paths are not channels.
        self.assertIsNone(canonical_twitch_url("https://www.twitch.tv/directory"))
        self.assertIsNone(canonical_twitch_url("https://twitch.tv/foo/bar"))

    def test_peertube_channel_permalinks(self) -> None:
        # Recognised by path shape on any instance, with trailing /videos dropped.
        self.assertEqual(
            canonical_peertube_url("https://anyinstance.example/video-channels/cool/videos"),
            "https://anyinstance.example/video-channels/cool",
        )
        self.assertEqual(
            canonical_peertube_url("https://tilvids.com/a/someuser"),
            "https://tilvids.com/a/someuser",
        )
        # A bare host with no channel path is not evidence.
        self.assertIsNone(canonical_peertube_url("https://framatube.org/about"))

    def test_canonical_channel_url_reports_platform(self) -> None:
        self.assertEqual(
            canonical_channel_url("https://www.youtube.com/@x"),
            ("youtube", "https://www.youtube.com/@x"),
        )
        self.assertIsNone(canonical_channel_url("https://example.com/random"))


class CategorizationTests(unittest.TestCase):
    def test_technology_profile(self) -> None:
        result = classify(
            {
                "acct": "example@mastodon.social",
                "display_name": "Linux Teacher",
                "note": "<p>Programming, open source and self-hosting videos.</p>",
                "fields": [],
            }
        )
        self.assertEqual(result.category, "technology")
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.account_type, "native")

    def test_rss_mirror_is_labeled(self) -> None:
        result = classify(
            {
                "acct": "youtube_example@rss-mstdn.studiofreesia.com",
                "display_name": "Game channel",
                "note": "<p>VTuber and gaming videos.</p>",
                "fields": [],
            }
        )
        self.assertEqual(result.category, "gaming")
        self.assertEqual(result.account_type, "rss-feed")


if __name__ == "__main__":
    unittest.main()
