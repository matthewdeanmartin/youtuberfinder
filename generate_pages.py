"""Generate the public directory pages from data/youtubers.json."""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import categorize, youtuber_store, youtube_feed

# Toggled off by --no-feeds (and during --dry-run) so page generation can run
# fully offline. Populated as creators are fetched so a creator appearing on
# multiple pages is only fetched once per build.
FETCH_FEEDS = True
_FEED_CACHE: dict[str, list] = {}

CONTENT_DIR = Path(__file__).parent / "content"
PAGES_DIR = CONTENT_DIR / "pages"
ARTICLES_DIR = CONTENT_DIR / "articles"
FOLLOW_TOOL_PATH = Path(__file__).parent / "static" / "mastodon-follow" / "index.html"

PAGES_DIR.mkdir(parents=True, exist_ok=True)
ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

CATEGORY_LABELS = categorize.CATEGORY_LABELS
CATEGORY_SORTORDER = categorize.CATEGORY_SORTORDER
ACCOUNT_TYPE_LABELS = {
    "native": "Mastodon",
    "rss-feed": "Automated feed",
    "channel-feed": "Automated feed",
    "bridge": "Bridge",
    "bot": "Bot",
}

# Account types that are unattended automation. They are collected on the
# dedicated bots page (grouped by topic) rather than cluttering the topic
# pages. Bridges are excluded because they are usually real people relayed
# via a fedibridge instance.
BOT_ACCOUNT_TYPES = {"rss-feed", "channel-feed", "bot"}

# Mean YouTube subscriber and Mastodon follower counts across all creators that
# have the respective metric. Populated once by compute_popularity_baselines()
# at the start of main() so the popularity score is computed against the whole
# directory, not just the creators on a single page. Defaults keep scoring
# defined (score 0) before baselines are computed, e.g. in unit tests.
_AVG_SUBSCRIBERS = 1.0
_AVG_FOLLOWERS = 1.0


def compute_popularity_baselines(youtubers: list[dict]) -> None:
    """Compute and store the mean subscriber/follower counts for scoring."""
    global _AVG_SUBSCRIBERS, _AVG_FOLLOWERS
    subs = [c["subscriber_count"] for c in youtubers if isinstance(c.get("subscriber_count"), int)]
    folls = [c["followers"] for c in youtubers if isinstance(c.get("followers"), int) and c["followers"] > 0]
    if subs:
        _AVG_SUBSCRIBERS = sum(subs) / len(subs)
    if folls:
        _AVG_FOLLOWERS = sum(folls) / len(folls)


def popularity_score(creator: dict) -> float:
    """Combined popularity score for default sorting.

    Implements ``(subs / avg_subs) * (followers / avg_followers)`` — a creator
    weighted both by YouTube reach and Mastodon reach, each normalised to the
    directory average so the two scales combine fairly. A creator missing either
    metric scores 0 and sorts to the bottom (we cannot rank it on this basis).
    """
    subs = creator.get("subscriber_count")
    folls = creator.get("followers")
    if not isinstance(subs, int) or not isinstance(folls, int) or folls <= 0:
        return 0.0
    return (subs / _AVG_SUBSCRIBERS) * (folls / _AVG_FOLLOWERS)


def _social_link(url: str | None) -> str:
    if not url:
        return "—"
    parsed = urlparse(url)
    username = parsed.path.strip("/").removeprefix("@")
    handle = f"@{username}@{parsed.netloc}"
    return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{html.escape(handle)}</a>'


def _mastodon_account(url: str) -> str:
    parsed = urlparse(url)
    username = parsed.path.strip("/").removeprefix("@")
    return f"{username}@{parsed.netloc}"


def _creator_page_url(creator: dict) -> str:
    """Pelican intrasite link to a creator's profile page.

    ``{filename}`` is resolved by Pelican's link processing (it scans href/src
    in raw HTML too), so the link works under any SITEURL — including the
    GitHub Pages subpath in production — without hardcoding a base.
    """
    cid = html.escape(creator["id"], quote=True)
    return f"{{filename}}creator/{cid}.md"


def nonempty_categories(youtubers: list[dict]) -> list[str]:
    """Categories whose page has at least one non-bot (interactive) account.

    Mirrors the visibility rule in generate_category_page: bot/feed accounts
    live on the Bots page, so a category with only bots renders an empty page
    and is hidden from the sidebar.
    """
    present = {
        creator.get("category", "other")
        for creator in youtubers
        if creator.get("account_type") not in BOT_ACCOUNT_TYPES
    }
    return [slug for slug in CATEGORY_SORTORDER if slug in present]


def sync_follow_tool(youtubers: list[dict]) -> None:
    text = FOLLOW_TOOL_PATH.read_text(encoding="utf-8")

    # Keep the static follow tool's hand-maintained sidebar in step with the
    # data-driven sidebar in base.html: only list non-empty category pages.
    topics = "\n".join(
        f'            <li><a href="{{{{SITEURL}}}}/{slug}/">{html.escape(CATEGORY_LABELS[slug])}</a></li>'
        for slug in nonempty_categories(youtubers)
    )
    topics_block = "<!-- TOPICS:START --><ul>\n" + topics + "\n          </ul><!-- TOPICS:END -->"
    text, topic_count = re.subn(
        r"<!-- TOPICS:START -->.*?<!-- TOPICS:END -->",
        topics_block,
        text,
        flags=re.DOTALL,
    )
    if topic_count != 1:
        raise ValueError(f"{FOLLOW_TOOL_PATH}: expected exactly one TOPICS sidebar block")

    rows = []
    for creator in youtubers:
        if creator.get("account_type") != "native":
            continue
        row = {
            "name": creator["name"],
            "acct": _mastodon_account(creator["mastodon_url"]),
            "niche": creator.get("description") or "",
        }
        rows.append(f"    {json.dumps(row, ensure_ascii=False)},")
    replacement = "/* DATA:START */\n  const STARTER_ACCOUNTS = [\n" + "\n".join(rows) + "\n  ];\n  /* DATA:END */"
    updated, count = re.subn(
        r"/\* DATA:START \*/.*?/\* DATA:END \*/",
        replacement,
        text,
        flags=re.DOTALL,
    )
    if count != 1:
        raise ValueError(f"{FOLLOW_TOOL_PATH}: expected exactly one generated data block")
    FOLLOW_TOOL_PATH.write_text(updated, encoding="utf-8")


def sync_reviews(youtubers: list[dict]) -> tuple[list[dict], int]:
    updated = 0
    for creator in youtubers:
        slug = creator.get("review_slug") or creator.get("id")
        if (ARTICLES_DIR / f"{slug}.md").exists() and not creator.get("reviewed"):
            creator["reviewed"] = True
            creator["review_slug"] = slug
            updated += 1
    return youtubers, updated


def generate_youtubers_page(youtubers: list[dict]) -> str:
    def category_sort(item: dict) -> int:
        try:
            return CATEGORY_SORTORDER.index(item.get("category", "other"))
        except ValueError:
            return 99

    sorted_creators = sorted(
        youtubers,
        key=lambda item: (
            item.get("account_type") != "native",
            category_sort(item),
            item.get("name", "").casefold(),
        ),
    )
    rows = []
    for creator in sorted_creators:
        name = html.escape(creator.get("name", ""))
        youtube = html.escape(creator.get("primary_url") or creator.get("youtube_url", ""), quote=True)
        category = CATEGORY_LABELS.get(creator.get("category", "other"), "Other")
        account_type = ACCOUNT_TYPE_LABELS.get(creator.get("account_type", "native"), "Other")
        followers = str(creator.get("followers") or "—")
        lang = html.escape(creator.get("language") or "en", quote=True)
        rows.append(
            f'        <tr data-lang="{lang}">'
            f'<td class="tools-table__name"><a href="{youtube}" target="_blank" rel="noopener noreferrer">{name}</a></td>'
            f"<td>{html.escape(category)}</td>"
            f"<td>{html.escape(account_type)}</td>"
            f"<td>{html.escape(followers)}</td>"
            f"<td>{_social_link(creator.get('mastodon_url'))}</td>"
            "</tr>"
        )

    filter_bar = (
        '<div class="lang-filter-bar">'
        '<p>Showing creators in your browser language.</p>'
        '<button id="lang-filter-btn" type="button" aria-pressed="false">'  # label set by JS
        "&#x1F30D; Show all languages"
        "</button>"
        "</div>"
        '<p id="lang-filter-empty" hidden>'
        "No creators match your browser language. "
        "Use the button above to show all languages."
        "</p>"
    )

    table = "\n".join(
        [
            filter_bar,
            '<table class="tools-table">',
            "    <thead>",
            "        <tr>",
            "            <th>YouTuber</th>",
            "            <th>Category</th>",
            "            <th>Account</th>",
            "            <th>Mastodon followers</th>",
            "            <th>Mastodon</th>",
            "        </tr>",
            "    </thead>",
            "    <tbody>",
            *rows,
            "    </tbody>",
            "</table>",
        ]
    )
    native_count = sum(item.get("account_type") == "native" for item in youtubers)
    feed_count = len(youtubers) - native_count
    native_only = [item for item in youtubers if item.get("account_type") == "native"]
    bulk_block = _bulk_follow_block(native_only, "all", "All YouTubers")
    return f"""Title: All YouTubers
Date: 2026-06-20
Slug: youtubers
sortorder: 2
Summary: YouTube creators and channel feeds discoverable on Mastodon.

## YouTubers on Mastodon

{len(youtubers)} evidence-backed profiles: **{native_count} native Mastodon accounts** and
**{feed_count} automated feeds or bridges**. Native accounts are listed first because those are
the profiles where interaction is most likely.

{table}

## Inclusion rule

- The Mastodon profile must contain a direct link to a YouTube channel.
- Automated channel feeds and bridges are labeled separately from native Mastodon accounts.

{bulk_block}{BULK_FOLLOW_SCRIPT if bulk_block else ""}
"""


def _lang_attr(creator: dict) -> str:
    """Return a data-lang HTML attribute string for the creator."""
    lang = html.escape(creator.get("language") or "en", quote=True)
    return f' data-lang="{lang}"'


# Mastodon serialises profile links across <span class="invisible"> elements,
# e.g. "https://www." + "example.com". Our plain-text extraction joins those
# spans with a space, leaving artifacts like "https://www. example.com" or
# "https:// example.com" in the stored description. Stitch that single space
# back so the URL is whole before we linkify. Only the space immediately after
# the scheme / "www." boundary is repaired — ordinary prose spaces are left
# alone.
_URL_SPLIT_RE = re.compile(r"(https?://(?:www\.)?)\s+(?=[^\s<>\"'])", re.IGNORECASE)

# Bare http(s) URLs in a creator blurb. Trailing punctuation that is usually
# sentence/parenthesis grammar rather than part of the link is excluded.
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]]")


def _linkify(text: str) -> str:
    """HTML-escape ``text`` and turn any bare http(s) URL into a link that opens
    in a new tab. Escaping happens first, so the surrounding text is always
    safe; the matched URL is then escaped again for the href attribute."""
    repaired = _URL_SPLIT_RE.sub(r"\1", text or "")
    escaped = html.escape(repaired)

    def repl(match: re.Match[str]) -> str:
        url = match.group(0)
        href = html.escape(url, quote=True)
        return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{url}</a>'

    # Run against the already-escaped text. URLs contain no characters that
    # html.escape rewrites except '&', which is rare in URLs and harmless here
    # because the regex stops at whitespace/quotes; an escaped '&amp;' simply
    # ends the match early, which is acceptable for display.
    return _URL_IN_TEXT_RE.sub(repl, escaped)


def creator_videos(creator: dict, limit: int = 5) -> list:
    """Fetch (and memoize) recent uploads for a creator's YouTube channel.

    Returns [] when feeds are disabled or the feed can't be fetched, so callers
    never have to special-case failure.
    """
    if not FETCH_FEEDS:
        return []
    url = creator.get("primary_url") or creator.get("youtube_url")
    if not url:
        return []
    if url not in _FEED_CACHE:
        _FEED_CACHE[url] = youtube_feed.recent_videos(url, limit=limit)
    return _FEED_CACHE[url]


def _lite_embed_html(video) -> str:
    """Render one video as a lite-embed card: a thumbnail with a play button
    that only loads the heavy YouTube iframe on click (wired by
    creator-profile.js). Falls back to a plain thumbnail link when the video id
    can't be determined, so a card always renders something useful."""
    title = html.escape(video.title)
    url = html.escape(video.url, quote=True)
    date = html.escape(video.published)
    vid = video.video_id
    date_html = f'<time datetime="{date}">{date}</time>' if date else ""

    if not vid:
        return (
            '<li class="video-card video-card--link">'
            f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
            f"{date_html}</li>"
        )

    vid_attr = html.escape(vid, quote=True)
    # mqdefault is light (320×180) and exists for every video, unlike maxres.
    thumb = f"https://i.ytimg.com/vi/{vid_attr}/mqdefault.jpg"
    return (
        '<li class="video-card">'
        f'<button type="button" class="video-card__play" '
        f'data-video-id="{vid_attr}" data-video-title="{title}" '
        f'aria-label="Play: {title}">'
        f'<img class="video-card__thumb" src="{thumb}" alt="" loading="lazy" '
        f'width="320" height="180" />'
        '<span class="video-card__badge" aria-hidden="true">▶</span>'
        "</button>"
        '<div class="video-card__meta">'
        f'<a class="video-card__title" href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
        f"{date_html}"
        "</div>"
        "</li>"
    )


def _video_cards_html(videos: list) -> str:
    """Render recent uploads as a grid of lite-embed cards (creator page)."""
    if not videos:
        return ""
    cards = "".join(_lite_embed_html(v) for v in videos)
    return (
        '<section class="video-cards">'
        f'<h2>Recent uploads ({len(videos)})</h2>'
        f'<ul class="video-cards__grid">{cards}</ul>'
        "</section>"
    )


def _recent_videos_html(videos: list) -> str:
    """Render a creator's recent uploads as an always-visible list.

    ``videos`` is a list of pipeline.youtube_feed.Video. Returns "" when empty
    so creators whose feed could not be fetched simply show no widget.
    """
    if not videos:
        return ""
    items = []
    for video in videos:
        title = html.escape(video.title)
        url = html.escape(video.url, quote=True)
        date = html.escape(video.published)
        date_html = f'<time datetime="{date}">{date}</time> · ' if date else ""
        link = (
            f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
            if url
            else title
        )
        items.append(f"<li>{date_html}{link}</li>")
    return (
        '<div class="recent-videos">'
        f'<p class="recent-videos__title">Recent uploads ({len(videos)})</p>'
        "<ul>" + "".join(items) + "</ul>"
        "</div>"
    )


def _creator_li(creator: dict, mastodon_label: str, recent_videos: list | None = None) -> str:
    """Render one directory entry as a self-contained HTML list item.

    We emit real HTML rather than Markdown because these `<li>` elements live
    inside a raw `<ul>` block; Pelican's Markdown processor does not descend
    into block-level raw HTML, so `**[name](url)**` would render literally.
    """
    lang = html.escape(creator.get("language") or "en", quote=True)
    name = html.escape(creator["name"])
    primary_url = html.escape(creator.get("primary_url") or creator["youtube_url"], quote=True)
    mastodon_url = html.escape(creator["mastodon_url"], quote=True)
    page_url = _creator_page_url(creator)
    # Blurbs sometimes contain a bare URL (e.g. a personal site); make it a
    # real, new-tab link instead of plain text.
    description = _linkify(creator.get("description") or "")
    videos_html = _recent_videos_html(recent_videos or [])

    # Inline one-click Follow for native accounts, on its own line *after* the
    # blurb. The button is wired by the shared follow-core script (loaded
    # site-wide) using data-mastodon-acct.
    follow_html = ""
    if creator.get("account_type") == "native":
        acct = html.escape(_mastodon_account(creator["mastodon_url"]), quote=True)
        follow_html = (
            '<p class="creator-follow-line">'
            f'<button type="button" class="creator-follow" '
            f'data-mastodon-acct="{acct}" hidden>Follow on Mastodon</button>'
            "</p>"
        )

    # Sort/filter metadata for category-controls.js: data-name drives the
    # search box and alpha sort; data-score is the combined popularity score
    # (the default sort); data-followers/data-subscribers back the individual
    # sort options. Missing counts sort to the bottom via -1 / 0.
    sort_name = html.escape(creator.get("name", "").casefold(), quote=True)
    followers_n = creator.get("followers")
    followers_attr = int(followers_n) if isinstance(followers_n, int) else -1
    subs_n = creator.get("subscriber_count")
    subs_attr = int(subs_n) if isinstance(subs_n, int) else -1
    score_attr = f"{popularity_score(creator):.6g}"

    # The name links to the creator's own profile page; YouTube and Mastodon
    # remain as explicit secondary links.
    return (
        f'<li data-lang="{lang}" data-name="{sort_name}" data-score="{score_attr}"'
        f' data-followers="{followers_attr}" data-subscribers="{subs_attr}">'
        f'<strong><a href="{page_url}">{name}</a></strong>'
        f' · <a href="{primary_url}" target="_blank" rel="noopener noreferrer">YouTube</a>'
        f' · <a href="{mastodon_url}" target="_blank" rel="noopener noreferrer">{mastodon_label}</a>'
        f" — {description}"
        f"{follow_html}"
        f"{videos_html}"
        "</li>"
    )


def _section(section_key: str, heading: str, list_items: list[str]) -> str:
    """Wrap a heading and list items in a data-lang-section div.

    Everything is real HTML — including the ``<h2>`` — because Markdown
    syntax inside a block-level raw HTML element is not processed by Pelican.
    """
    return (
        f'<div data-lang-section="{html.escape(section_key, quote=True)}">\n'
        f"<h2>{html.escape(heading)}</h2>\n\n"
        "<ul>\n" + "\n".join(list_items) + "\n</ul>\n"
        "</div>"
    )


def _bulk_follow_block(youtubers: list[dict], scope_slug: str, scope_label: str) -> str:
    """Render an inline bulk-follow widget for the native accounts in scope.

    Provides both a copy-paste textarea and a client-side CSV download (Mastodon
    "Following list" import format). The download filename is made unique per
    scope and per download (timestamp) so saved files don't all collide on a
    generic name like ``accts.csv``.
    """
    handles = [
        f"@{_mastodon_account(item['mastodon_url'])}"
        for item in sorted(youtubers, key=lambda item: item.get("name", "").casefold())
        if item.get("account_type") == "native"
    ]
    if not handles:
        return ""

    textarea_value = html.escape("\n".join(handles))
    # Embed the handles as a JSON array for the download script.
    handles_json = html.escape(json.dumps(handles, ensure_ascii=False), quote=True)
    scope_attr = html.escape(scope_slug, quote=True)

    return f"""
<section class="bulk-follow" data-bulk-scope="{scope_attr}" data-bulk-handles="{handles_json}">
<h2>Follow {"this account" if len(handles) == 1 else f"these {len(handles)} accounts"}</h2>
<p>Copy the handles below, or download a CSV to import via your Mastodon server's
<strong>Preferences &rarr; Import and export &rarr; Import &rarr; Following list</strong>.
Prefer one click? Use the <a href="../mastodon-follow/">Follow on Mastodon</a> tool.</p>
<label class="bulk-follow__label" for="bulk-follow-{scope_attr}">Native accounts in {html.escape(scope_label)}</label>
<textarea id="bulk-follow-{scope_attr}" class="bulk-follow__text" rows="6" readonly spellcheck="false">{textarea_value}</textarea>
<div class="bulk-follow__actions">
<button type="button" class="bulk-follow__copy" data-bulk-copy>Copy handles</button>
<a class="bulk-follow__download" data-bulk-download href="#" download>Download CSV</a>
</div>
</section>
"""


BULK_FOLLOW_SCRIPT = """
<script>
(function () {
  function csvFor(handles) {
    var rows = ["Account address,Show boosts,Notify on new posts,Languages"];
    handles.forEach(function (h) { rows.push(h.replace(/^@/, "") + ",true,false,"); });
    return rows.join("\\n") + "\\n";
  }
  function stamp() {
    var d = new Date();
    function p(n) { return String(n).padStart(2, "0"); }
    return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "-" +
           p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds());
  }
  document.querySelectorAll(".bulk-follow").forEach(function (section) {
    var handles;
    try { handles = JSON.parse(section.getAttribute("data-bulk-handles")) || []; }
    catch (e) { handles = []; }
    var scope = section.getAttribute("data-bulk-scope") || "accounts";

    var copyBtn = section.querySelector("[data-bulk-copy]");
    var textarea = section.querySelector(".bulk-follow__text");
    if (copyBtn && textarea) {
      copyBtn.addEventListener("click", function () {
        var text = handles.join("\\n");
        function done() {
          var original = copyBtn.textContent;
          copyBtn.textContent = "Copied!";
          setTimeout(function () { copyBtn.textContent = original; }, 1500);
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, function () {
            textarea.select(); document.execCommand("copy"); done();
          });
        } else {
          textarea.select(); document.execCommand("copy"); done();
        }
      });
    }

    var dl = section.querySelector("[data-bulk-download]");
    if (dl) {
      dl.addEventListener("click", function (e) {
        e.preventDefault();
        var blob = new Blob([csvFor(handles)], { type: "text/csv;charset=utf-8" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        // Unique per scope and per download so saved files never collide.
        a.download = "mastodon-follows-" + scope + "-" + stamp() + ".csv";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(url); }, 0);
      });
    }
  });
})();
</script>
"""


def _category_controls(target_section: str) -> str:
    """Render a search + sort toolbar for a category listing.

    ``target_section`` is the ``data-lang-section`` value of the ``<ul>`` whose
    items the controls operate on. category-controls.js reads ``data-controls``
    to locate that section and its ``<li>`` items (which carry ``data-name`` and
    ``data-followers``). The toolbar is inert without JS — the static page still
    renders the default popularity-sorted list.
    """
    target = html.escape(target_section, quote=True)
    return (
        f'<div class="list-controls" data-controls="{target}" hidden>'
        '<input type="search" class="list-controls__search" '
        'placeholder="Filter by name…" aria-label="Filter accounts by name" '
        'data-controls-search />'
        '<div class="list-controls__buttons">'
        '<button type="button" class="list-controls__btn" data-controls-sort="score">'
        "Top picks</button>"
        '<button type="button" class="list-controls__btn" data-controls-sort="subscribers">'
        "Most subscribers</button>"
        '<button type="button" class="list-controls__btn" data-controls-sort="followers">'
        "Most followed</button>"
        '<button type="button" class="list-controls__btn" data-controls-sort="alpha">'
        "A–Z</button>"
        '<button type="button" class="list-controls__btn" data-controls-sort="shuffle">'
        "Shuffle</button>"
        "</div>"
        '<p class="list-controls__empty" data-controls-empty hidden>'
        "No accounts match your search.</p>"
        "</div>\n"
    )


def generate_category_page(category: str, youtubers: list[dict]) -> str:
    label = CATEGORY_LABELS[category]
    items = [item for item in youtubers if item.get("category") == category]
    # Bot/feed accounts are surfaced on their own page (see generate_bots_page),
    # so topic pages only carry native accounts and human-operated bridges.
    items = [item for item in items if item.get("account_type") not in BOT_ACCOUNT_TYPES]
    native = [item for item in items if item.get("account_type") == "native"]
    feeds = [item for item in items if item.get("account_type") != "native"]

    # Native section — wrapped in a data-lang-section div so JS can collapse
    # the whole block when all items are filtered out. Default order is by the
    # combined popularity score (YouTube subscribers × Mastodon followers, each
    # normalised to the directory average); category-controls.js can re-sort by
    # the individual metrics, alphabetically, or shuffle client-side.
    native_default = sorted(
        native,
        key=lambda item: (-popularity_score(item), item.get("name", "").casefold()),
    )
    native_items = [
        _creator_li(creator, "Mastodon", creator_videos(creator))
        for creator in native_default
    ]

    if native_items:
        native_block = _category_controls("native") + _section(
            "native", f"Native Mastodon accounts ({len(native)})", native_items
        )
    else:
        native_block = (
            f"<h2>Native Mastodon accounts ({len(native)})</h2>\n\nNo native accounts in this category yet."
        )

    feeds_block = ""
    if feeds:
        feed_items = [
            _creator_li(creator, "Bridge", creator_videos(creator))
            for creator in sorted(feeds, key=lambda item: item.get("name", "").casefold())
        ]
        feeds_block = "\n" + _section("feeds", f"Bridged accounts ({len(feeds)})", feed_items)

    bulk_block = _bulk_follow_block(native, category, label)

    return f"""Title: {label} YouTubers
Date: 2026-06-20
Slug: {category}
sortorder: {CATEGORY_SORTORDER.index(category) + 10}
Summary: {label} YouTube creators and channel feeds on Mastodon.

{native_block}{feeds_block}
{bulk_block}{BULK_FOLLOW_SCRIPT if bulk_block else ""}
"""


def generate_creator_page(creator: dict, videos: list | None = None) -> str:
    """Generate a per-creator profile page at /creator/{id}/.

    The page is static and crawlable: name, category, blurb (links live),
    YouTube + Mastodon links, and lite-embed cards for recent uploads. A
    ``data-creator-live`` placeholder lets creator-profile.js enrich the page
    with the creator's recent Mastodon posts and richer profile *when the
    visitor is logged in*; logged-out visitors still get the full static page.
    """
    name = html.escape(creator["name"])
    category = CATEGORY_LABELS.get(creator.get("category", "other"), "Other")
    primary_url = html.escape(creator.get("primary_url") or creator["youtube_url"], quote=True)
    mastodon_url = html.escape(creator["mastodon_url"], quote=True)
    acct = html.escape(_mastodon_account(creator["mastodon_url"]), quote=True)
    description = _linkify(creator.get("description") or "")
    followers = creator.get("followers")
    lang = html.escape(creator.get("language") or "en", quote=True)
    is_native = creator.get("account_type") == "native"

    follow_html = ""
    if is_native:
        follow_html = (
            '<p class="creator-follow-line">'
            f'<button type="button" class="creator-follow" '
            f'data-mastodon-acct="{acct}" hidden>Follow on Mastodon</button>'
            "</p>"
        )

    subscribers = creator.get("subscriber_count")
    stat_lines = []
    if subscribers:
        stat_lines.append(
            f'<p class="creator-stat">YouTube subscribers: <strong>{subscribers:,}</strong></p>'
        )
    if followers:
        stat_lines.append(
            f'<p class="creator-stat">Mastodon followers: <strong>{html.escape(str(followers))}</strong></p>'
        )
    followers_html = "\n".join(stat_lines)

    cards = _video_cards_html(videos or [])

    # Live-enrichment target. data-* attributes give the client script what it
    # needs to query the visitor's Mastodon instance for this creator.
    live_section = (
        '<section class="creator-live" data-creator-live '
        f'data-mastodon-acct="{acct}" data-mastodon-url="{mastodon_url}">'
        '<h2>Recent posts on Mastodon</h2>'
        '<p class="creator-live__hint" data-creator-live-hint>'
        "Log in (top-right) to load this creator's recent Mastodon posts."
        "</p>"
        '<div class="creator-live__feed" data-creator-live-feed hidden></div>'
        "</section>"
    )

    return f"""Title: {creator['name']}
Date: 2026-06-20
Slug: {creator['id']}
save_as: creator/{creator['id']}/index.html
url: creator/{creator['id']}/
status: hidden
Summary: {category} creator {creator['name']} on YouTube and Mastodon.

<article class="creator-profile" data-lang="{lang}">
<header class="creator-profile__header">
<p class="creator-profile__category">{html.escape(category)}</p>
<p class="creator-profile__links">
<a href="{primary_url}" target="_blank" rel="noopener noreferrer">YouTube channel</a>
 · <a href="{mastodon_url}" target="_blank" rel="noopener noreferrer">@{acct}</a>
</p>
{followers_html}
<p class="creator-profile__bio">{description}</p>
{follow_html}
</header>

{cards}

{live_section}
</article>
"""


def generate_bots_page(youtubers: list[dict]) -> str:
    """Collect every automated feed/bot account on one page, grouped by topic."""
    bots = [item for item in youtubers if item.get("account_type") in BOT_ACCOUNT_TYPES]

    sections = []
    for category in CATEGORY_SORTORDER:
        in_category = [item for item in bots if item.get("category") == category]
        if not in_category:
            continue
        label = CATEGORY_LABELS[category]
        bot_items = [
            _creator_li(creator, "Feed")
            for creator in sorted(in_category, key=lambda item: item.get("name", "").casefold())
        ]
        sections.append(_section(f"bots-{category}", f"{label} ({len(in_category)})", bot_items))

    body = "\n\n".join(sections) if sections else "No automated feeds in the directory yet."

    return f"""Title: Automated Feeds & Bots
Date: 2026-06-20
Slug: bots
sortorder: 8
Summary: Automated channel feeds and bot accounts that relay YouTube content to Mastodon.

## Automated Feeds & Bots

These {len(bots)} accounts are unattended automation — RSS feeds and bots that mirror a
channel's uploads to the Fediverse. They are grouped here, by topic, so the topic pages stay
focused on accounts you can actually interact with.

{body}
"""


def generate_bulk_follow_page(youtubers: list[dict]) -> str:
    handles = [
        f"@{_mastodon_account(item['mastodon_url'])}"
        for item in youtubers
        if item.get("account_type") == "native"
    ]
    csv_rows = ["Account address,Show boosts", *(f"{handle},true" for handle in handles)]
    return f"""Title: Bulk Follow Guide
Date: 2026-06-20
Slug: bulk-follow
sortorder: 3
Summary: How to bulk follow native YouTuber accounts on Mastodon.

## Bulk Follow on Mastodon

This list contains native Mastodon accounts only. Automated RSS feeds and bridges are excluded so
the follow pack stays focused on profiles where interaction is possible.

```text
{chr(10).join(handles)}
```

### Import a following list

Save the following as `follows.csv`, then import it from your Mastodon server's
**Preferences → Import and export → Import → Following list** screen.

```csv
{chr(10).join(csv_rows)}
```

### Interactive follow tool

Use the **[Follow on Mastodon](/mastodon-follow/)** page to browse and follow native accounts
one-by-one or all at once using PKCE OAuth.
"""


def main() -> None:
    global FETCH_FEEDS
    parser = argparse.ArgumentParser(description="Generate Pelican pages from youtubers.json")
    parser.add_argument("--dry-run", action="store_true", help="Print output without writing files")
    parser.add_argument(
        "--no-feeds",
        action="store_true",
        help="Skip fetching YouTube RSS feeds (faster, fully offline build)",
    )
    args = parser.parse_args()
    # Skip network during dry runs and when explicitly disabled.
    FETCH_FEEDS = not (args.no_feeds or args.dry_run)
    youtubers = youtuber_store.load()
    print(f"Loaded {len(youtubers)} YouTubers")
    compute_popularity_baselines(youtubers)
    youtubers, synced = sync_reviews(youtubers)
    if synced and not args.dry_run:
        youtuber_store.save(youtubers)

    generated = {
        "youtubers.md": generate_youtubers_page(youtubers),
        "bots.md": generate_bots_page(youtubers),
        "bulk-follow.md": generate_bulk_follow_page(youtubers),
        **{
            f"{category}.md": generate_category_page(category, youtubers)
            for category in CATEGORY_SORTORDER
        },
    }
    for filename, content in generated.items():
        path = PAGES_DIR / filename
        if args.dry_run:
            print(f"\n--- {path} ---\n{content[:300]}...")
        else:
            path.write_text(content, encoding="utf-8")
            print(f"Wrote {path}")

    # Per-creator profile pages under content/pages/creator/. Written even on
    # --no-feeds (the live section and links still render); only the video
    # cards are skipped when feeds are disabled.
    creator_dir = PAGES_DIR / "creator"
    creator_dir.mkdir(parents=True, exist_ok=True)
    creator_count = 0
    for creator in youtubers:
        if not creator.get("id"):
            continue
        content = generate_creator_page(creator, creator_videos(creator))
        if args.dry_run:
            if creator_count < 1:
                print(f"\n--- creator/{creator['id']} ---\n{content[:400]}...")
        else:
            (creator_dir / f"{creator['id']}.md").write_text(content, encoding="utf-8")
        creator_count += 1
    print(f"{'Would write' if args.dry_run else 'Wrote'} {creator_count} creator profile pages")

    if not args.dry_run:
        sync_follow_tool(youtubers)
        print(f"Updated {FOLLOW_TOOL_PATH}")


if __name__ == "__main__":
    main()
