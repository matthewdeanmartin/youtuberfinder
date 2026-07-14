from __future__ import annotations

import unittest

from pipeline import dossier, gemma_review


def _valid_payload(**over) -> dict:
    base = {
        "decision": "include",
        "score": 10,
        "hard_fail": None,
        "criteria": {"A": 2, "B": 2, "C": 2, "D": 2, "E": 2},
        "confidence": "high",
        "language": "en",
        "category": "technology",
        "subcategory": "tech news",
        "hashtags": ["#technology", "#tech"],
        "reason": "Matches, original content, strong presence.",
    }
    base.update(over)
    return base


class DossierTests(unittest.TestCase):
    def _creator(self, **over) -> dict:
        base = {
            "id": "ars-technica",
            "name": "Ars Technica",
            "youtube_url": "https://www.youtube.com/channel/UCCDU1fsmgvWljcW2aodfJsA",
            "mastodon_acct": "arstechnica@mastodon.social",
            "subscriber_count": 391000,
            "video_count": 1200,
            "description": "Original news, reviews, analysis of tech trends.",
            "language": "en",
        }
        base.update(over)
        return base

    def test_front_matter_carries_id(self) -> None:
        text = dossier.dossier_markdown(self._creator())
        self.assertEqual(dossier.parse_dossier_id(text), "ars-technica")
        self.assertEqual(dossier.dossier_filename(self._creator()), "ars-technica.md")

    def test_unknown_counts_render_as_unknown(self) -> None:
        text = dossier.dossier_markdown(self._creator(subscriber_count=None, video_count=None))
        self.assertIn("subscriber_count: unknown", text)
        self.assertIn("video_count: unknown", text)

    def test_bio_is_truncated_and_single_line(self) -> None:
        text = dossier.dossier_markdown(self._creator(description="x " * 600))
        bio_line = [ln for ln in text.splitlines() if ln.startswith("- mastodon_bio:")][0]
        self.assertLessEqual(len(bio_line), len("- mastodon_bio: ") + 500)
        self.assertTrue(bio_line.endswith("…"))

    def test_withheld_fields_absent(self) -> None:
        text = dossier.dossier_markdown(self._creator(suspended=False, last_status_at="2026-01-01"))
        self.assertNotIn("suspended", text)
        self.assertNotIn("last_status_at", text)


class ExtractJsonTests(unittest.TestCase):
    def test_plain_object(self) -> None:
        self.assertEqual(gemma_review.extract_json('{"a": 1}'), {"a": 1})

    def test_object_in_code_fence_with_prose(self) -> None:
        msg = 'Sure!\n```json\n{"a": 1, "b": {"c": 2}}\n```\nHope that helps.'
        self.assertEqual(gemma_review.extract_json(msg), {"a": 1, "b": {"c": 2}})

    def test_braces_inside_strings_dont_break_balance(self) -> None:
        self.assertEqual(gemma_review.extract_json('{"reason": "a } b { c"}'), {"reason": "a } b { c"})

    def test_no_json_raises(self) -> None:
        with self.assertRaises(gemma_review.ReviewValidationError):
            gemma_review.extract_json("no json here")


class ValidatePayloadTests(unittest.TestCase):
    def test_valid_include(self) -> None:
        result = gemma_review.validate_payload(_valid_payload())
        self.assertEqual(result.decision, "include")
        self.assertEqual(result.category, "technology")
        self.assertEqual(result.hashtags, ["#technology", "#tech"])

    def test_score_must_match_criteria_sum(self) -> None:
        with self.assertRaises(gemma_review.ReviewValidationError):
            gemma_review.validate_payload(_valid_payload(score=9))

    def test_criteria_out_of_range(self) -> None:
        with self.assertRaises(gemma_review.ReviewValidationError):
            gemma_review.validate_payload(
                _valid_payload(criteria={"A": 3, "B": 2, "C": 2, "D": 2, "E": 2}, score=11)
            )

    def test_hard_fail_requires_exclude(self) -> None:
        with self.assertRaises(gemma_review.ReviewValidationError):
            gemma_review.validate_payload(_valid_payload(hard_fail="H1"))

    def test_unknown_category_rejected(self) -> None:
        with self.assertRaises(gemma_review.ReviewValidationError):
            gemma_review.validate_payload(_valid_payload(category="cooking"))

    def test_bad_hashtag_shape_rejected(self) -> None:
        with self.assertRaises(gemma_review.ReviewValidationError):
            gemma_review.validate_payload(_valid_payload(hashtags=["technology"]))

    def test_too_many_hashtags_rejected(self) -> None:
        with self.assertRaises(gemma_review.ReviewValidationError):
            gemma_review.validate_payload(_valid_payload(hashtags=[f"#t{i}" for i in range(9)]))

    def test_invalid_language_for_included(self) -> None:
        with self.assertRaises(gemma_review.ReviewValidationError):
            gemma_review.validate_payload(_valid_payload(language="english"))

    def test_exclude_clears_category_fields(self) -> None:
        payload = _valid_payload(
            decision="exclude",
            hard_fail="H2",
            criteria={"A": 0, "B": 0, "C": 0, "D": 0, "E": 0},
            score=0,
            category="technology",
            subcategory="tech",
            hashtags=["#tech"],
        )
        result = gemma_review.validate_payload(payload)
        self.assertIsNone(result.category)
        self.assertIsNone(result.subcategory)
        self.assertEqual(result.hashtags, [])

    def test_build_messages_puts_rubric_first(self) -> None:
        msgs = gemma_review.build_messages("RUBRIC", "DOSSIER")
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[0]["content"], "RUBRIC")
        self.assertEqual(msgs[1]["role"], "user")
        self.assertEqual(msgs[1]["content"], "DOSSIER")


if __name__ == "__main__":
    unittest.main()
