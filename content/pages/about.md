Title: About
Date: 2026-06-20
Slug: about
sortorder: 3
Summary: About the YouTubers on Mastodon directory.

## Why this exists

Finding a YouTuber's post-Twitter home is surprisingly awkward. Mastodon is distributed across
many servers, usernames are not globally obvious, and channel feed bots can look like creator-run
accounts.

**YouTubers on Mastodon** starts from Mastodon profiles and looks for direct links to YouTube
channels. That provides auditable evidence connecting each profile to a channel.

## Inclusion and labeling

A profile qualifies when its Mastodon bio or profile fields contain a direct YouTube channel URL.
That evidence does not prove that every account is personally operated by the creator, so the site
also labels native accounts, RSS feeds, bots, and bridges separately.

Topic categories are inferred from profile names, bios, and profile fields. Each classification
stores its matched terms and confidence in the local discovery database so maintainers can review
and override imperfect automated guesses.

## Future scope

Threads and Bluesky handles may be added later. For now, the goal is a useful, honest Mastodon
directory with enough creators to browse and a clear distinction between conversation and feeds.

## Technical setup

The site is generated with Pelican. Discovery data and classification evidence live in a local,
gitignored SQLite database; the publishable catalog lives in `data/youtubers.json`.
