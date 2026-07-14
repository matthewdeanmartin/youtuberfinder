from __future__ import annotations

import unittest

import generate_pages


class LinkifyTests(unittest.TestCase):
    def test_plain_url_becomes_link(self) -> None:
        out = generate_pages._linkify("See https://example.com for more.")
        self.assertIn(
            '<a href="https://example.com" target="_blank" rel="noopener noreferrer">'
            "https://example.com</a>",
            out,
        )

    def test_mastodon_split_url_is_stitched(self) -> None:
        # The plain-text extraction leaves a space after the "www." boundary.
        out = generate_pages._linkify("Site: https://www. agora-verkehrswende.de")
        self.assertIn('href="https://www.agora-verkehrswende.de"', out)
        self.assertNotIn("www. agora", out)

    def test_split_after_scheme_only(self) -> None:
        out = generate_pages._linkify("https:// example.com/path")
        self.assertIn('href="https://example.com/path"', out)

    def test_text_is_escaped(self) -> None:
        out = generate_pages._linkify("Tom & Jerry <not a tag>")
        self.assertIn("Tom &amp; Jerry", out)
        self.assertIn("&lt;not a tag&gt;", out)
        self.assertNotIn("<not a tag>", out)

    def test_trailing_punctuation_excluded_from_link(self) -> None:
        out = generate_pages._linkify("Visit https://example.com.")
        self.assertIn('href="https://example.com"', out)
        # The sentence period stays outside the anchor.
        self.assertTrue(out.rstrip().endswith("</a>."))

    def test_no_url_returns_escaped_text(self) -> None:
        self.assertEqual(generate_pages._linkify("just words"), "just words")


if __name__ == "__main__":
    unittest.main()
