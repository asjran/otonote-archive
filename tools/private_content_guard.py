"""Reject private-only namespaces and markers from public site trees."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".map",
    ".mjs",
    ".svg",
    ".txt",
    ".xml",
}
FORBIDDEN_MARKERS = (
    b"private local preview",
    b"/private-preview/anontokyo",
    b"anontokyo-private",
    b"ournotes_anontokyo_private_preview",
    b'"publicationstate": "private_preview"',
)
FORBIDDEN_PATH_TERMS = (
    "private-preview/anontokyo",
    "anontokyo-private",
)


class PrivateContentError(RuntimeError):
    """Raised when a public artifact contains private preview content."""


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def verify_no_private_content(root: Path) -> dict[str, Any]:
    """Scan one public tree through a small, failure-closed interface."""
    if not root.is_dir():
        raise PrivateContentError("public tree is missing")
    files_scanned = 0
    text_files_scanned = 0
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in [*dirnames, *filenames]:
            path = parent / name
            relative = _relative(root, path)
            if any(term in relative.casefold() for term in FORBIDDEN_PATH_TERMS):
                raise PrivateContentError(
                    f"private content path found in public tree: {relative}"
                )
        for name in filenames:
            path = parent / name
            if path.is_symlink():
                continue
            files_scanned += 1
            if path.suffix.casefold() not in TEXT_SUFFIXES:
                continue
            text_files_scanned += 1
            try:
                content = path.read_bytes().lower()
            except OSError as exc:
                raise PrivateContentError(
                    f"public file is unreadable: {_relative(root, path)}"
                ) from exc
            for marker in FORBIDDEN_MARKERS:
                if marker in content:
                    raise PrivateContentError(
                        "private content marker found in public file: "
                        f"{_relative(root, path)}"
                    )
    return {
        "filesScanned": files_scanned,
        "textFilesScanned": text_files_scanned,
        "status": "clean",
    }
