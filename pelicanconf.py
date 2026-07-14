import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import categorize

AUTHOR = 'YouTubers on Mastodon'
SITENAME = 'YouTubers on Mastodon'
SITESUBTITLE = 'Find YouTube creators, channel feeds, and real people to follow on Mastodon.'
SITEURL = ''
CURRENTYEAR = datetime.now().year
GENERATED_DATE = datetime.now().strftime('%Y-%m-%d')

PATH = 'content'

TIMEZONE = 'UTC'

DEFAULT_LANG = 'en'

# Feed generation is usually not needed for static listings
FEED_ALL_ATOM = None
CATEGORY_FEED_ATOM = None
TRANSLATION_FEED_ATOM = None
AUTHOR_FEED_ATOM = None
AUTHOR_FEED_RSS = None

LINKS = ()
SOCIAL = ()

DEFAULT_PAGINATION = 20

# ── Sidebar categories ──────────────────────────────────────────────────────
# The sidebar should only list category pages that actually have content.
# A category page (see generate_pages.generate_category_page) shows native and
# bridged accounts but NOT unattended bot/feed accounts, so a category is
# "empty" — and suppressed from the menu — when all of its entries are bots.
# Exposed to templates as SIDEBAR_CATEGORIES (list of {slug, label}).
_BOT_ACCOUNT_TYPES = {"rss-feed", "channel-feed", "bot"}


def _nonempty_categories():
    data_path = Path(__file__).parent / "data" / "youtubers.json"
    try:
        creators = json.loads(data_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        creators = []
    present = {
        c.get("category", "other")
        for c in creators
        if c.get("account_type") not in _BOT_ACCOUNT_TYPES
    }
    return [
        {"slug": slug, "label": categorize.CATEGORY_LABELS[slug]}
        for slug in categorize.CATEGORY_SORTORDER
        if slug in present
    ]


SIDEBAR_CATEGORIES = _nonempty_categories()

# Curated short labels for the horizontal top nav. Only those that are also in
# SIDEBAR_CATEGORIES (i.e. non-empty) are rendered.
TOP_NAV_CATEGORIES = {
    "technology": "Technology",
    "gaming": "Gaming",
    "science-education": "Education",
    "music": "Music",
    "news-society": "News",
}

def _sort_by_sortorder(pages):
    return sorted(pages, key=lambda p: int(getattr(p, 'sortorder', 99)))

JINJA_FILTERS = {'sort_by_sortorder': _sort_by_sortorder}

DISPLAY_PAGES_ON_MENU = True
DISPLAY_CATEGORIES_ON_MENU = False

THEME = 'themes/simple-pages'

PAGE_URL = '{slug}/'
PAGE_SAVE_AS = '{slug}/index.html'
ARTICLE_URL = 'reviews/{slug}/'
ARTICLE_SAVE_AS = 'reviews/{slug}/index.html'

DIRECT_TEMPLATES = ['index', 'tags']
ARCHIVES_SAVE_AS = ''
AUTHOR_SAVE_AS = ''
AUTHORS_SAVE_AS = ''
CATEGORY_SAVE_AS = ''
CATEGORIES_SAVE_AS = ''
TAG_URL = 'tag/{slug}/'
TAG_SAVE_AS = 'tag/{slug}/index.html'
TAGS_SAVE_AS = 'tags/index.html'
