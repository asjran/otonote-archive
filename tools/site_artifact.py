"""Build and verify immutable Site Artifact v2 release metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from pathlib import PurePosixPath
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.private_content_guard import (  # noqa: E402
    PrivateContentError,
    verify_no_private_content,
)


ARTIFACT_MANIFEST = "artifact-manifest.json"
RELEASE_MANIFEST = ".release.json"


class ArtifactError(RuntimeError):
    """Raised when a site artifact cannot be built or verified safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.next")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"{label} is unreadable") from exc


def _content_releases(release_index: Path) -> list[dict[str, str]]:
    try:
        value = json.loads(release_index.read_text(encoding="utf-8"))
        projections = value["projections"]
        if value["schemaVersion"] != 1 or not isinstance(projections, list):
            raise ValueError
        references = {
            (
                item["region"],
                item["channel"],
                item["contentReleaseId"],
            )
            for item in projections
        }
        if not references:
            raise ValueError
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ArtifactError("release index contract is invalid") from exc
    return [
        {"channel": channel, "id": release_id, "region": region}
        for region, channel, release_id in sorted(references)
    ]


def _is_media(relative: Path) -> bool:
    return bool(relative.parts) and relative.parts[0] == "media"


def _symlink_entry(artifact_root: Path, path: Path) -> dict[str, str]:
    relative = path.relative_to(artifact_root)
    try:
        path.resolve(strict=True).relative_to(artifact_root)
    except (OSError, ValueError) as exc:
        raise ArtifactError(
            f"artifact symlink points outside the artifact: {relative}"
        ) from exc
    return {"path": relative.as_posix(), "target": os.readlink(path)}


def _inventory(artifact_root: Path) -> tuple[dict[str, object], int, int, int, int]:
    files: list[dict[str, object]] = []
    symlinks: list[dict[str, str]] = []
    file_count = 0
    total_bytes = 0
    media_file_count = 0
    media_total_bytes = 0
    excluded = {ARTIFACT_MANIFEST, RELEASE_MANIFEST}

    for directory, dirnames, filenames in os.walk(
        artifact_root, followlinks=False
    ):
        parent = Path(directory)
        for name in list(dirnames):
            path = parent / name
            if path.is_symlink():
                symlinks.append(_symlink_entry(artifact_root, path))
                dirnames.remove(name)
        for name in filenames:
            if name == ".DS_Store":
                continue
            path = parent / name
            relative = path.relative_to(artifact_root)
            if path.is_symlink():
                symlinks.append(_symlink_entry(artifact_root, path))
                continue
            if relative.as_posix() in excluded:
                continue
            size = path.stat().st_size
            file_count += 1
            total_bytes += size
            if _is_media(relative):
                media_file_count += 1
                media_total_bytes += size
            else:
                files.append(
                    {
                        "bytes": size,
                        "path": relative.as_posix(),
                        "sha256": _sha256(path),
                        "type": path.suffix.lower().removeprefix(".") or "file",
                    }
                )

    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "files": sorted(files, key=lambda item: str(item["path"])),
        "symlinks": sorted(symlinks, key=lambda item: item["path"]),
    }
    return (
        manifest,
        file_count,
        total_bytes,
        media_file_count,
        media_total_bytes,
    )


def _require_v2_identity(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("schemaVersion") != 2:
        raise ArtifactError("Site Artifact v2 release manifest is required")
    required = {
        "siteReleaseId": str,
        "gitCommit": str,
        "dockerImage": str,
        "builtAt": str,
        "contentReleases": list,
        "packageLockSha256": str,
        "artifactManifestSha256": str,
        "schemas": dict,
        "fileCount": int,
        "totalBytes": int,
        "media": dict,
    }
    for name, expected_type in required.items():
        if not isinstance(value.get(name), expected_type):
            raise ArtifactError(f"release manifest field is invalid: {name}")
    if not re.fullmatch(
        r"[a-z0-9][a-z0-9-]*", str(value["siteReleaseId"])
    ):
        raise ArtifactError("release manifest field is invalid: siteReleaseId")
    if not re.fullmatch(r"[0-9a-f]{7,64}", str(value["gitCommit"])):
        raise ArtifactError("release manifest field is invalid: gitCommit")
    if not str(value["dockerImage"]).strip():
        raise ArtifactError("release manifest field is invalid: dockerImage")
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z",
        str(value["builtAt"]),
    ):
        raise ArtifactError("release manifest field is invalid: builtAt")
    for hash_field in ("packageLockSha256", "artifactManifestSha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(value[hash_field])):
            raise ArtifactError(f"release manifest field is invalid: {hash_field}")
    references = value["contentReleases"]
    assert isinstance(references, list)
    server_keys: set[tuple[str, str]] = set()
    for reference in references:
        if not isinstance(reference, dict) or set(reference) != {
            "channel",
            "id",
            "region",
        }:
            raise ArtifactError(
                "release manifest field is invalid: contentReleases"
            )
        if any(
            not isinstance(reference[field], str)
            or not re.fullmatch(
                r"[a-z0-9][a-z0-9-]*", reference[field]
            )
            for field in ("channel", "id", "region")
        ):
            raise ArtifactError(
                "release manifest field is invalid: contentReleases"
            )
        server_key = (reference["region"], reference["channel"])
        if server_key in server_keys:
            raise ArtifactError(
                "release manifest contains duplicate ContentRelease servers"
            )
        server_keys.add(server_key)
    if not references:
        raise ArtifactError(
            "release manifest field is invalid: contentReleases"
        )
    for statistic in ("fileCount", "totalBytes"):
        number = value[statistic]
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise ArtifactError(
                f"release manifest field is invalid: {statistic}"
            )
    schemas = value["schemas"]
    assert isinstance(schemas, dict)
    if any(
        not isinstance(name, str)
        or not name
        or not isinstance(version, int)
        or isinstance(version, bool)
        or version < 1
        for name, version in schemas.items()
    ):
        raise ArtifactError("release manifest field is invalid: schemas")
    media = value["media"]
    assert isinstance(media, dict)
    index_path = media.get("indexPath")
    if not isinstance(index_path, str):
        raise ArtifactError("release manifest media indexPath is invalid")
    parsed_index_path = PurePosixPath(index_path)
    if parsed_index_path.is_absolute() or ".." in parsed_index_path.parts:
        raise ArtifactError("release manifest media indexPath is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(media.get("indexSha256"))):
        raise ArtifactError("release manifest media indexSha256 is invalid")
    for statistic in ("fileCount", "totalBytes"):
        number = media.get(statistic)
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise ArtifactError(
                f"release manifest media {statistic} is invalid"
            )
    return value


def build_artifact(
    *,
    artifact_root: Path,
    release_index: Path,
    package_lock: Path,
    media_index: Path,
    schemas: Mapping[str, int],
    site_release_id: str,
    git_commit: str,
    docker_image: str,
    built_at: str,
) -> dict[str, object]:
    """Write v2 metadata for a complete, immutable static site tree."""

    artifact_root = artifact_root.resolve()
    if not (artifact_root / "index.html").exists():
        raise ArtifactError("artifact is missing index.html")
    try:
        verify_no_private_content(artifact_root)
    except PrivateContentError as exc:
        raise ArtifactError(str(exc)) from exc
    try:
        media_relative = media_index.resolve().relative_to(artifact_root)
    except ValueError as exc:
        raise ArtifactError("media index must be inside the artifact") from exc

    manifest, file_count, total_bytes, media_count, media_bytes = _inventory(
        artifact_root
    )
    _write_json(artifact_root / ARTIFACT_MANIFEST, manifest)
    artifact_manifest_sha256 = _sha256(artifact_root / ARTIFACT_MANIFEST)
    identity: dict[str, object] = {
        "schemaVersion": 2,
        "siteReleaseId": site_release_id,
        "gitCommit": git_commit,
        "dockerImage": docker_image,
        "builtAt": built_at,
        "contentReleases": _content_releases(release_index),
        "packageLockSha256": _sha256(package_lock),
        "artifactManifestSha256": artifact_manifest_sha256,
        "schemas": dict(sorted(schemas.items())),
        "fileCount": file_count,
        "totalBytes": total_bytes,
        "media": {
            "indexPath": media_relative.as_posix(),
            "indexSha256": _sha256(media_index),
            "fileCount": media_count,
            "totalBytes": media_bytes,
        },
    }
    _require_v2_identity(identity)
    _write_json(artifact_root / RELEASE_MANIFEST, identity)
    return identity


def verify_artifact(
    artifact_root: Path,
    *,
    expected_git_commit: str | None = None,
    package_lock: Path | None = None,
    release_index: Path | None = None,
    expected_schemas: Mapping[str, int] | None = None,
) -> dict[str, object]:
    """Verify release identity and every core file through the v2 seam."""

    artifact_root = artifact_root.resolve()
    identity = _require_v2_identity(
        _load_json(artifact_root / RELEASE_MANIFEST, "release manifest")
    )
    if (
        expected_git_commit is not None
        and identity["gitCommit"] != expected_git_commit
    ):
        raise ArtifactError("artifact Git commit does not match expected Git commit")
    if package_lock is not None and identity["packageLockSha256"] != _sha256(
        package_lock
    ):
        raise ArtifactError("artifact package lock does not match")
    if (
        release_index is not None
        and identity["contentReleases"] != _content_releases(release_index)
    ):
        raise ArtifactError("artifact ContentRelease references do not match")
    if expected_schemas is not None and identity["schemas"] != dict(
        sorted(expected_schemas.items())
    ):
        raise ArtifactError("artifact Schema versions do not match")

    manifest_path = artifact_root / ARTIFACT_MANIFEST
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != identity[
        "artifactManifestSha256"
    ]:
        raise ArtifactError("artifact manifest digest does not match")
    recorded_manifest = _load_json(manifest_path, "artifact manifest")
    (
        actual_manifest,
        file_count,
        total_bytes,
        media_count,
        media_bytes,
    ) = _inventory(artifact_root)
    if recorded_manifest != actual_manifest:
        raise ArtifactError("artifact manifest does not match the artifact tree")
    if identity["fileCount"] != file_count or identity["totalBytes"] != total_bytes:
        raise ArtifactError("artifact file statistics do not match")

    media = identity["media"]
    assert isinstance(media, dict)
    try:
        media_index = artifact_root / str(media["indexPath"])
        if _sha256(media_index) != media["indexSha256"]:
            raise ArtifactError("media index digest does not match")
        if media["fileCount"] != media_count or media["totalBytes"] != media_bytes:
            raise ArtifactError("media file statistics do not match")
    except (KeyError, OSError) as exc:
        raise ArtifactError("media index summary is invalid") from exc
    return identity


def _schema_versions(media_index: Path) -> dict[str, int]:
    from tools.artifact_registry import schema_versions

    versions = schema_versions()
    media_value = _load_json(media_index, "media index")
    if not isinstance(media_value, dict) or not isinstance(
        media_value.get("schemaVersion"), int
    ):
        raise ArtifactError("media index schemaVersion is invalid")
    versions.update(
        {
            ".release.json": 2,
            ARTIFACT_MANIFEST: 1,
            "media-index.json": media_value["schemaVersion"],
        }
    )
    return versions


def _parse_schemas(values: list[str], media_index: Path) -> dict[str, int]:
    if not values:
        return _schema_versions(media_index)
    schemas: dict[str, int] = {}
    try:
        for item in values:
            name, raw_version = item.rsplit("=", 1)
            if not name or name in schemas:
                raise ValueError
            version = int(raw_version)
            if version < 1:
                raise ValueError
            schemas[name] = version
    except ValueError as exc:
        raise ArtifactError(
            "Schema must use a unique NAME=POSITIVE_VERSION value"
        ) from exc
    return schemas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify immutable Site Artifact v2 metadata."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--artifact-root", type=Path, required=True)
    build.add_argument("--release-index", type=Path, required=True)
    build.add_argument("--package-lock", type=Path, required=True)
    build.add_argument("--media-index", type=Path, required=True)
    build.add_argument("--schema", action="append", default=[])
    build.add_argument("--site-release-id", required=True)
    build.add_argument("--git-commit", required=True)
    build.add_argument("--docker-image", required=True)
    build.add_argument("--built-at", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--artifact-root", type=Path, required=True)
    verify.add_argument("--expected-git-commit")
    verify.add_argument("--package-lock", type=Path)
    verify.add_argument("--release-index", type=Path)
    verify.add_argument("--schema", action="append", default=[])
    verify.add_argument("--print-site-release-id", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            identity = build_artifact(
                artifact_root=args.artifact_root,
                release_index=args.release_index,
                package_lock=args.package_lock,
                media_index=args.media_index,
                schemas=_parse_schemas(args.schema, args.media_index),
                site_release_id=args.site_release_id,
                git_commit=args.git_commit,
                docker_image=args.docker_image,
                built_at=args.built_at,
            )
        else:
            raw_identity = _require_v2_identity(
                _load_json(
                    args.artifact_root / RELEASE_MANIFEST,
                    "release manifest",
                )
            )
            media = raw_identity["media"]
            assert isinstance(media, dict)
            media_index = args.artifact_root / str(media["indexPath"])
            identity = verify_artifact(
                args.artifact_root,
                expected_git_commit=args.expected_git_commit,
                package_lock=args.package_lock,
                release_index=args.release_index,
                expected_schemas=_parse_schemas(args.schema, media_index),
            )
    except (ArtifactError, OSError) as exc:
        print(f"Site Artifact failed: {exc}", file=sys.stderr)
        return 1

    if args.command == "build" or not args.print_site_release_id:
        print(f"Verified Site Artifact: {identity['siteReleaseId']}")
    else:
        print(identity["siteReleaseId"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
