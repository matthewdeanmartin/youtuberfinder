"""Heuristic language detection for youtubers.json.

Detects whether a creator's content is primarily Japanese (CJK characters
in name or description) or English, and stamps the ``language`` field with a
BCP 47 base tag ("ja" / "en").

Run locally and commit the updated youtubers.json.  New entries with an
existing non-null language tag are left unchanged so manual overrides survive.

Usage:
    uv run python scripts/detect_language.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import youtuber_store
from pipeline.language import detect_language


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Stamp BCP 47 language tags onto youtubers.json")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-detect even when language is already set",
    )
    args = parser.parse_args()

    youtubers = youtuber_store.load()
    changed = 0
    for creator in youtubers:
        existing = creator.get("language")
        if existing and not args.overwrite:
            continue
        lang = detect_language(creator)
        if lang != existing:
            if args.dry_run:
                print(f"  {creator['id']}: {existing!r} -> {lang!r}")
            creator["language"] = lang
            changed += 1

    print(f"{'Would update' if args.dry_run else 'Updated'} {changed} entries.")
    if not args.dry_run and changed:
        youtuber_store.save(youtubers)
        print("Saved youtubers.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
