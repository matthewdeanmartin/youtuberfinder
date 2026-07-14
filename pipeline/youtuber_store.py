"""
Read/write helpers for data/youtubers.json.

Preserves hand-edited fields (reviewed, review_slug, description).
"""
import json
from pathlib import Path

YOUTUBERS_PATH = Path(__file__).parent.parent / "data" / "youtubers.json"

PROTECTED = {"reviewed", "review_slug", "description"}


def load() -> list[dict]:
    if not YOUTUBERS_PATH.exists():
        return []
    youtubers = json.loads(YOUTUBERS_PATH.read_text(encoding="utf-8"))
    errors = []
    for y in youtubers:
        label = y.get("id") or y.get("name") or "<unknown>"
        if not y.get("mastodon_url"):
            errors.append(f"{label}: mastodon_url is required")
        if not y.get("youtube_url"):
            errors.append(f"{label}: youtube_url is required")
    if errors:
        raise ValueError("Invalid YouTuber data:\n  - " + "\n  - ".join(errors))
    return youtubers


def save(youtubers: list[dict]) -> None:
    youtubers_sorted = sorted(youtubers, key=lambda y: (y.get("category", ""), y.get("name", "")))
    YOUTUBERS_PATH.write_text(
        json.dumps(youtubers_sorted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def merge(existing: list[dict], incoming: list[dict], force_fields: set[str] | None = None) -> tuple[list[dict], int, int]:
    """
    Merge incoming YouTubers into existing list.
    """
    force_fields = force_fields or set()
    index = {t.get("id"): i for i, t in enumerate(existing)}
    result = list(existing)
    added = updated = 0

    for inc in incoming:
        k = inc.get("id")
        if not k:
            continue
        if k not in index:
            result.append(inc)
            added += 1
        else:
            i = index[k]
            changed = False
            for field, val in inc.items():
                if field in PROTECTED:
                    continue
                if field in force_fields or result[i].get(field) is None:
                    if result[i].get(field) != val:
                        result[i][field] = val
                        changed = True
            if changed:
                updated += 1

    return result, added, updated
