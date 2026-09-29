"""Atomic SiteRelease publication coordinated with ContentRelease pointers."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import Channel, Region
from .release_repository import ReleaseRepository
from ..site_artifact import ArtifactError, verify_artifact


class PublishError(RuntimeError):
    """Raised when a candidate SiteRelease cannot become current safely."""


@dataclass(frozen=True)
class ContentReleaseRef:
    region: Region
    channel: Channel
    id: str

    def __post_init__(self) -> None:
        prefix = f"{self.region.value}-{self.channel.value}-"
        if not isinstance(self.id, str) or not self.id.startswith(
            prefix
        ) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]*", self.id
        ):
            raise ValueError("ContentReleaseRef identity does not match its server")

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "region": self.region.value,
            "channel": self.channel.value,
        }


@dataclass(frozen=True)
class SiteRelease:
    id: str
    content_releases: tuple[ContentReleaseRef, ...]
    git_commit: str
    docker_image: str
    built_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]*", self.id
        ):
            raise ValueError("SiteRelease id must be path-safe")
        if not self.content_releases:
            raise ValueError("SiteRelease must reference at least one ContentRelease")
        server_keys = [
            (item.region, item.channel) for item in self.content_releases
        ]
        if len(server_keys) != len(set(server_keys)):
            raise ValueError("SiteRelease contains duplicate server references")
        if not isinstance(self.git_commit, str) or not re.fullmatch(
            r"[0-9a-f]{7,64}", self.git_commit
        ):
            raise ValueError("git_commit must be a hexadecimal commit id")
        if not isinstance(self.docker_image, str) or not self.docker_image.strip():
            raise ValueError("docker_image cannot be empty")
        if not isinstance(self.built_at, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z",
            self.built_at,
        ):
            raise ValueError("built_at must be a UTC ISO-8601 timestamp")

    def to_manifest(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "siteRelease": {
                "id": self.id,
                "contentReleases": [
                    item.to_dict() for item in self.content_releases
                ],
                "gitCommit": self.git_commit,
                "dockerImage": self.docker_image,
                "builtAt": self.built_at,
            },
        }

    @classmethod
    def from_manifest(cls, value: object) -> "SiteRelease":
        try:
            if not isinstance(value, dict):
                raise TypeError("manifest must be an object")
            if value.get("schemaVersion") == 2:
                root = {
                    "id": value["siteReleaseId"],
                    "contentReleases": value["contentReleases"],
                    "gitCommit": value["gitCommit"],
                    "dockerImage": value["dockerImage"],
                    "builtAt": value["builtAt"],
                }
            else:
                root = value["siteRelease"]
            references = tuple(
                ContentReleaseRef(
                    region=Region(item["region"]),
                    channel=Channel(item["channel"]),
                    id=item["id"],
                )
                for item in root["contentReleases"]
            )
            return cls(
                id=root["id"],
                content_releases=references,
                git_commit=root["gitCommit"],
                docker_image=root["dockerImage"],
                built_at=root["builtAt"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PublishError("SiteRelease manifest is invalid") from exc

    @classmethod
    def from_release_index(
        cls,
        *,
        site_release_id: str,
        release_index: object,
        git_commit: str,
        docker_image: str,
        built_at: str,
    ) -> "SiteRelease":
        if not isinstance(release_index, dict):
            raise PublishError("release index must be an object")
        projections = release_index.get("projections")
        if release_index.get("schemaVersion") != 1 or not isinstance(
            projections, list
        ):
            raise PublishError("release index contract is invalid")
        by_server: dict[tuple[Region, Channel], ContentReleaseRef] = {}
        try:
            for item in projections:
                if not isinstance(item, dict):
                    raise ValueError("projection must be an object")
                reference = ContentReleaseRef(
                    region=Region(item["region"]),
                    channel=Channel(item["channel"]),
                    id=item["contentReleaseId"],
                )
                key = (reference.region, reference.channel)
                previous = by_server.get(key)
                if previous is not None and previous.id != reference.id:
                    raise ValueError(
                        "one server maps to multiple ContentReleases"
                    )
                by_server[key] = reference
        except (KeyError, TypeError, ValueError) as exc:
            raise PublishError("release index projection is invalid") from exc
        return cls(
            id=site_release_id,
            content_releases=tuple(
                sorted(
                    by_server.values(),
                    key=lambda item: (
                        item.region.value,
                        item.channel.value,
                        item.id,
                    ),
                )
            ),
            git_commit=git_commit,
            docker_image=docker_image,
            built_at=built_at,
        )


HealthCheck = Callable[[Path], bool]


class ContentPublisher:
    """Publish a complete site and its content pointers as one operation."""

    def __init__(
        self,
        *,
        site_root: Path,
        content_repository: ReleaseRepository,
    ):
        self._site_root = site_root
        self._release_root = site_root / "releases"
        self._content_repository = content_repository

    def publish(
        self,
        candidate_root: Path,
        release: SiteRelease,
        *,
        static_check: HealthCheck,
        health_check: HealthCheck,
    ) -> Path:
        if candidate_root.is_symlink():
            raise PublishError("private object symlinks are forbidden in web root")
        candidate_root = candidate_root.resolve()
        if not candidate_root.is_dir() or not (
            candidate_root / "index.html"
        ).is_file():
            raise PublishError("candidate SiteRelease is missing index.html")
        preserve_v2_identity = False
        candidate_manifest = candidate_root / ".release.json"
        if candidate_manifest.is_file():
            try:
                candidate_value = json.loads(
                    candidate_manifest.read_text(encoding="utf-8")
                )
                if (
                    isinstance(candidate_value, dict)
                    and candidate_value.get("schemaVersion") == 2
                ):
                    verify_artifact(
                        candidate_root,
                        expected_git_commit=release.git_commit,
                    )
                    if SiteRelease.from_manifest(candidate_value) != release:
                        raise PublishError(
                            "candidate SiteRelease identity does not match publish request"
                        )
                    preserve_v2_identity = True
            except (OSError, json.JSONDecodeError, ArtifactError) as exc:
                raise PublishError(
                    f"candidate SiteRelease artifact is invalid: {exc}"
                ) from exc
        self._validate_public_tree(candidate_root)
        if not static_check(candidate_root):
            raise PublishError("candidate SiteRelease failed its static check")

        destination = self._release_root / release.id
        if destination.exists():
            raise PublishError(f"SiteRelease already exists: {release.id}")
        self._release_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(candidate_root, destination)
        if not preserve_v2_identity:
            (destination / ".release.json").write_text(
                json.dumps(
                    release.to_manifest(),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

        old_current = self._target("current")
        old_previous = self._target("previous")
        self._switch(release.id, old_current)
        if not health_check(self._site_root / "current"):
            self._restore_site_pointers(old_current, old_previous)
            raise PublishError("published SiteRelease failed its health check")

        try:
            self._content_repository.publish_candidates_atomically(
                (
                    (content.region, content.channel, content.id)
                    for content in release.content_releases
                )
            )
        except Exception as exc:
            self._restore_site_pointers(old_current, old_previous)
            raise PublishError(
                "ContentRelease pointer update failed after site activation"
            ) from exc
        return destination

    @staticmethod
    def _validate_public_tree(candidate_root: Path) -> None:
        forbidden_names = {
            "phone_dump",
            "private",
            "secrets",
            ".env",
        }
        forbidden_suffixes = {
            ".apk",
            ".credentials",
            ".secret",
        }
        for path in candidate_root.rglob("*"):
            relative = path.relative_to(candidate_root)
            lowered_parts = {part.lower() for part in relative.parts}
            if (
                forbidden_names.intersection(lowered_parts)
                or path.suffix.lower() in forbidden_suffixes
            ):
                raise PublishError(
                    f"private object is forbidden in web root: {relative}"
                )
            if path.is_symlink():
                try:
                    path.resolve(strict=True).relative_to(candidate_root)
                except (OSError, ValueError) as exc:
                    raise PublishError(
                        f"private object is forbidden in web root: {relative}"
                    ) from exc

    def rollback(self, *, health_check: HealthCheck) -> Path:
        current_target = self._target("current")
        previous_target = self._target("previous")
        if current_target is None or previous_target is None:
            raise PublishError("no previous SiteRelease is available")
        previous_root = (self._site_root / previous_target).resolve()
        try:
            previous_root.relative_to(self._release_root.resolve())
        except ValueError as exc:
            raise PublishError("previous SiteRelease points outside release root") from exc
        try:
            manifest_value = json.loads(
                (previous_root / ".release.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise PublishError("previous SiteRelease manifest is unreadable") from exc
        release = SiteRelease.from_manifest(manifest_value)
        if release.id != previous_root.name:
            raise PublishError("previous SiteRelease manifest identity is invalid")

        self._replace_link("current", previous_target)
        self._replace_link("previous", current_target)
        if not health_check(self._site_root / "current"):
            self._replace_link("current", current_target)
            self._replace_link("previous", previous_target)
            raise PublishError("rollback target failed its health check")
        try:
            self._content_repository.publish_candidates_atomically(
                (
                    (content.region, content.channel, content.id)
                    for content in release.content_releases
                )
            )
        except Exception as exc:
            self._replace_link("current", current_target)
            self._replace_link("previous", previous_target)
            raise PublishError(
                "ContentRelease pointer update failed during rollback"
            ) from exc
        return previous_root

    def _target(self, name: str) -> str | None:
        path = self._site_root / name
        return os.readlink(path) if path.is_symlink() else None

    def _replace_link(self, name: str, target: str | None) -> None:
        path = self._site_root / name
        temporary = self._site_root / f".{name}.next"
        self._site_root.mkdir(parents=True, exist_ok=True)
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        if target is None:
            if path.exists() or path.is_symlink():
                path.unlink()
            return
        temporary.symlink_to(target)
        os.replace(temporary, path)

    def _switch(self, release_id: str, old_current: str | None) -> None:
        if old_current is not None:
            self._replace_link("previous", old_current)
        self._replace_link("current", f"releases/{release_id}")

    def _restore_site_pointers(
        self,
        old_current: str | None,
        old_previous: str | None,
    ) -> None:
        self._replace_link("current", old_current)
        self._replace_link("previous", old_previous)


def write_site_release_manifest(release: SiteRelease, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.next")
    temporary.write_text(
        json.dumps(
            release.to_manifest(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage atomic SiteReleases.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--release-index", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--site-release-id", required=True)
    manifest.add_argument("--git-commit", required=True)
    manifest.add_argument("--docker-image", required=True)
    manifest.add_argument("--built-at", required=True)
    args = parser.parse_args(argv)

    try:
        release_index = json.loads(
            args.release_index.read_text(encoding="utf-8")
        )
        release = SiteRelease.from_release_index(
            site_release_id=args.site_release_id,
            release_index=release_index,
            git_commit=args.git_commit,
            docker_image=args.docker_image,
            built_at=args.built_at,
        )
        write_site_release_manifest(release, args.output)
    except (OSError, json.JSONDecodeError, PublishError, ValueError) as exc:
        print(f"SiteRelease manifest failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
