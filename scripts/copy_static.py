from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy hand-crafted static files into the Pelican output.")
    parser.add_argument("siteurl", nargs="?", default="")
    args = parser.parse_args()

    source = Path("static")
    destination = Path("output")
    if not source.is_dir():
        return

    for source_file in source.rglob("*"):
        if not source_file.is_file():
            continue
        relative = source_file.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source_file.suffix in {".html", ".htm"}:
            text = source_file.read_text(encoding="utf-8").replace("{{SITEURL}}", args.siteurl)
            target.write_text(text, encoding="utf-8")
        else:
            shutil.copy2(source_file, target)
        print(f"copied: {relative} (siteurl={args.siteurl!r})")


if __name__ == "__main__":
    main()
