"""Check V1 candidate routes, HTML references and closed media before publication."""
from __future__ import annotations

import argparse
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and key in {"href", "src", "poster"}:
                self.urls.append(value)
            if value and key == "srcset":
                self.urls.extend(part.strip().split()[0] for part in value.split(",") if part.strip())


def verify(root: Path) -> dict:
    failures = set()
    pages = 0
    references = 0
    for directory, _, files in os.walk(root, followlinks=False):
        for name in files:
            path = Path(directory) / name
            if path.is_symlink() or path.suffix != ".html":
                continue
            pages += 1
            relative = path.relative_to(root).as_posix()
            if re.search(r"(?:^|/)(resources|anontokyo)/", relative):
                failures.add(f"closed route: {relative}")
            parser = References()
            parser.feed(path.read_text())
            for url in parser.urls:
                if url.startswith(("#", "data:", "mailto:", "tel:", "http:", "https:", "//")):
                    continue
                target_path = unquote(urlsplit(urljoin("/" + relative, url)).path)
                target = root / target_path.lstrip("/")
                references += 1
                if not (target.is_file() or (target / "index.html").is_file()):
                    failures.add(f"missing: {target_path}")
    for name in ("live2d", "device-archive", "story-resources", "character-textures", "audio", "audio-preview", "music", "anontokyo", "anontokyo-private"):
        if (root / "media" / name).exists():
            failures.add(f"closed media: {name}")
    return {"status": "failed" if failures else "passed", "htmlFiles": pages, "references": references, "failures": sorted(failures)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.root)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text)
    raise SystemExit(report["status"] != "passed")
