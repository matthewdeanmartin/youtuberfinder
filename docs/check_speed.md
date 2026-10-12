# Check speed and when to pay for it

Quality checks are only useful when people can afford to run them. This repository has nearly 800
generated creator pages, tens of thousands of links, hundreds of YouTube feeds, and browser-driven
accessibility checks. Treating every check as an edit-loop requirement would make small changes
needlessly slow and encourage people to skip validation entirely.

Use checks in layers. A later layer adds confidence; it does not redefine every earlier layer as
insufficient.

## Quick checks: every edit loop

Target: seconds, offline, deterministic, and safe to repeat.

```bash
uv run python -m unittest discover -s tests
uv run python -m compileall -q pipeline scripts generate_pages.py
uv run python generate_pages.py --dry-run --no-feeds
git diff --check
```

These checks catch most implementation mistakes: broken Python, policy regressions, page-generator
exceptions, and malformed patches. The dry-run deliberately avoids RSS and does not rewrite the
tracked generated pages.

Run the smallest relevant test module while actively editing, then run the complete unit suite
before handing work off. For example:

```bash
uv run python -m unittest tests.test_collections
```

Do not put remote Mastodon lookups, YouTube RSS refreshes, external link crawling, Chrome startup,
or a full site regeneration in this tier.

## Change checks: before pushing a meaningful site change

Target: roughly one or two minutes on a warm workstation. These checks build or inspect the full
static site but avoid deliberately expensive external audits.

```bash
just build
just quality-python
npm run quality:html
npm run quality:browser
```

Choose checks that match the surface changed:

- Pipeline-only code generally needs unit tests and compilation, plus a dry-run of its command.
- Templates, generated HTML, navigation, or CSS need the site build, HTML validation, internal
  link audit, and browser-support check.
- A focused UI change should get a focused accessibility check of the affected pages when the
  local Chrome runner is healthy.
- Documentation-only changes normally need quick checks, link checking only when links changed,
  and no browser crawl.

`just build` refreshes YouTube-backed page content and can rewrite many generated creator files.
Review the resulting diff and keep unrelated feed churn out of feature changes.

## Pre-release checks: intentionally expensive

Target: several minutes or more. Run these in CI, before a release, or when changing the check
itself—not after every small edit.

```bash
just quality
just quality-links
```

This tier includes full generation, all deterministic gates, browser-driven accessibility, and
external link verification. Cost comes from the size of the generated site and from systems we do
not control:

- YouTube feed refreshes make hundreds of network requests.
- The internal link audit currently examines more than 40,000 links.
- Accessibility uses a real Chrome process and may approach its timeout on a slow or unhealthy
  browser installation.
- External links can be slow, rate-limited, or temporarily unavailable even when our code is fine.

An external outage should be reported separately from a deterministic code failure. Do not weaken
the quick suite to accommodate flaky networks; keep networks out of the quick suite.

## Collection synchronization is an operations job

The monthly Mastodon Collection reconciliation is neither a build check nor a normal pre-push
check. A complete dry-run resolves hundreds of federated accounts and then reads YouTube RSS for
the Mastodon-active subset:

```bash
just sync-collections
```

Use `--limit-creators` for a small development smoke test. It is intentionally incompatible with
`--apply`, because a partial catalog must never be used to remove live Collection members.

```bash
uv run python scripts/sync_mastodon_collections.py --limit-creators 5
```

Only the scheduled monthly job or an intentional operator run should use `--apply`. A live sync
must fail safe when Mastodon lookups fail and must preserve incumbents when YouTube activity cannot
be observed.

## Recommended policy

1. Keep the quick tier under ten seconds and deterministic.
2. Require quick checks for every change.
3. Select change checks based on the files and behavior touched.
4. Require the full pre-release tier once per release candidate, not once per commit.
5. Run external audits and live synchronization on schedules with clear failure reporting.
6. Record unusually slow checks and optimize or split them instead of normalizing long waits.

The goal is fast feedback during development and deep confidence at release time. Both matter;
they simply belong at different points in the workflow.
