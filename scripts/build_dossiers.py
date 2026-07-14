"""Write one Markdown dossier per creator into ``dossiers/``.

A dossier is the exact prompt body a Gemma-class model reads to judge a creator
against ``spec/rubric.md`` (see ``pipeline.dossier``). This step is offline and
free; run it anytime to refresh the dossiers before a review run.

Usage::

    uv run python scripts/build_dossiers.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import dossier, youtuber_store

DOSSIERS_DIR = Path(__file__).parent.parent / "dossiers"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print a sample; write nothing")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N creators")
    args = parser.parse_args()

    youtubers = youtuber_store.load()
    scope = youtubers[: args.limit] if args.limit else youtubers
    print(f"Loaded {len(youtubers)} creators; building {len(scope)} dossiers")

    if not args.dry_run:
        DOSSIERS_DIR.mkdir(parents=True, exist_ok=True)

    written = unchanged = skipped = 0
    for creator in scope:
        if not creator.get("id"):
            skipped += 1
            continue
        text = dossier.dossier_markdown(creator)
        path = DOSSIERS_DIR / dossier.dossier_filename(creator)
        if args.dry_run:
            if written < 1:
                print(f"\n--- {path} ---\n{text}")
            written += 1
            continue
        # Idempotent: only rewrite when content actually changed, so a re-run
        # produces a clean diff of just what moved.
        if path.exists() and path.read_text(encoding="utf-8") == text:
            unchanged += 1
            continue
        path.write_text(text, encoding="utf-8")
        written += 1

    if args.dry_run:
        print(f"\nDry run: would write {written} dossiers (skipped {skipped} without id)")
    else:
        print(f"Wrote {written}, unchanged {unchanged}, skipped {skipped} (no id) -> {DOSSIERS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
