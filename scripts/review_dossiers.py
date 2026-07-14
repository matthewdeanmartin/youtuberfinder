"""Review every dossier with a Gemma-class model via OpenRouter.

Reads the rubric (``spec/rubric.md``) as the system prompt and each
``dossiers/<id>.md`` as the user prompt, then writes one verdict per creator to
``data/reviews/<id>.json``. It does **not** touch ``data/youtubers.json`` —
applying reviews back is a separate, human-gated step.

Safety properties (this runs on 700+ paid calls):
  • Resumable    — skips creators that already have a clean review (use --force).
  • Idempotent   — each verdict written immediately after its call.
  • Guarded      — --limit / --max-calls cap spend; --dry-run makes ZERO calls.
  • Validated    — malformed replies are stored as errors, retried next run.

Usage::

    # Free preview — prints prompts + token estimate, no API calls, no key:
    uv run python scripts/review_dossiers.py --dry-run --limit 3

    # Real run (needs OPENROUTER_API_KEY in env or .env):
    uv run python scripts/review_dossiers.py --limit 5
    uv run python scripts/review_dossiers.py            # the whole set
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

from pipeline import dossier as dossier_mod
from pipeline import gemma_review

ROOT = Path(__file__).parent.parent
DOSSIERS_DIR = ROOT / "dossiers"
REVIEWS_DIR = ROOT / "data" / "reviews"
RUBRIC_PATH = ROOT / "spec" / "rubric.md"
ENV_PATH = ROOT / ".env"


def load_env(path: Path = ENV_PATH) -> None:
    """Minimal ``.env`` loader (shared shape with fetch_youtube_stats.py)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        import os

        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _estimate_tokens(text: str) -> int:
    """Very rough token estimate (~4 chars/token) for the dry-run cost preview."""
    return max(1, len(text) // 4)


def _existing_review(path: Path) -> dict | None:
    """Return a previously written review dict, or None if absent/unreadable."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_review(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=gemma_review.DEFAULT_MODEL, help="OpenRouter model id")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N dossiers")
    parser.add_argument("--max-calls", type=int, default=0, help="Hard cap on API calls this run (cost guard)")
    parser.add_argument("--force", action="store_true", help="Re-review even creators that already have a clean review")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts + token estimate; make NO API calls")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to wait between calls (politeness)")
    parser.add_argument("--retries", type=int, default=2, help="Transient-failure retries per dossier")
    args = parser.parse_args()

    if not RUBRIC_PATH.exists():
        print(f"Rubric not found: {RUBRIC_PATH}", file=sys.stderr)
        return 2
    rubric = RUBRIC_PATH.read_text(encoding="utf-8")

    dossiers = sorted(DOSSIERS_DIR.glob("*.md")) if DOSSIERS_DIR.exists() else []
    if not dossiers:
        print(f"No dossiers in {DOSSIERS_DIR}. Run scripts/build_dossiers.py first.", file=sys.stderr)
        return 2
    if args.limit:
        dossiers = dossiers[: args.limit]
    print(f"Found {len(dossiers)} dossiers (model={args.model}, dry_run={args.dry_run})")

    api_key = None
    if not args.dry_run:
        import os

        load_env()
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            print("OPENROUTER_API_KEY is not set (checked environment and .env)", file=sys.stderr)
            return 2

    session = None if args.dry_run else requests.Session()
    today = _dt.date.today().isoformat()

    calls = reviewed = skipped = errors = 0
    est_prompt_tokens = 0

    for path in dossiers:
        text = path.read_text(encoding="utf-8")
        cid = dossier_mod.parse_dossier_id(text) or path.stem
        review_path = REVIEWS_DIR / f"{cid}.json"

        prior = _existing_review(review_path)
        if prior and not prior.get("error") and not args.force:
            skipped += 1
            continue

        if args.dry_run:
            messages = gemma_review.build_messages(rubric, text)
            tokens = sum(_estimate_tokens(m["content"]) for m in messages)
            est_prompt_tokens += tokens
            if calls < 2:  # show only the first couple in full
                print(f"\n=== {cid} (~{tokens} prompt tokens) ===")
                print("[system] rubric ({} chars)".format(len(rubric)))
                print("[user]\n" + text)
            calls += 1
            continue

        if args.max_calls and calls >= args.max_calls:
            print(f"Reached --max-calls={args.max_calls}; stopping.")
            break

        record = {"id": cid, "model": args.model, "reviewed_at": today}
        try:
            result = gemma_review.review_one(
                rubric, text, api_key, model=args.model, retries=args.retries, session=session
            )
            record.update(result.to_dict())
            record["error"] = None
            reviewed += 1
        except gemma_review.ReviewValidationError as exc:
            record["error"] = f"validation: {exc}"
            errors += 1
        except requests.RequestException as exc:
            record["error"] = f"http: {exc}"
            errors += 1
        calls += 1
        _write_review(review_path, record)
        if args.sleep:
            time.sleep(args.sleep)

    if args.dry_run:
        print(
            f"\nDry run complete: {calls} dossiers would be reviewed, "
            f"{skipped} already done. Estimated prompt tokens: ~{est_prompt_tokens:,} "
            "(completion tokens extra). No API calls were made."
        )
    else:
        print(f"\nDone: {reviewed} reviewed, {errors} errors, {skipped} skipped, {calls} API calls. -> {REVIEWS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
