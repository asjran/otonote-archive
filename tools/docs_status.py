"""Validate the small, explicit status registry for design documents."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ALLOWED_STATUSES = {
    "proposed",
    "accepted",
    "implemented",
    "partially-implemented",
    "superseded",
    "historical",
}
TABLE_ROW = re.compile(
    r"^\|\s*`(?P<document>[^`]+)`\s*"
    r"\|\s*`(?P<status>[^`]+)`\s*"
    r"\|\s*(?P<superseded>.*?)\s*"
    r"\|\s*(?P<evidence>.*?)\s*"
    r"\|\s*(?P<verified>.*?)\s*\|$"
)
BACKTICK_PATH = re.compile(r"`([^`]+)`")
DESIGN_ROOTS = (
    Path("docs/superpowers/specs"),
    Path("docs/superpowers/plans"),
)


def validate_status_index(repo_root: Path, status_path: Path) -> list[str]:
    """Return stable validation errors for the document status table."""
    errors: list[str] = []
    seen: set[str] = set()
    try:
        lines = status_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [f"cannot read status index: {exc}"]

    for line_number, line in enumerate(lines, start=1):
        match = TABLE_ROW.match(line)
        if match is None:
            continue
        document = match.group("document")
        status = match.group("status")
        if status not in ALLOWED_STATUSES:
            errors.append(
                f"line {line_number}: unknown document status: {status}"
            )
        if document in seen:
            errors.append(
                f"line {line_number}: duplicate document entry: {document}"
            )
        seen.add(document)
        if not (repo_root / document).is_file():
            errors.append(
                f"line {line_number}: document does not exist: {document}"
            )

        superseded = match.group("superseded")
        for referenced in BACKTICK_PATH.findall(superseded):
            if not (repo_root / referenced).is_file():
                errors.append(
                    f"line {line_number}: superseding document does not exist: "
                    f"{referenced}"
                )

    if not seen:
        errors.append("status index contains no document entries")
    expected = {
        path.relative_to(repo_root).as_posix()
        for design_root in DESIGN_ROOTS
        for path in (repo_root / design_root).glob("*.md")
        if path.is_file()
    }
    for document in sorted(expected - seen):
        errors.append(f"design document is not registered: {document}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--status",
        type=Path,
        default=None,
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    status_path = (
        args.status.resolve()
        if args.status is not None
        else repo_root / "docs/STATUS.md"
    )
    errors = validate_status_index(repo_root, status_path)
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"Validated document status index: {status_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
