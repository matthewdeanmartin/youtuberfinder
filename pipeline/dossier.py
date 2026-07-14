"""Render a compact, human-auditable dossier for each creator.

A dossier is the exact text a Gemma-class model sees when judging a creator
against ``spec/rubric.md``. It is plain Markdown with a small YAML front-matter
block that carries the creator ``id`` so a model result can be matched back to
the source record in ``data/youtubers.json`` with zero ambiguity.

These functions are pure (no I/O, no network) so they are trivially testable.
The fields included are *only* the rubric's declared inputs — deliberately not
``last_status_at`` or ``suspended``, which are pre-gates the model must not
re-judge.
"""
from __future__ import annotations

import re

SCHEMA_VERSION = 1

# Mastodon bios can be long; the rubric asks for ~500 chars. Keep the dossier
# small so a 2–9B model stays focused and prompt cost stays low.
_BIO_MAX_CHARS = 500

_FRONT_MATTER_ID_RE = re.compile(r"^id:\s*(\S+)\s*$", re.MULTILINE)


def _clean(text: str | None) -> str:
    """Collapse whitespace/newlines so a value stays on one dossier line."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _truncate(text: str, limit: int) -> str:
    text = _clean(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _num_or_unknown(value) -> str:
    return str(value) if isinstance(value, int) else "unknown"


def dossier_filename(creator: dict) -> str:
    """Stable dossier filename for a creator (``"<id>.md"``)."""
    return f"{creator['id']}.md"


def parse_dossier_id(text: str) -> str | None:
    """Extract the creator ``id`` from a dossier's front matter, or ``None``."""
    match = _FRONT_MATTER_ID_RE.search(text or "")
    return match.group(1) if match else None


def dossier_markdown(creator: dict) -> str:
    """Render the dossier Markdown for one creator.

    The body lists exactly the rubric input fields. ``mastodon_bio`` is the
    creator's stored ``description`` (the blurb scraped from the profile),
    truncated; if a richer bio field is added later it can be swapped in here.
    """
    cid = creator["id"]
    name = _clean(creator.get("name"))
    youtube_url = creator.get("primary_url") or creator.get("youtube_url") or ""
    subscriber_count = _num_or_unknown(creator.get("subscriber_count"))
    video_count = _num_or_unknown(creator.get("video_count"))
    mastodon_acct = creator.get("mastodon_acct") or ""
    description = _clean(creator.get("description"))
    bio = _truncate(creator.get("description") or "", _BIO_MAX_CHARS)
    language = creator.get("language") or "unknown"

    # Front matter is intentionally minimal — just what's needed to match the
    # result back and audit it. The body carries the model-facing fields.
    return (
        "---\n"
        f"id: {cid}\n"
        f"schema_version: {SCHEMA_VERSION}\n"
        f"name: {name}\n"
        f"mastodon_acct: {mastodon_acct}\n"
        "---\n\n"
        f"# {name or cid}\n\n"
        "Evaluate this creator against the inclusion rubric.\n\n"
        f"- name: {name}\n"
        f"- youtube_url: {youtube_url}\n"
        f"- subscriber_count: {subscriber_count}\n"
        f"- video_count: {video_count}\n"
        f"- mastodon_acct: {mastodon_acct}\n"
        f"- mastodon_bio: {bio}\n"
        f"- description: {description}\n"
        f"- language: {language}\n"
    )
