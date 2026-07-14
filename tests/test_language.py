from __future__ import annotations

import unittest

from pipeline.language import detect_language


class LanguageDetectionTests(unittest.TestCase):
    def _detect(self, name: str = "", description: str = "", **extra) -> str:
        return detect_language({"name": name, "description": description, **extra})

    def test_plain_english_bio(self) -> None:
        self.assertEqual(
            self._detect("DistroTube", "Derek Taylor from the DistroTube channel on YouTube."),
            "en",
        )

    def test_english_with_a_german_surname_stays_english(self) -> None:
        # A single foreign function word (here none, but a name like "von") must
        # not flip an otherwise English bio.
        self.assertEqual(
            self._detect("Jane von Neumann", "I make videos about open source software."),
            "en",
        )

    def test_german_institution_is_rejected(self) -> None:
        self.assertEqual(
            self._detect(
                "Hochschule Anhalt",
                "Offizieller Kanal der Hochschule Anhalt für Studierende und Forschung.",
            ),
            "de",
        )

    def test_dutch_government_is_rejected(self) -> None:
        self.assertEqual(
            self._detect(
                "Provincie Drenthe",
                "Het officiële account van de provincie Drenthe voor nieuws en informatie.",
            ),
            "nl",
        )

    def test_french_is_rejected(self) -> None:
        self.assertEqual(
            self._detect(
                "Alternative Libertaire",
                "Le mensuel de l'Union Communiste Libertaire pour les militants.",
            ),
            "fr",
        )

    def test_spanish_is_rejected(self) -> None:
        self.assertEqual(
            self._detect(
                "El Salto",
                "Somos un medio de comunicación autogestionado y horizontal para todos.",
            ),
            "es",
        )

    def test_japanese_still_detected(self) -> None:
        self.assertEqual(self._detect("ゲーム実況", "毎日ゲーム配信しています"), "ja")

    def test_empty_defaults_to_english(self) -> None:
        self.assertEqual(self._detect("", ""), "en")


if __name__ == "__main__":
    unittest.main()
