# Tech YouTubers Directory — Road Map

> **Current state (v0.1 — June 2026)**  
> Static Pelican site, 17 creators in `data/youtubers.json`, PKCE-secured Mastodon follow-pack
> page, per-stack pages, bulk-follow CSV export, quality gates (HTML, a11y, link checker).

---

## Guiding goals

1. **Promote tech YouTubers** — be the authoritative index of creators at the intersection of
   YouTube and the Fediverse/Bluesky.
2. **Promote Mastodon** — lower the barrier for people who know YouTube creators but are new to
   federated social networks.
3. **Make following easy** — match the convenience of Bluesky starter packs, but for Mastodon and
   across many instances.

---

## Phase 1 — Data quality & pipeline (next priority)

The site is only as good as its data. Before growing the creator list, harden the pipeline so
updates stay accurate with minimal manual effort.

### 1.1 YouTube Data API integration

- **Script**: `pipeline/fetch_youtube.py`
- Pull live subscriber counts, channel description, upload-frequency signal, and thumbnail URL
  using the [YouTube Data API v3](https://developers.google.com/youtube/v3) (free quota: 10 000
  units/day, well within our needs).
- Store `youtube_channel_id` in `youtubers.json` so lookups are stable even if handle URLs change.
- Merge results non-destructively via the existing `pipeline.youtuber_store.merge()` function.
- **Justfile task**: `just refresh-youtube`
- Run as a **GitHub Actions cron** (weekly) and commit updated JSON if subscriber counts or
  descriptions changed.

### 1.2 Mastodon handle verification

- **Script**: `pipeline/verify_mastodon.py`
- For each creator with a `mastodon_url`, hit the instance's `/api/v1/accounts/lookup` endpoint
  (no auth required for public accounts) and confirm the account still exists and is active.
- Set a `mastodon_verified_at` timestamp and a `mastodon_active: true/false` flag.
- Creators that have gone silent (no posts in 6 months) get flagged `mastodon_stale: true` so
  the site can show a soft warning badge.
- Uses `requests-cache` (already in deps) to avoid hammering instances.

### 1.3 Bluesky handle verification  

- Mirror of the Mastodon verifier, using the AT Protocol `app.bsky.actor.getProfile` lexicon.
- Checks DID resolution to confirm handles haven't gone stale.

### 1.4 Canonical data schema & validation

- Add a **JSON Schema** at `spec/youtuber.schema.json` and a pre-commit / CI gate that validates
  `data/youtubers.json` on every PR.
- Required fields: `id`, `name`, `tech_stack`, `youtube_url`.
- Optional but validated when present: `mastodon_url` must be a valid `https://` Mastodon profile
  URL, `bluesky_url` must match `https://bsky.app/profile/...`.

### 1.5 Contributor-friendly add-creator script

- **Script**: `pipeline/add_creator.py --youtube-handle @SomePerson`
- Fetches YouTube metadata, prompts for Mastodon/Bluesky handle, runs verification, and appends
  to `youtubers.json`.
- Lowers the bar for contributors to a single command rather than hand-editing JSON.

---

## Phase 2 — New-to-Mastodon features

People arriving from YouTube land often have no idea what Mastodon is. Make this site their
on-ramp.

### 2.1 "What is Mastodon?" explainer page

- `/about-mastodon/` — a friendly, jargon-light explanation of:
  - Federated social (instances, the Fediverse).
  - Why it's different from Twitter/Bluesky.
  - How to pick an instance (link to `joinmastodon.org` instance picker).
  - What following a remote account means (federation, boost visibility).
- No patronising tone — written for someone who knows YouTube but is confused by the ActivityPub
  model.

### 2.2 Instance recommendation widget (client-side)

- On the `/mastodon-follow/` page, before the user types an instance, show a small widget:
  - "Don't have a Mastodon account yet?" → links to `joinmastodon.org`.
  - **Quick instance finder**: dropdown of popular general-purpose and tech-focused instances
    (mastodon.social, fosstodon.org, infosec.exchange, hachyderm.io, toot.cafe, sigmoid.social)
    with a one-click "Use this instance" button that fills in the field.
- Instance list stored as a small JSON file (`data/recommended_instances.json`) so it stays
  maintainable.

### 2.3 "Already on Mastodon? Here's how to find people" guide

- A Pelican page at `/mastodon-search-tips/` covering:
  - Why searching for `@user@other.instance` in your own instance's search works (with `resolve`).
  - The Mastodon CSV import flow (already documented in `/bulk-follow/`, deep-link from here).
  - The interactive follow tool (link to `/mastodon-follow/`).

### 2.4 Per-creator "Follow on Mastodon" button

- On every creator profile page, add a `Follow on Mastodon` button that:
  1. Checks `sessionStorage` for an existing token.
  2. If found: follows directly via API (single-account flow).
  3. If not: links to `/mastodon-follow/?highlight=<acct>` which pre-scrolls to that creator
     with the checkbox pre-selected and a "Connect & Follow" CTA.

### 2.5 Follow-pack sharing via URL

- Support `/mastodon-follow/?pack=starter` (query param) that loads a named subset of creators.
- Named packs defined in `data/follow_packs.json`:
  ```json
  {
    "starter":  ["geerlingguy@mastodon.social", "technotim@mastodon.social"],
    "linux":    ["thelinuxEXP@mastodon.social", "BrodieOnLinux@mstdn.social"],
    "security": ["tomlawrence@infosec.exchange", "davidbombal@infosec.exchange"]
  }
  ```
- Makes the page shareable as a Mastodon-equivalent of a Bluesky starter pack link.

---

## Phase 3 — Follow-pack UX improvements

### 3.1 Follow-status persistence

Currently the follow tool loses all resolved state on page refresh. Options:
- Cache resolved account IDs in `sessionStorage` keyed by `acct` so a page reload within the
  same tab doesn't need to re-resolve everything.
- Show a "following" badge on creator cards for accounts already followed (fetched from
  `/api/v1/accounts/relationships` on login).

### 3.2 Bulk follow progress indicator

- Replace the current log-only approach with a visible progress bar during "Follow All".
- Show a summary card at the end: "Followed 9 · Pending 1 (locked account) · Error 0".

### 3.3 Export your follow list

- Button: **"Download follows.csv"** — generates and downloads a Mastodon-importable CSV of the
  currently-checked creators without needing to authorize at all.
- This is the zero-auth path for cautious users who prefer the manual import route.

### 3.4 Rate-limit awareness

- Mastodon's API limits are per-instance and vary. Catch `429 Too Many Requests` responses and
  back off automatically with user-visible feedback ("Rate limited — waiting 30 s…").

---

## Phase 4 — Content & curation quality

### 4.1 Creator tier / activity badges

Based on YouTube API + Mastodon verification data, show automatic badges on creator cards:
- **Active** — posted on Mastodon in the last 30 days.
- **Occasional** — posted in the last 90 days.
- **Quiet** — no posts in 90+ days (still worth following, just a heads-up).
- **Growing** — subscriber growth > 10% in last 90 days (YouTube API).

### 4.2 Human-written review backlog

There are currently 12 unreviewed creators. The `generate_review_stubs.py` script already creates
stub articles. Priority order for writing full reviews:
1. Jeff Geerling (600K subs, hugely influential homelab/Pi community).
2. Techno Tim (400K, Kubernetes/self-hosting crowd).
3. Nick / The Linux Experiment (260K, FOSS desktop).
4. David Bombal (1.1M, networking/security).

### 4.3 Community submissions

- **GitHub Issue template**: "Suggest a creator" with fields for YouTube URL, Mastodon handle,
  and niche description.
- A CI workflow runs `pipeline/verify_mastodon.py` on the proposed handle and comments the result
  on the issue automatically.

### 4.4 "Hidden gem" section

Surface smaller channels (< 50K subscribers) with an active Mastodon presence that deserve more
visibility. Separate section on the homepage or a `/hidden-gems/` page.

---

## Phase 5 — YouTube API deeper integration

### 5.1 Automated discovery of new Mastodon accounts

- When a channel's YouTube "About" / links section or pinned post contains a Mastodon URL,
  flag it for review: `pipeline/scan_for_mastodon.py`.
- Cross-reference channels already in the JSON against their latest YouTube "About" page using
  the YouTube API `channels.list` endpoint (part `snippet,brandingSettings`).
- Queue newly found handles to the verification pipeline (see 1.2) and open a draft PR if they
  pass.

### 5.2 Upload frequency signal

- Store `upload_frequency_days` (rolling 90-day average from playlist items API).
- Displayed on creator cards: "Posts ~2x / week" helps users decide who to prioritise following.

### 5.3 Subscriber milestone notifications

- Optional GitHub Actions step that posts a Mastodon toot from a bot account
  when a tracked creator crosses a subscriber milestone (100K, 250K, 500K, 1M).

---

## Phase 6 — Bluesky parity

The site already exports Bluesky handle lists. Go further:

### 6.1 Bluesky AT Protocol follow tool

- Mirror of the Mastodon follow page, using the `app.bsky.graph.follow` lexicon via the
  AT Protocol HTTP API.
- Use app passwords initially (with a clear security disclaimer); revisit when AT Protocol
  OAuth 2.0 support lands upstream.

### 6.2 Bluesky starter pack generation

- The Bluesky API (`app.bsky.graph.starterpack`) allows programmatic creation of starter packs.
- A script `pipeline/create_bsky_starterpack.py` generates an official starter pack from the
  curated list and keeps it up to date as creators are added.

---

## Phase 7 — Infrastructure & ops

### 7.1 GitHub Actions pipeline

```
.github/workflows/
  refresh.yml      — weekly: fetch YouTube stats, verify handles, commit if changed
  pr-validate.yml  — on PR: JSON schema check, generate-pages dry-run, quality gates
  deploy.yml       — on push to main: build + deploy to GitHub Pages
```

### 7.2 Secrets management

- `YOUTUBE_API_KEY` → GitHub Actions secret (never committed).
- No Mastodon credentials needed server-side — all OAuth is client-side PKCE.
- Optional: a bot Mastodon app token for milestone posting (see 5.3), stored as a separate secret.

### 7.3 Caching layer

- `requests-cache` is already a dependency. Configure a SQLite cache at `.cache/requests.db`
  with a 24-hour TTL for YouTube and Mastodon API calls.
- The `.cache/` directory is `.gitignore`d and the CI pipeline warms it between runs using
  GitHub Actions cache restore.

### 7.4 `pelicanconf.py` — `SITEURL` for GitHub Pages

- Ensure `publishconf.py` sets `SITEURL` to the correct GitHub Pages URL so all internal links
  and the Mastodon OAuth `redirect_uri` work correctly in production.
- The `/mastodon-follow/` page already handles `location.origin` correctly for both `file://`
  (local dev) and `https://` (GitHub Pages) origins.

---

## Open questions / decisions needed

| # | Question | Notes / options |
|---|----------|-----------------|
| Q1 | Where does the YouTube API key live for local dev? | `.env` file (gitignored); `just` already has `set dotenv-load := true` |
| Q2 | Bot Mastodon account for milestone toots? | Register an account, or skip entirely and just update the site |
| Q3 | Community submissions: PR-only or a web form? | GitHub issue template (low friction) vs. a Pages Function form handler |
| Q4 | Should the follow-pack page remain a standalone HTML file? | Yes — keep it standalone and generate the `STARTER_ACCOUNTS` JS array from `youtubers.json` at build time via a `just generate-follow-pack` step |
| Q5 | Named follow packs (Phase 2.5) — who curates them? | Maintainer-curated only to start; open community submissions later |
| Q6 | Bluesky app password UX — acceptable for POC? | Yes with a prominent disclaimer; revisit when AT Protocol OAuth lands |

---

## Milestones

| Milestone | Key deliverables | Rough effort |
|-----------|-----------------|-------------|
| **v0.2 — Pipeline** | YouTube API fetch, Mastodon verify, JSON schema, add-creator script, GH Actions cron | ~2–3 days |
| **v0.3 — New-to-Mastodon** | Explainer page, instance picker widget, per-creator follow button, URL-based packs | ~1–2 days |
| **v0.4 — Follow UX** | Follow-status persistence, progress bar, CSV export, rate-limit handling | ~1 day |
| **v0.5 — Content quality** | Activity badges, 4 new reviews written, community issue template | ~2–3 days (writing) |
| **v0.6 — Bluesky parity** | Bluesky follow tool, starter pack script | ~1–2 days |
| **v1.0 — Launch** | All quality gates green, README complete, GitHub Pages deployed, 30+ verified creators | — |
