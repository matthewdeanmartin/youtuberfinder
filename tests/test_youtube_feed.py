from __future__ import annotations

import unittest

from pipeline import youtube_feed


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <title>Sample Channel</title>
  <entry>
    <title>Newest video</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=aaa"/>
    <published>2026-06-20T12:00:00+00:00</published>
  </entry>
  <entry>
    <title>Older video</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=bbb"/>
    <published>2026-06-18T09:30:00+00:00</published>
  </entry>
  <entry>
    <title>Third video</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=ccc"/>
    <published>2026-06-15T09:30:00+00:00</published>
  </entry>
</feed>
"""


class ChannelIdTests(unittest.TestCase):
    def test_extracts_id_from_channel_url(self) -> None:
        url = "https://www.youtube.com/channel/UCsnGwSIHyoYN0kiINAGUKxg"
        self.assertEqual(youtube_feed.channel_id_from_url(url), "UCsnGwSIHyoYN0kiINAGUKxg")

    def test_channel_url_with_trailing_path(self) -> None:
        url = "https://www.youtube.com/channel/UCsnGwSIHyoYN0kiINAGUKxg/videos"
        self.assertEqual(youtube_feed.channel_id_from_url(url), "UCsnGwSIHyoYN0kiINAGUKxg")

    def test_empty_url_returns_none(self) -> None:
        self.assertIsNone(youtube_feed.channel_id_from_url(""))


class FeedParsingTests(unittest.TestCase):
    def test_parses_titles_and_dates(self) -> None:
        videos = youtube_feed._parse_feed(SAMPLE_FEED, limit=5)
        self.assertEqual(len(videos), 3)
        self.assertEqual(videos[0].title, "Newest video")
        self.assertEqual(videos[0].url, "https://www.youtube.com/watch?v=aaa")
        self.assertEqual(videos[0].published, "2026-06-20")

    def test_respects_limit(self) -> None:
        videos = youtube_feed._parse_feed(SAMPLE_FEED, limit=2)
        self.assertEqual(len(videos), 2)

    def test_malformed_feed_returns_empty(self) -> None:
        self.assertEqual(youtube_feed._parse_feed("not xml", limit=5), [])


if __name__ == "__main__":
    unittest.main()
