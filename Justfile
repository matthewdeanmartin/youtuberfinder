# YouTubers on Mastodon — task runner
# Run `just` to see available recipes.

set dotenv-load := true
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

# ── Dependency management ──────────────────────────────────────────────────────

# Install / sync Python dependencies
sync:
    uv sync

# ── Page generation ────────────────────────────────────────────────────────────

# Regenerate all Pelican content pages from data/youtubers.json
generate-pages:
    uv run python generate_pages.py

# Preview page generation without writing
generate-pages-dry-run:
    uv run python generate_pages.py --dry-run

# Search Mastodon profiles first and persist all candidates/evidence in SQLite.
discover-mastodon *args:
    uv run python -m pipeline.discover_mastodon collect {{args}}

# Import the current published directory into the candidate database.
seed-mastodon:
    uv run python -m pipeline.discover_mastodon seed

# Look up curated well-known creators by address (finds non-topical handles).
seed-known:
    uv run python -m pipeline.discover_mastodon seed-known

# Seed from Wikidata: items with both a YouTube channel (P2397) and Mastodon (P4033).
seed-wikidata *args:
    uv run python -m pipeline.discover_mastodon seed-wikidata {{args}}

# Preview removal of entries without Mastodon-hosted YouTube channel evidence.
audit-creators:
    uv run python -m pipeline.discover_mastodon audit

# Apply the strict Mastodon + YouTube evidence rule to data/youtubers.json.
prune-creators:
    uv run python -m pipeline.discover_mastodon audit --write

# Review discovered profiles that have direct YouTube channel links.
mastodon-candidates *args:
    uv run python -m pipeline.discover_mastodon report {{args}}

# Categorize all YouTube-linked profiles and store reviewable evidence in SQLite.
categorize-mastodon:
    uv run python -m pipeline.discover_mastodon classify

# Publish the categorized candidate catalog to data/youtubers.json.
publish-candidates:
    uv run python -m pipeline.publish_candidates

# Generate stub articles for all unreviewed YouTubers
stubs:
    uv run python generate_review_stubs.py

# Overwrite all existing stubs (use with care — destroys hand-written prose)
stubs-force:
    uv run python generate_review_stubs.py --overwrite

# ── Site build ─────────────────────────────────────────────────────────────────

# Build the Pelican site
html:
    uv run pelican content -o output -s pelicanconf.py

# Copy hand-crafted static pages into output/ after Pelican runs.
# HTML files have {{SITEURL}} placeholders substituted with the real base URL
# so the page works under subdirectories (e.g. /youtuberfinder/ on GitHub Pages).
# Usage: just copy-static "" (dev) or just copy-static "/youtuberfinder" (prod)
copy-static siteurl="":
    uv run python scripts/copy_static.py "{{siteurl}}"

# Full build: regenerate pages into a clean output directory.
build: generate-pages
    just clean
    just html
    just copy-static ""

# Remove generated output
clean:
    uv run python -c "import shutil, pathlib; shutil.rmtree('output', ignore_errors=True)"

# Serve with live reload (Ctrl-C to stop)
serve:
    uv run pelican --listen content -o output -s pelicanconf.py

# Serve and auto-regenerate on content changes
devserver:
    uv run pelican --listen --autoreload content -o output -s pelicanconf.py

# Generate production HTML (publishconf uses DELETE_OUTPUT_DIRECTORY=True)
publish: generate-pages
    uv run pelican content -o output -s publishconf.py
    just copy-static "/youtuberfinder"

# ── Quality gates ─────────────────────────────────────────────────────────────

# Python-only deterministic gates: generated artifact lint + internal links
quality-python: html
    just copy-static ""
    uv run python -m unittest discover -s tests
    uv run python scripts/check_pelican_artifacts.py --site-dir output
    uv run python scripts/check_links.py --site-dir output --internal-only

# Cached external link audit
quality-links: html
    just copy-static ""
    uv run python scripts/check_mastodon_links.py
    uv run python scripts/check_links.py --site-dir output

# Verify source Mastodon accounts through each server's API
check-mastodon:
    uv run python scripts/check_mastodon_links.py

# Node-only gates: HTML validation, CSS browser support, accessibility
quality-node: html copy-static
    npm run quality

# Full quality pass
quality: build quality-python quality-node
