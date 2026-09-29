"""Render an image-only query offline without QQ credentials."""
from __future__ import annotations

import argparse
from pathlib import Path

from backend.qqbot.content import Content
from backend.qqbot.query import Queries
from backend.qqbot.render import Renderer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--font")
    parser.add_argument("command")
    args = parser.parse_args()
    content = Content(args.bundle)
    images = Renderer(content.snapshot, args.font).render(Queries(content).query(args.command))
    args.output.mkdir(parents=True, exist_ok=False)
    for i, image in enumerate(images, 1):
        path = args.output / f"{i}.png"
        path.write_bytes(image)
        print(path.resolve())


if __name__ == "__main__":
    main()
