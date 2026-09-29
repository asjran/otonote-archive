#!/usr/bin/env python3
"""Report fixed CSS font sizes that fall below the site readability floor."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable


FONT_SIZE_PATTERN = re.compile(
    r"font-size\s*:\s*(?P<size>\d+(?:\.\d+)?)px\b",
    re.IGNORECASE,
)


def find_undersized_font_declarations(
    paths: Iterable[Path], minimum_px: float = 12
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in paths:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in FONT_SIZE_PATTERN.finditer(line):
                size_px = float(match.group("size"))
                if size_px >= minimum_px:
                    continue
                findings.append(
                    {
                        "path": str(path),
                        "line": line_number,
                        "size_px": size_px,
                        "source": line.strip(),
                    }
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=sorted(Path("site/src/styles").glob("*.css")),
    )
    parser.add_argument("--minimum", type=float, default=12)
    arguments = parser.parse_args()
    findings = find_undersized_font_declarations(
        arguments.paths, minimum_px=arguments.minimum
    )
    print(json.dumps(findings, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
