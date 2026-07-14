from __future__ import annotations

import argparse
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse


class DocumentSummary(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doctype = False
        self.html_lang = ""
        self.in_title = False
        self.title_parts: list[str] = []
        self.viewport = False
        self.h1_count = 0
        self.assets: list[tuple[str, str]] = []

    @property
    def title(self) -> str:
        return "".join(self.title_parts).strip()

    def handle_decl(self, decl: str) -> None:
        if decl.lower() == "doctype html":
            self.doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        if tag == "html":
            self.html_lang = attr.get("lang", "").strip()
        elif tag == "title":
            self.in_title = True
        elif tag == "meta" and attr.get("name", "").lower() == "viewport":
            self.viewport = bool(attr.get("content", "").strip())
        elif tag == "h1":
            self.h1_count += 1
        elif tag in {"link", "script", "img"}:
            key = "href" if tag == "link" else "src"
            value = attr.get(key, "").strip()
            if value:
                self.assets.append((tag, value))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)


def site_path_for_url(site_dir: Path, url: str, siteurl_prefix: str = "") -> Path | None:
    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc or url.startswith(("#", "data:", "mailto:", "tel:", "javascript:")):
        return None

    path = unquote(parsed.path)
    if not path or path == "/":
        return site_dir / "index.html"

    # Strip the sub-path prefix injected by copy_static.py (e.g. /youtuberfinder)
    # so that /youtuberfinder/theme/css/style.css resolves to
    # <site_dir>/theme/css/style.css instead of <site_dir>/youtuberfinder/theme/…
    if siteurl_prefix and path.startswith(siteurl_prefix):
        path = path[len(siteurl_prefix):] or "/"

    relative = path.lstrip("/")
    candidate = site_dir / relative
    if path.endswith("/"):
        return candidate / "index.html"
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint generated Pelican output for basic artifact sanity.")
    parser.add_argument("--site-dir", default="output", type=Path)
    parser.add_argument(
        "--siteurl",
        default="",
        help="Sub-path prefix used in production (e.g. /youtuberfinder). "
             "Must match the value passed to copy_static.py.",
    )
    args = parser.parse_args()

    # Normalise: strip trailing slash, keep leading slash (or empty string).
    siteurl_prefix = args.siteurl.rstrip("/")

    site_dir = args.site_dir.resolve()
    html_files = sorted(site_dir.rglob("*.html"))
    errors: list[str] = []

    if not site_dir.exists():
        errors.append(f"{site_dir}: site output directory does not exist; run make html first")
    if site_dir.exists() and not html_files:
        errors.append(f"{site_dir}: no generated HTML files found")

    for html_file in html_files:
        try:
            text = html_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"{html_file}: is not valid UTF-8 ({exc})")
            continue

        rel = html_file.relative_to(site_dir)
        summary = DocumentSummary()
        try:
            summary.feed(text)
        except Exception as exc:
            errors.append(f"{rel}: could not parse generated HTML ({exc})")
            continue

        if not text.strip():
            errors.append(f"{rel}: file is empty")
        if not summary.doctype:
            errors.append(f"{rel}: missing <!doctype html>")
        if not summary.html_lang:
            errors.append(f"{rel}: missing <html lang=\"...\">")
        if not summary.title:
            errors.append(f"{rel}: missing non-empty <title>")
        if not summary.viewport:
            errors.append(f"{rel}: missing viewport meta tag")
        if summary.h1_count == 0:
            errors.append(f"{rel}: missing an h1")

        for tag, url in summary.assets:
            asset_path = site_path_for_url(site_dir, url, siteurl_prefix)
            if asset_path and not asset_path.exists():
                errors.append(f"{rel}: {tag} asset does not exist: {url}")

    if errors:
        print("Pelican artifact lint failed:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"Pelican artifact lint passed ({len(html_files)} HTML files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
