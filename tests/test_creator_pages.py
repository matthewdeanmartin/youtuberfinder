from __future__ import annotations

import unittest

import generate_pages
from pipeline.youtube_feed import Video, video_id_from_url


class VideoIdTests(unittest.TestCase):
    def test_watch_url(self) -> None:
        self.assertEqual(
            video_id_from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_watch_url_with_extra_params(self) -> None:
        self.assertEqual(
            video_id_from_url("https://www.youtube.com/watch?list=PL&v=dQw4w9WgXcQ&t=5"),
            "dQw4w9WgXcQ",
        )

    def test_short_url(self) -> None:
        self.assertEqual(video_id_from_url("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_channel_url_has_no_video_id(self) -> None:
        self.assertIsNone(video_id_from_url("https://www.youtube.com/channel/UCabcdEFGHij_klmnopqrstu"))

    def test_empty(self) -> None:
        self.assertIsNone(video_id_from_url(""))


class LiteEmbedTests(unittest.TestCase):
    def test_card_has_thumbnail_and_play_button(self) -> None:
        video = Video(title="Cool video", url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", published="2026-01-02")
        out = generate_pages._lite_embed_html(video)
        self.assertIn('data-video-id="dQw4w9WgXcQ"', out)
        self.assertIn("i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg", out)
        self.assertIn("video-card__play", out)
        # No iframe at build time — only loaded on click.
        self.assertNotIn("<iframe", out)

    def test_card_without_id_falls_back_to_link(self) -> None:
        video = Video(title="No id", url="https://example.com/x", published="")
        out = generate_pages._lite_embed_html(video)
        self.assertIn("video-card--link", out)
        self.assertIn("No id", out)

    def test_title_is_escaped(self) -> None:
        video = Video(title='<script>"x"', url="https://youtu.be/dQw4w9WgXcQ", published="")
        out = generate_pages._lite_embed_html(video)
        self.assertNotIn("<script>", out)


class CreatorPageTests(unittest.TestCase):
    def _creator(self, **extra) -> dict:
        base = {
            "id": "example-creator",
            "name": "Example Creator",
            "category": "technology",
            "account_type": "native",
            "youtube_url": "https://www.youtube.com/channel/UCabcdEFGHij_klmnopqrstu",
            "primary_url": "https://www.youtube.com/channel/UCabcdEFGHij_klmnopqrstu",
            "mastodon_url": "https://mastodon.social/@example",
            "description": "We make things. https://example.com",
            "followers": 1234,
            "language": "en",
        }
        base.update(extra)
        return base

    def test_page_has_metadata_and_live_section(self) -> None:
        out = generate_pages.generate_creator_page(self._creator(), [])
        self.assertIn("save_as: creator/example-creator/index.html", out)
        self.assertIn("status: hidden", out)
        self.assertIn("data-creator-live", out)
        self.assertIn('data-mastodon-acct="example@mastodon.social"', out)
        # Bio URL is linkified.
        self.assertIn('href="https://example.com"', out)
        # Native account gets a follow button.
        self.assertIn("creator-follow", out)
        # No second <h1> — the page template renders the title heading.
        self.assertNotIn("<h1>", out)

    def test_non_native_has_no_follow_button(self) -> None:
        out = generate_pages.generate_creator_page(self._creator(account_type="rss-feed"), [])
        self.assertNotIn("creator-follow", out)

    def test_creator_link_uses_filename_directive(self) -> None:
        url = generate_pages._creator_page_url(self._creator())
        self.assertEqual(url, "{filename}creator/example-creator.md")


class PopularityScoreTests(unittest.TestCase):
    def test_score_combines_normalised_metrics(self) -> None:
        creators = [
            {"subscriber_count": 100, "followers": 10},
            {"subscriber_count": 300, "followers": 30},
        ]
        generate_pages.compute_popularity_baselines(creators)
        # avg subs = 200, avg followers = 20.
        # creator 2: (300/200) * (30/20) = 1.5 * 1.5 = 2.25
        self.assertAlmostEqual(generate_pages.popularity_score(creators[1]), 2.25)

    def test_missing_metric_scores_zero(self) -> None:
        generate_pages.compute_popularity_baselines(
            [{"subscriber_count": 100, "followers": 10}]
        )
        self.assertEqual(generate_pages.popularity_score({"subscriber_count": 100}), 0.0)
        self.assertEqual(generate_pages.popularity_score({"followers": 10}), 0.0)
        self.assertEqual(generate_pages.popularity_score({}), 0.0)


class CategoryControlsTests(unittest.TestCase):
    def test_controls_toolbar_has_search_and_sorts(self) -> None:
        out = generate_pages._category_controls("native")
        self.assertIn('data-controls="native"', out)
        self.assertIn("data-controls-search", out)
        for mode in ("score", "subscribers", "followers", "alpha", "shuffle"):
            self.assertIn(f'data-controls-sort="{mode}"', out)

    def test_creator_li_stamps_sort_attributes(self) -> None:
        generate_pages.compute_popularity_baselines(
            [{"subscriber_count": 1000, "followers": 50}]
        )
        creator = {
            "id": "x",
            "name": "Zeta",
            "account_type": "native",
            "youtube_url": "https://www.youtube.com/channel/UCabcdEFGHij_klmnopqrstu",
            "primary_url": "https://www.youtube.com/channel/UCabcdEFGHij_klmnopqrstu",
            "mastodon_url": "https://mastodon.social/@zeta",
            "subscriber_count": 1000,
            "followers": 50,
            "language": "en",
        }
        out = generate_pages._creator_li(creator, "Mastodon", [])
        self.assertIn('data-name="zeta"', out)
        self.assertIn('data-subscribers="1000"', out)
        self.assertIn('data-followers="50"', out)
        self.assertIn("data-score=", out)


if __name__ == "__main__":
    unittest.main()
