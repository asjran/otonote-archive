"""Deduplicate verified media inside a build candidate using hard links."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator


class MediaDedupeError(RuntimeError):
    """Raised when indexed media cannot be safely deduplicated."""


@dataclass(frozen=True)
class MediaDedupeResult:
    duplicate_groups: int
    linked_files: int
    bytes_saved: int


def _indexed_files(value: Any) -> Iterator[tuple[str, int, str]]:
    if isinstance(value, dict):
        url = value.get("url")
        byte_size = value.get("byteSize")
        digest = value.get("sha256")
        if (
            isinstance(url, str)
            and url.startswith("/media/")
            and isinstance(byte_size, int)
            and byte_size >= 0
            and isinstance(digest, str)
            and len(digest) == 64
        ):
            yield url, byte_size, digest
        for child in value.values():
            yield from _indexed_files(child)
    elif isinstance(value, list):
        for child in value:
            yield from _indexed_files(child)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_media_path(media_root: Path, url: str) -> Path:
    relative = PurePosixPath(url.removeprefix("/media/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise MediaDedupeError(f"unsafe media URL in index: {url}")
    path = media_root.joinpath(*relative.parts)
    try:
        path.resolve(strict=True).relative_to(media_root)
    except (OSError, ValueError) as exc:
        raise MediaDedupeError(f"indexed media is unavailable: {url}") from exc
    if not path.is_file() or path.is_symlink():
        raise MediaDedupeError(f"indexed media is not a regular file: {url}")
    return path


def deduplicate_indexed_media(
    media_root: Path,
    media_index: Path,
) -> MediaDedupeResult:
    """Hard-link duplicate indexed files after verifying their real digest."""
    media_root = media_root.resolve()
    try:
        payload = json.loads(media_index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MediaDedupeError(f"cannot read media index: {media_index}") from exc

    by_identity: dict[tuple[int, str], set[str]] = defaultdict(set)
    for url, byte_size, digest in _indexed_files(payload):
        by_identity[(byte_size, digest)].add(url)

    duplicate_groups = 0
    linked_files = 0
    bytes_saved = 0
    for (byte_size, digest), urls in sorted(by_identity.items()):
        if len(urls) < 2:
            continue
        paths = [
            _resolve_media_path(media_root, url)
            for url in sorted(urls)
        ]
        for path in paths:
            if path.stat().st_size != byte_size or _sha256(path) != digest:
                raise MediaDedupeError(
                    f"indexed media digest mismatch: "
                    f"{path.relative_to(media_root)}"
                )
        duplicate_groups += 1
        canonical = paths[0]
        for target in paths[1:]:
            if canonical.stat().st_ino == target.stat().st_ino:
                continue
            temporary = target.with_name(
                f".{target.name}.dedupe-{uuid.uuid4().hex[:10]}"
            )
            try:
                os.link(canonical, temporary)
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()
            linked_files += 1
            bytes_saved += byte_size

    return MediaDedupeResult(
        duplicate_groups=duplicate_groups,
        linked_files=linked_files,
        bytes_saved=bytes_saved,
    )
