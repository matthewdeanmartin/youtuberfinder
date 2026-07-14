# Inclusion Rubric — Quality Gate for Channels & Mastodon Accounts

> **Purpose** — Decide whether a candidate (a YouTube channel paired with a
> Mastodon account) is good enough to list in the directory. This rubric is
> written to be executed by a **Gemma-class LLM** (small, local, ~2–9B). It
> trades nuance for determinism: every criterion is concrete, the scoring is
> additive, and the output is a fixed JSON shape. When a human and this rubric
> disagree, the human wins.

This is an *editorial* quality gate. It runs **after** the mechanical gates that
the pipeline already enforces and that the model should **not** re-judge:

- the Mastodon profile links directly to the YouTube channel (evidence rule),
- the account is **active** (posted on Mastodon within the last year),
- the account is **not suspended**,
- the YouTube channel **resolves** (a `subscriber_count` was fetched).

> **Note on missing stats.** A candidate with **no `subscriber_count`**
> (deleted/suspended/unresolvable channel) is **not** auto-excluded by the app
> today — it simply scores 0 on the popularity sort and renders last. This
> rubric treats a missing/zero subscriber count as a **signal**, not an
> automatic reject (criterion C below), so a genuinely good small or new channel
> is not dropped on a transient fetch failure.

---

## How to score

Award points for each criterion independently, then sum. A candidate is
**INCLUDE** only if it clears the threshold **and** trips no hard-fail.

- **Total possible: 10 points.**
- **Threshold: include if `score >= 6` AND no hard-fail is triggered.**
- A **hard-fail** forces `EXCLUDE` regardless of score.

### Hard-fails (any one → EXCLUDE)

| Code | Condition |
|------|-----------|
| `H1` | The content is spam, scam, engagement-farming, or pure affiliate/drop-ship promotion with no original content. |
| `H2` | Hate speech, harassment, or content targeting a protected group; or sexual content involving minors. |
| `H3` | The Mastodon account is a pure repost/RSS bot **misrepresenting itself as a person** (genuine, labeled feeds are fine and belong on the Bots page, not excluded). |
| `H4` | The YouTube channel and the Mastodon account clearly belong to **different, unrelated** entities (mismatched identity). |
| `H5` | Deceptive impersonation of another creator, brand, or public figure. |

### Scored criteria (0–10)

| Code | Criterion | Points |
|------|-----------|--------|
| **A — Identity match** | The Mastodon display name / handle / bio plausibly refers to the same creator as the YouTube channel (same name, brand, or topic). | 0–2 |
| **B — Content substance** | The channel publishes original, on-topic content (tutorials, reviews, essays, music, news, etc.) rather than reuploads, clip farms, or low-effort compilations. | 0–2 |
| **C — Reach & traction** | Evidence the channel has a real audience. Use `subscriber_count` when present: ≥10k → 2; 1k–10k → 1; <1k or missing → 0. A missing count alone never excludes (see note above). | 0–2 |
| **D — Mastodon presence quality** | The Mastodon account has a filled-in bio, a recognizable avatar/name, and posts that read as a real person/brand (not empty, not link-only spam). | 0–2 |
| **E — Coherence & safety** | Content is coherent, in a supported language, and free of borderline-but-not-hard-fail issues (heavy clickbait, mild misinformation, excessive self-promo). Deduct toward 0 as these appear. | 0–2 |

> **Edge guidance for the model**
> - **Small but genuine** creators are welcome. Do not exclude solely for low
>   subscriber count — that is at most a C=0, recoverable by A/B/D/E.
> - **Non-English** is fine; the directory is multilingual. Do not penalize a
>   language you cannot read *if* identity (A) and presence (D) are clear.
> - **Uncertainty** → prefer the lower score, and set `confidence` accordingly.
>   Borderline candidates should be sent to human review, not silently included.

---

## Decision

```
if any hard-fail:            decision = "exclude"
elif score >= 6:             decision = "include"
elif score >= 4:             decision = "review"   # send to a human
else:                        decision = "exclude"
```

`review` exists so the model never has to force a coin-flip into include/exclude.

---

## Required output (strict JSON, nothing else)

The model MUST return exactly one JSON object and no surrounding prose:

```json
{
  "decision": "include | review | exclude",
  "score": 0,
  "hard_fail": null,
  "criteria": { "A": 0, "B": 0, "C": 0, "D": 0, "E": 0 },
  "confidence": "high | medium | low",
  "language": "en",
  "category": "technology",
  "subcategory": "tech news",
  "hashtags": ["#technology", "#tech"],
  "reason": "one sentence, <= 200 chars, citing the deciding criteria"
}
```

Rules for the output:
- `hard_fail` is `null` or one of `H1`–`H5`.
- `score` must equal the sum of `criteria` values.
- If `hard_fail` is set, `decision` must be `"exclude"`.
- `reason` is a single short sentence; no markdown, no line breaks.

### Enrichment fields (only when `decision != "exclude"`)

When you do **not** exclude the creator, also classify them. When you **do**
exclude, set `language` to your best guess (or `null`), and set `category` and
`subcategory` to `null` and `hashtags` to `[]` — we don't categorize what we
won't list.

- `language` — the creator's primary **content** language as a BCP-47 base tag
  (e.g. `en`, `de`, `pt-br`, `ja`). Judge from the name/bio/description, not the
  instance domain.
- `category` — exactly one slug from the project taxonomy:

  | slug | covers |
  |------|--------|
  | `technology` | computing, software, gadgets, IT, tech news |
  | `gaming` | games, let's-plays, VTubers, esports |
  | `science-education` | science, maths, engineering, teaching, explainers |
  | `music` | musicians, music production, music commentary |
  | `art-making` | art, design, crafts, makers, DIY, woodworking |
  | `news-society` | news, politics, society, activism, journalism |
  | `culture-entertainment` | film, TV, comedy, pop culture, podcasts |
  | `lifestyle-hobbies` | travel, food, fitness, vlogs, hobbies |
  | `other` | none of the above fits |

- `subcategory` — a short free-text label in your own words (≤ 40 chars), e.g.
  `"home automation"`, `"indie game dev"`, `"classical piano"`.
- `hashtags` — 1–8 lowercase Fediverse-style tags, each `#word` (letters,
  digits, `-`), most-relevant first, e.g. `["#linux", "#selfhosting"]`.

---

## Input the model receives

Provide the model only these fields (keep the prompt small for a Gemma-class
model):

```
name:               <creator name>
youtube_url:        <channel URL>
subscriber_count:   <int or "unknown">
video_count:        <int or "unknown">
mastodon_acct:      <user@instance>
mastodon_bio:       <plain-text bio, truncated to ~500 chars>
description:        <stored channel/blurb description>
language:           <bcp47 or "unknown">
```

Do not feed the model fields it should not re-judge (e.g. `last_status_at`,
`suspended`) — those gates run before this rubric.

---

## Few-shot examples

**Example 1 — clear include**

Input:
```
name: Undecided with Matt Ferrell
youtube_url: https://www.youtube.com/@undecidedtechnology
subscriber_count: 1240000
video_count: 410
mastodon_acct: undecided@mastodon.social
mastodon_bio: Exploring sustainable + future tech. Host of Undecided & Still TBD.
description: Clean-energy and future-tech explainers.
language: en
```
Output:
```json
{"decision":"include","score":10,"hard_fail":null,"criteria":{"A":2,"B":2,"C":2,"D":2,"E":2},"confidence":"high","language":"en","category":"technology","subcategory":"sustainable tech","hashtags":["#technology","#cleanenergy","#futuretech"],"reason":"Identity matches, original tech content, 1.2M subs, strong Mastodon bio."}
```

**Example 2 — small but genuine, included**

Input:
```
name: Maker of Things
youtube_url: https://www.youtube.com/channel/UCsmallchannel00000000
subscriber_count: 740
video_count: 36
mastodon_acct: maker_of_things@makertube.net
mastodon_bio: I build weird little machines and film the process.
description: DIY electronics and woodworking builds.
language: en
```
Output:
```json
{"decision":"include","score":7,"hard_fail":null,"criteria":{"A":2,"B":2,"C":0,"D":2,"E":1},"confidence":"medium","language":"en","category":"art-making","subcategory":"diy electronics","hashtags":["#diy","#electronics","#maker"],"reason":"Genuine original maker content and matching profile; low subs (C=0) but clears threshold."}
```

**Example 3 — identity mismatch, hard-fail**

Input:
```
name: Crypto Signals Pro
youtube_url: https://www.youtube.com/channel/UCcryptoxxxxxxxxxxxxxxx
subscriber_count: 5200
video_count: 12
mastodon_acct: news_bot_9000@spam.example
mastodon_bio: 🚀🚀 Join my paid signals group! Link in bio. Guaranteed 10x.
description: Crypto trading signals.
language: en
```
Output:
```json
{"decision":"exclude","score":0,"hard_fail":"H1","criteria":{"A":0,"B":0,"C":0,"D":0,"E":0},"confidence":"high","language":"en","category":null,"subcategory":null,"hashtags":[],"reason":"Paid-signals engagement farming with no original content (H1)."}
```

**Example 4 — borderline, sent to review**

Input:
```
name: Daily Clips Channel
youtube_url: https://www.youtube.com/channel/UCclipsxxxxxxxxxxxxxxxx
subscriber_count: 22000
video_count: 900
mastodon_acct: dailyclips@mastodon.social
mastodon_bio:
description: Reuploaded highlights from various streamers.
language: en
```
Output:
```json
{"decision":"review","score":4,"hard_fail":null,"criteria":{"A":2,"B":0,"C":2,"D":0,"E":0},"confidence":"low","language":"en","category":"gaming","subcategory":"stream clips","hashtags":["#gaming","#streaming"],"reason":"Reupload/clip channel with empty Mastodon bio; identity matches but substance unclear — needs human review."}
```

---

## Operational notes

- **Determinism:** run the model at temperature 0. The rubric is additive so the
  same input yields the same score.
- **Batching:** score one candidate per call; do not ask the model to rank a
  list (small models drift on long inputs).
- **Auditability:** persist the full JSON output (not just the decision) next to
  the candidate so a human can spot-check `criteria` breakdowns.
- **Human override:** any human decision supersedes the model and should be
  recorded so it is never re-litigated by a later run.
```
