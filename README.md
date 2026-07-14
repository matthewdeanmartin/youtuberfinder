# YouTubers on Mastodon

A static directory of YouTube creators and channel feeds found through Mastodon profile evidence.

This website makes it easier to find YouTube creators on Mastodon and distinguish creator-run
profiles from automated channel feeds.

## Features

- **Topic categories**: Browse technology, gaming, education, music, art, news, culture, and hobbies.
- **Bulk Follow lists**: Copy-paste handle lists or download a CSV to upload directly to Mastodon.
- **Honest account labels**: Native profiles are separated from RSS feeds, bots, and bridges.
- **Comprehensive Quality Gates**: Built-in HTML validation, link checking, browser compatibility audit, and accessibility (WCAG2AA) verification.

## Architecture

This site is built with:
- **[Pelican](https://getpelican.com/)**: Python static site generator.
- **Mastodon-first discovery**: profile searches are collected into a local SQLite evidence store.
- **Curated JSON directory**: `data/youtubers.json` contains only publishable creators.
- **Vanilla CSS**: Premium dark/light themes without utility classes.

## Development Tasks

The project uses `just` (or `make`) for task running:

```bash
# Install and synchronize Python and Node dependencies
just sync
npm install

# Generate content files from data/youtubers.json
just generate-pages

# Generate stub profiles for unreviewed creators
just stubs

# Build the Pelican HTML site
just html

# Build the site and serve with auto-reload
just devserver

# Run all quality checks (HTML, CSS compatibility, Links, a11y)
just quality
```

## Mastodon-first discovery pipeline

The discovery direction is intentionally Mastodon → YouTube. The number of YouTube channels is
effectively unbounded, while the set of Mastodon profiles that identify themselves as YouTube
creators is tractable.

Copy `.env.example` to `.env` and supply a Mastodon application access token. `.env` and the local
SQLite database are gitignored.

```bash
# Search profile metadata across broad YouTube topics. Results are upserted,
# so this can be run repeatedly with more queries or pages.
just discover-mastodon
just discover-mastodon --query "retro computing youtube" --pages 20

# Inspect profiles whose bio or profile fields contain a direct YouTube channel URL.
just mastodon-candidates --limit 200

# Categorize every evidence-backed profile, then publish the catalog.
just categorize-mastodon
just publish-candidates
just build
```

### Seeding from Wikidata

Wikidata records both a YouTube channel ID (property `P2397`) and a Mastodon
address (`P4033`) for many notable creators and organisations. That makes it a
*YouTube-first* seed source: instead of guessing topical search terms, we pull
accounts already cross-referenced to a channel, then run each Mastodon handle
through the same evidence store and publish gates.

```bash
# Fetch Wikidata creators (cached to .cache/), resolve each Mastodon handle,
# and store it with the Wikidata channel as fallback evidence.
just seed-wikidata
just seed-wikidata --refresh            # re-query Wikidata instead of using the cache
just seed-wikidata --max-items 200      # cap how many items to process
```

The Wikidata YouTube channel is only used as fallback evidence — a channel link
found in the profile itself always wins. Non-English and inactive accounts (e.g.
the many German institutional accounts Wikidata surfaces) are pruned by the
existing publish gates, so no manual filtering is required.

Candidates are stored in `data/mastodon_candidates.sqlite`, including the raw Mastodon account,
the query that found it, and the exact bio/profile-field evidence for each YouTube channel link.
A profile mentioning YouTube without linking a channel does not qualify. Category, confidence,
matched terms, and account type are stored for review. Native accounts are included in follow
packs; automated channel feeds remain discoverable in the directory but are clearly labeled.

Automatic categories are intentionally reviewable. Add durable human corrections to
`data/category_overrides.json`, keyed by the full `user@server` Mastodon address; publishing marks
those classifications as `curated`.

## Contributing

Suggestions are welcome! To add a creator:
1. Ensure the creator has a YouTube channel and a working Mastodon profile.
2. Add them to `data/youtubers.json`.
3. Run `just check-mastodon` and `just build`.
