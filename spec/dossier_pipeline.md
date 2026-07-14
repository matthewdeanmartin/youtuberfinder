# Dossier + Gemma Review Pipeline — Plan

> **Goal** — For every creator in `data/youtubers.json`, produce a compact
> markdown **dossier** that a Gemma-class model (via OpenRouter) reads to decide,
> per [`spec/rubric.md`](rubric.md), whether the channel/account is good enough
> to include — and, when it is, to return the **correct language**, a
> **category**, a **subcategory**, and a list of **hashtags**.
>
> This pipeline is built to be **solid before it is run on 700+ paid API
> calls**: every stage is offline-testable, resumable, idempotent, and never
> mutates `youtubers.json` directly.

## Why dossiers (vs. inlining JSON in the prompt)

- **Human-auditable.** A reviewer can open `dossiers/<id>.md` and read exactly
  what the model saw. Same artifact for model and human.
- **Stable matching.** Each dossier carries the creator `id` in YAML front
  matter and is named `dossiers/<id>.md`, so a model result maps back to the
  source record with zero ambiguity.
- **Cheap diffing.** Re-running `build_dossiers` only rewrites changed files, so
  you can see what actually changed before paying to re-review.
- **Prompt hygiene.** The dossier is the single source of the prompt body; the
  system prompt (the rubric) is separate and versioned.

## Data flow

```
data/youtubers.json
   │  scripts/build_dossiers.py      (offline, free)
   ▼
dossiers/<id>.md                     ← one per creator, id in front matter
   │  scripts/review_dossiers.py     (OpenRouter, $$, resumable)
   ▼
data/reviews/<id>.json               ← one verdict per creator
   │  (future) scripts/apply_reviews.py
   ▼
data/youtubers.json                  ← merged, human-gated
```

The last arrow is **not** part of this change. Reviews land in
`data/reviews/`; applying them back into `youtubers.json` is a separate,
human-reviewed step so a bad model run can never silently corrupt the directory.

## Components

### 1. `pipeline/dossier.py`

Pure functions, no I/O, no network — trivially unit-testable.

- `dossier_markdown(creator: dict) -> str` — renders the dossier. Front matter:
  `id`, `name`, `mastodon_acct`, plus a `schema_version`. Body holds exactly the
  rubric input fields (name, youtube_url, subscriber/video counts, mastodon
  acct, **mastodon bio truncated to ~500 chars**, description, current
  language guess) and nothing the rubric says to withhold (`last_status_at`,
  `suspended`).
- `dossier_filename(creator: dict) -> str` — `"<id>.md"`.
- `parse_dossier_id(text: str) -> str | None` — reads the `id` back out of a
  dossier (used to match results).

### 2. `scripts/build_dossiers.py`

- Loads `youtubers.json`, writes `dossiers/<id>.md` for each creator with an
  `id`. Idempotent: only writes when content changed. `--dry-run`, `--limit`.
- No network, no key required. Safe to run anytime.

### 3. `pipeline/gemma_review.py`

The OpenRouter client + **strict response validation**. This is where most of
the "make it solid" effort goes, because the calls cost money.

- `ReviewResult` dataclass — the validated, typed verdict (rubric fields +
  `language`, `category`, `subcategory`, `hashtags`).
- `build_messages(rubric: str, dossier: str)` — system = rubric, user = dossier.
- `review_one(client, model, rubric, dossier) -> ReviewResult` — one call,
  parse, validate.
- `validate_payload(obj) -> ReviewResult` — enforces the contract (see below);
  raises `ReviewValidationError` on any violation so a malformed model reply is
  never written as if it were valid.

**Robustness measures (pre-run safety):**

- **JSON extraction** tolerant of code fences / leading prose (small models
  wrap output); we extract the first balanced `{...}` block.
- **Schema enforcement**: `decision ∈ {include,review,exclude}`;
  `criteria` keys exactly `A–E`, each `0–2`; `score == sum(criteria)`;
  `hard_fail ∈ {null,H1..H5}`; if `hard_fail` set then `decision=="exclude"`;
  `category ∈` the project taxonomy; `language` a plausible BCP-47 base tag;
  `hashtags` a list of ≤8 `#tag` strings. Anything off → validation error,
  recorded as an `error` result, **not** a silent pass.
- **Retries** with backoff on transient HTTP/timeout/JSON errors only (not on
  validation errors — re-asking won't fix a confidently-wrong reply cheaply;
  configurable).
- **Deterministic**: `temperature=0`, one creator per call.
- **Cost guardrails**: `--limit`, `--max-calls`, and a `--dry-run` that prints
  the exact prompt + estimated token count and makes **zero** API calls.

### 4. `scripts/review_dossiers.py`

- Loads the rubric (`spec/rubric.md`) as the system prompt and each dossier as
  the user prompt.
- **Resumable**: skips any creator that already has a non-error
  `data/reviews/<id>.json` unless `--force`.
- Writes one JSON per creator immediately after each call, so an interrupt
  (or running out of credits) never loses completed work.
- Reads `OPENROUTER_API_KEY` from the environment / `.env` (loaded with the same
  tiny inline parser used by `fetch_youtube_stats.py`). The key need not exist
  yet; `--dry-run` runs the whole pipeline without it.
- Flags: `--model` (default `google/gemma-2-9b-it`), `--limit`, `--max-calls`,
  `--force`, `--dry-run`, `--sleep` (politeness delay).

## Result contract (`data/reviews/<id>.json`)

Superset of the rubric output plus the enrichment fields the user asked for:

```json
{
  "id": "ars-technica",
  "model": "google/gemma-2-9b-it",
  "reviewed_at": "2026-06-25",
  "decision": "include",
  "score": 10,
  "hard_fail": null,
  "criteria": { "A": 2, "B": 2, "C": 2, "D": 2, "E": 2 },
  "confidence": "high",
  "language": "en",
  "category": "technology",
  "subcategory": "tech news",
  "hashtags": ["#technology", "#tech", "#news"],
  "reason": "Identity matches, original tech content, strong presence.",
  "error": null
}
```

- `language`, `category`, `subcategory`, `hashtags` are populated **only when
  `decision != "exclude"`** (the rubric says don't categorize what we won't
  list). For excluded/errored creators they are `null` / `[]`.
- `category` must be one of the project taxonomy slugs:
  `technology, gaming, science-education, music, art-making, news-society,
  culture-entertainment, lifestyle-hobbies, other`.
- `subcategory` is a free-text short label (model's own words, ≤40 chars).
- `error` is `null` on success, else a short string (validation/HTTP). When
  `error` is set, the decision fields are best-effort/empty and the record is
  **not** treated as a finished review (it will be retried on the next run).

## Testing before the paid run

1. `uv run python scripts/build_dossiers.py` — inspect a handful of
   `dossiers/*.md` by eye.
2. `uv run python scripts/review_dossiers.py --dry-run --limit 3` — prints the
   exact messages and token estimate, makes no API calls.
3. Unit tests cover dossier rendering, JSON extraction from messy replies, and
   every validation branch — so the contract is proven without spending money.
4. Only then: set `OPENROUTER_API_KEY`, run with `--limit 5` to sanity-check
   real replies and cost, then the full set.

## Out of scope (intentionally)

- Applying reviews back into `youtubers.json` (separate human-gated step).
- Choosing the final Gemma model / OpenRouter routing tier (left configurable).
- Hashtag normalization beyond basic shape checks.
