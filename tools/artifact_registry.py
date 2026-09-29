#!/usr/bin/env python3
"""Central registry for versioned site artifacts."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any


ARTIFACT_SCHEMA_VERSIONS = MappingProxyType(
    {
        "catalog.json": 6,
        "database-shards/manifest.json": 1,
        "release-index.json": 1,
        "story-resources.json": 2,
    }
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def schema_versions() -> dict[str, int]:
    """Return a stable, caller-owned map of published artifact versions."""

    return dict(ARTIFACT_SCHEMA_VERSIONS)


class ArtifactValidationError(ValueError):
    """Raised when a registered artifact does not satisfy its contract."""


def _require_mapping(
    artifact_path: str, payload: Mapping[str, Any], field: str
) -> Mapping[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise ArtifactValidationError(
            f"{artifact_path}: {field} must be an object"
        )
    return value


def _require_list(
    artifact_path: str, payload: Mapping[str, Any], field: str
) -> list[Any]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise ArtifactValidationError(
            f"{artifact_path}: {field} must be an array"
        )
    return value


def _require_nonempty_string(
    artifact_path: str, payload: Mapping[str, Any], field: str
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ArtifactValidationError(
            f"{artifact_path}: {field} must be a non-empty string"
        )
    return value


def _require_nonnegative_integer(
    artifact_path: str, payload: Mapping[str, Any], field: str
) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactValidationError(
            f"{artifact_path}: {field} must be a non-negative integer"
        )
    return value


def _validate_catalog(payload: Mapping[str, Any]) -> None:
    artifact_path = "catalog.json"
    release = _require_mapping(artifact_path, payload, "release")
    projection = _require_mapping(
        artifact_path, payload, "projectionContext"
    )
    release_identity = (
        _require_nonempty_string(artifact_path, release, "id"),
        _require_nonempty_string(artifact_path, release, "region"),
        _require_nonempty_string(artifact_path, release, "channel"),
        _require_nonempty_string(artifact_path, release, "locale"),
    )
    projection_identity = (
        _require_nonempty_string(
            artifact_path, projection, "contentReleaseId"
        ),
        _require_nonempty_string(artifact_path, projection, "region"),
        _require_nonempty_string(artifact_path, projection, "channel"),
        _require_nonempty_string(artifact_path, projection, "locale"),
    )
    if projection_identity != release_identity:
        raise ArtifactValidationError(
            f"{artifact_path}: projectionContext must match release identity"
        )
    for field in (
        "bands",
        "characters",
        "memberCards",
        "supportCards",
        "musicTracks",
        "assets",
    ):
        _require_list(artifact_path, payload, field)


def _validate_story_resources(payload: Mapping[str, Any]) -> None:
    artifact_path = "story-resources.json"
    _require_nonempty_string(artifact_path, payload, "sourceReleaseId")
    _require_mapping(artifact_path, payload, "source")
    summary = _require_mapping(artifact_path, payload, "summary")
    _require_mapping(artifact_path, summary, "byKind")
    _require_mapping(artifact_path, summary, "byBrowserState")
    resources = _require_list(artifact_path, payload, "resources")
    if summary.get("total") != len(resources):
        raise ArtifactValidationError(
            f"{artifact_path}: summary.total must equal resources length"
        )


def _projection_identity(
    artifact_path: str, entry: Mapping[str, Any]
) -> tuple[str, str, str, str]:
    return tuple(
        _require_nonempty_string(artifact_path, entry, field)
        for field in ("contentReleaseId", "region", "channel", "locale")
    )


def _validate_release_index(payload: Mapping[str, Any]) -> None:
    artifact_path = "release-index.json"
    active = _require_mapping(artifact_path, payload, "active")
    active_identity = _projection_identity(artifact_path, active)
    _require_nonempty_string(artifact_path, active, "catalogPath")
    projections = _require_list(artifact_path, payload, "projections")
    if not projections:
        raise ArtifactValidationError(
            f"{artifact_path}: projections must not be empty"
        )

    identities: list[tuple[str, str, str, str]] = []
    for entry in projections:
        if not isinstance(entry, Mapping):
            raise ArtifactValidationError(
                f"{artifact_path}: each projection must be an object"
            )
        identities.append(_projection_identity(artifact_path, entry))
        _require_nonempty_string(artifact_path, entry, "catalogPath")
    if active_identity not in identities:
        raise ArtifactValidationError(
            f"{artifact_path}: active projection is not in projections"
        )


def _validate_database_shard_manifest(payload: Mapping[str, Any]) -> None:
    artifact_path = "database-shards/manifest.json"
    _require_nonempty_string(artifact_path, payload, "contentReleaseId")
    file_count = _require_nonnegative_integer(
        artifact_path, payload, "fileCount"
    )
    total_bytes = _require_nonnegative_integer(
        artifact_path, payload, "totalBytes"
    )
    files = _require_list(artifact_path, payload, "files")
    if file_count != len(files):
        raise ArtifactValidationError(
            f"{artifact_path}: fileCount must equal files length"
        )

    recorded_bytes = 0
    seen_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, Mapping):
            raise ArtifactValidationError(
                f"{artifact_path}: each file must be an object"
            )
        relative = _require_nonempty_string(artifact_path, entry, "path")
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or relative in seen_paths:
            raise ArtifactValidationError(
                f"{artifact_path}: file paths must be unique safe relative paths"
            )
        seen_paths.add(relative)
        _require_nonempty_string(artifact_path, entry, "kind")
        _require_nonnegative_integer(artifact_path, entry, "recordCount")
        digest = _require_nonempty_string(artifact_path, entry, "sha256")
        if SHA256_PATTERN.fullmatch(digest) is None:
            raise ArtifactValidationError(
                f"{artifact_path}: sha256 must be a lowercase SHA-256 digest"
            )
        recorded_bytes += _require_nonnegative_integer(
            artifact_path, entry, "byteSize"
        )
    if total_bytes != recorded_bytes:
        raise ArtifactValidationError(
            f"{artifact_path}: totalBytes must equal file byteSize total"
        )


def validate_artifact(
    artifact_path: str, payload: Any
) -> Mapping[str, Any]:
    """Validate a registered artifact and return its original mapping."""

    expected_version = ARTIFACT_SCHEMA_VERSIONS.get(artifact_path)
    if expected_version is None:
        raise KeyError(f"unregistered artifact: {artifact_path}")
    if not isinstance(payload, Mapping):
        raise ArtifactValidationError(f"{artifact_path}: root must be an object")
    if payload.get("schemaVersion") != expected_version:
        raise ArtifactValidationError(
            f"{artifact_path}: schemaVersion must be {expected_version}"
        )
    if artifact_path == "catalog.json":
        _validate_catalog(payload)
    elif artifact_path == "story-resources.json":
        _validate_story_resources(payload)
    elif artifact_path == "release-index.json":
        _validate_release_index(payload)
    elif artifact_path == "database-shards/manifest.json":
        _validate_database_shard_manifest(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate registered generated site artifacts."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "site/src/data/generated",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        for artifact_path in ARTIFACT_SCHEMA_VERSIONS:
            path = root / artifact_path
            payload = json.loads(path.read_text(encoding="utf-8"))
            validate_artifact(artifact_path, payload)
    except (
        ArtifactValidationError,
        json.JSONDecodeError,
        KeyError,
        OSError,
    ) as exc:
        print(f"Artifact registry validation failed: {exc}")
        return 1
    print(
        f"Validated {len(ARTIFACT_SCHEMA_VERSIONS)} registered artifacts "
        f"under {root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
