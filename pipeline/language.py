"""Heuristic language detection shared by the publish pipeline and the
stand-alone ``scripts/detect_language.py`` tool.

The directory is English-only, so the job here is narrow: decide whether a
creator's name + bio is primarily English, and reject the rest. We classify in
two stages, both dependency-free:

1. **Script test** — a high CJK ratio means Japanese ("ja").
2. **Stopword test** — for Latin-script text, count short, highly
   language-specific function words (der/und/für, het/een/voor, ...). These
   dominate real sentences but almost never appear in English bios, so even a
   couple of hits is strong evidence the account is not English. This matters
   because Wikidata contributes many German, Dutch, French and Spanish
   institutional accounts whose bios would otherwise be assumed English.

Returns a BCP 47 base tag ("en", "ja", "de", "nl", "fr", "es"). The publish
pipeline keeps only "en"; every other tag is dropped from the English-only
directory.
"""
from __future__ import annotations

import re
import unicodedata

# Function words that are common in the target language and rare in English.
# Kept short and unambiguous; an English bio essentially never accumulates two
# of these. Order matters only for reporting — scoring picks the highest count.
STOPWORDS: dict[str, frozenset[str]] = {
    "de": frozenset({
        "der", "die", "das", "und", "für", "den", "dem", "des", "ein", "eine",
        "ist", "von", "mit", "sich", "auf", "im", "zu", "wir", "uns", "unsere",
        "nicht", "auch", "über", "oder", "aus", "bei", "wird", "werden", "hier",
    }),
    "nl": frozenset({
        "het", "een", "voor", "wij", "onze", "van", "met", "niet", "ook", "naar",
        "zijn", "wordt", "worden", "deze", "dit", "tussen", "over", "bij", "uit",
    }),
    # French/Spanish deliberately omit short words that collide with English or
    # appear as English fragments ("la", "le", "des", "que", "en", "no", "su",
    # "se", "un"). Only function words that are unambiguous in running French /
    # Spanish text remain, so an English bio won't accumulate two of them.
    "fr": frozenset({
        "les", "une", "pour", "nous", "vous", "avec", "dans", "sur", "est",
        "sont", "pas", "qui", "plus", "aux", "notre", "votre", "cette",
        "depuis", "leur", "ses", "ces", "été",
    }),
    "es": frozenset({
        "los", "las", "una", "para", "con", "por", "del", "como", "más",
        "nuestra", "nuestro", "somos", "este", "esta", "desde", "está",
        "también", "pero", "sus", "comunicación",
    }),
}

# Two or more matching function words is a confident non-English signal; one
# stray word (e.g. an English bio that says "von Neumann") is not enough.
STOPWORD_THRESHOLD = 2

_WORD_RE = re.compile(r"[a-zàâäçéèêëîïôöùûüáíóúñ]+", re.IGNORECASE)


def cjk_ratio(text: str) -> float:
    """Fraction of *letter* codepoints that are CJK / kana / hangul."""
    if not text:
        return 0.0
    letters = [c for c in text if unicodedata.category(c).startswith("L")]
    if not letters:
        return 0.0
    cjk = [
        c
        for c in letters
        if (
            "　" <= c <= "鿿"  # CJK unified + kana blocks
            or "가" <= c <= "퟿"  # Hangul
            or "豈" <= c <= "﫿"  # CJK compatibility
            or "㐀" <= c <= "䶿"  # CJK extension A
        )
    ]
    return len(cjk) / len(letters)


def _stopword_language(text: str) -> str | None:
    """Return the best-matching non-English language tag, or ``None`` if the
    text doesn't reach the threshold for any of them (i.e. treat as English)."""
    tokens = set(_WORD_RE.findall(text.casefold()))
    if not tokens:
        return None
    best_lang: str | None = None
    best_hits = STOPWORD_THRESHOLD - 1
    for lang, words in STOPWORDS.items():
        hits = len(tokens & words)
        if hits > best_hits:
            best_hits, best_lang = hits, lang
    return best_lang


def detect_language(creator: dict) -> str:
    """Return a BCP 47 base language tag for the creator."""
    name = creator.get("name") or ""
    description = creator.get("description") or ""

    # RSS-bot accounts on rss-mstdn.studiofreesia.com always append Japanese
    # boilerplate to the description; only trust the channel name for those.
    is_rss_bot = "rss-mstdn.studiofreesia.com" in (creator.get("mastodon_acct") or "")
    if is_rss_bot:
        text = name
    else:
        # Weight name heavily: repeat it 5 times so a Japanese name wins over
        # an incidental CJK character in an otherwise English description.
        text = (name + " ") * 5 + description

    # A high CJK *ratio* alone is fooled by very short text — one kanji in a
    # repeated two-word name clears 0.15. Require a handful of CJK letters in
    # absolute terms too, so an English bio with a single decorative CJK glyph
    # (e.g. "NPR Music 🎵" mirror accounts) isn't mislabelled Japanese.
    cjk_letters = sum(1 for c in (name + " " + description) if cjk_ratio(c) == 1.0)
    if cjk_ratio(text) > 0.15 and cjk_letters >= 4:
        return "ja"
    # The name is repeated above, which would over-count a stopword that happens
    # to sit in the name. Run the European-language test on the *raw* name + bio
    # so word counts reflect the real text.
    european = _stopword_language(f"{name} {description}")
    if european is not None:
        return european
    return "en"
