"""Immutable ContentRelease manifests stored by server identity."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .models import Channel, ContentRelease, Region


# Reserved manifest keys. ``queryDatasets`` is set explicitly via the
# ``query_datasets`` keyword on ``create_candidate`` so the publisher can
# never accidentally overwrite the recorded dataset hashes.
_RESERVED_MANIFEST_KEYS = {"schemaVersion", "contentRelease", "status", "queryDatasets"}


class ReleaseRepositoryError(RuntimeError):
    """Raised when a release manifest would violate repository invariants."""


class ReleaseRepository:
    def __init__(self, data_root: Path):
        self.release_root = data_root / "releases"

    def manifest_path(
        self,
        region: Region,
        channel: Channel,
        content_release_id: str,
    ) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", content_release_id):
            raise ValueError("content_release_id must be a path-safe identifier")
        expected_prefix = f"{region.value}-{channel.value}-"
        if not content_release_id.startswith(expected_prefix):
            raise ValueError(
                "content_release_id must belong to "
                f"{region.value}/{channel.value}"
            )
        return (
            self.release_root
            / region.value
            / channel.value
            / content_release_id
            / "manifest.json"
        )

    def create_candidate(
        self,
        release: ContentRelease,
        payload: Mapping[str, Any],
        *,
        query_datasets: Sequence[Mapping[str, Any]] = (),
    ) -> Path:
        reserved = _RESERVED_MANIFEST_KEYS
        conflicts = reserved.intersection(payload)
        if conflicts:
            raise ReleaseRepositoryError(
                f"release payload contains reserved fields: {sorted(conflicts)}"
            )
        path = self.manifest_path(release.region, release.channel, release.id)
        if path.exists():
            raise ReleaseRepositoryError(
                f"release manifest already exists: {release.id}"
            )

        normalized_query_datasets: list[dict[str, Any]] = []
        for descriptor in query_datasets:
            if not isinstance(descriptor, Mapping):
                raise ReleaseRepositoryError(
                    "query_datasets entries must be mappings"
                )
            for key in ("path", "dataset", "datasetSchemaVersion", "sha256"):
                if key not in descriptor:
                    raise ReleaseRepositoryError(
                        f"query_datasets entry missing {key!r}"
                    )
            normalized_query_datasets.append(
                {
                    "path": str(descriptor["path"]),
                    "dataset": str(descriptor["dataset"]),
                    "datasetSchemaVersion": int(descriptor["datasetSchemaVersion"]),
                    "sha256": str(descriptor["sha256"]),
                }
            )

        manifest = {
            "schemaVersion": 1,
            "contentRelease": {
                "id": release.id,
                "region": release.region.value,
                "channel": release.channel.value,
                "observedByClientBuildRef": (
                    release.observed_by_client_build_ref
                ),
                "versionVector": release.version_vector.as_canonical_dict(),
                "versionVectorHash": release.version_vector.fingerprint(),
            },
            "status": "candidate",
            "queryDatasets": normalized_query_datasets,
            **dict(payload),
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix="manifest-",
                suffix=".part",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                json.dump(
                    manifest,
                    output,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary_path, path)
            except FileExistsError as exc:
                raise ReleaseRepositoryError(
                    f"release manifest already exists: {release.id}"
                ) from exc
            temporary_path.unlink()
            temporary_path = None
            return path
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def load_manifest(
        self,
        region: Region,
        channel: Channel,
        content_release_id: str,
    ) -> dict[str, Any]:
        path = self.manifest_path(region, channel, content_release_id)
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ReleaseRepositoryError(f"release manifest is not an object: {path}")
        return value

    def publish_candidate(
        self,
        region: Region,
        channel: Channel,
        content_release_id: str,
    ) -> Path:
        return self.publish_candidates_atomically(
            ((region, channel, content_release_id),)
        )[0]

    def publish_candidates_atomically(
        self,
        candidates: Iterable[tuple[Region, Channel, str]],
    ) -> tuple[Path, ...]:
        """Advance multiple server pointers together, restoring all on error."""
        requests = tuple(candidates)
        if not requests:
            raise ReleaseRepositoryError("at least one candidate is required")
        server_keys = [(region, channel) for region, channel, _ in requests]
        if len(server_keys) != len(set(server_keys)):
            raise ReleaseRepositoryError("candidate batch contains duplicate servers")

        prepared: list[tuple[Path, dict[str, Any]]] = []
        for region, channel, content_release_id in requests:
            manifest_path = self.manifest_path(
                region,
                channel,
                content_release_id,
            )
            manifest = self.load_manifest(region, channel, content_release_id)
            content = manifest.get("contentRelease")
            if (
                not isinstance(content, dict)
                or content.get("id") != content_release_id
            ):
                raise ReleaseRepositoryError(
                    "candidate release identity is invalid"
                )
            if manifest.get("status") != "candidate":
                raise ReleaseRepositoryError(
                    "only candidate releases can be published"
                )
            pointer_path = (
                self.release_root
                / region.value
                / channel.value
                / "current.json"
            )
            prepared.append(
                (
                    pointer_path,
                    {
                        "schemaVersion": 1,
                        "contentReleaseId": content_release_id,
                        "manifestSha256": hashlib.sha256(
                            manifest_path.read_bytes()
                        ).hexdigest(),
                    },
                )
            )

        snapshots = {
            path: path.read_bytes() if path.exists() else None
            for path, _ in prepared
        }
        try:
            for path, payload in prepared:
                self._replace_pointer(path, payload)
        except Exception:
            for path, content in snapshots.items():
                if content is None:
                    if path.exists():
                        path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_name(f".{path.name}.restore")
                    temporary.write_bytes(content)
                    os.replace(temporary, path)
            raise
        return tuple(path for path, _ in prepared)

    @staticmethod
    def _replace_pointer(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix="current-",
                suffix=".part",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                json.dump(
                    payload,
                    output,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def update_manifest_query_datasets(
        self,
        region: Region,
        channel: Channel,
        content_release_id: str,
        descriptors: Sequence[Mapping[str, Any]],
    ) -> Path:
        """Atomically update the ``queryDatasets`` field on an existing manifest.

        The publisher calls this after writing ``query/<dataset>.json`` files
        so the manifest hash recorded in ``current.json`` reflects the
        complete ContentRelease bundle.
        """

        path = self.manifest_path(region, channel, content_release_id)
        if not path.is_file():
            raise ReleaseRepositoryError(
                f"release manifest missing: {path}"
            )
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ReleaseRepositoryError(
                f"release manifest is not an object: {path}"
            )
        normalized: list[dict[str, Any]] = []
        for descriptor in descriptors:
            if not isinstance(descriptor, Mapping):
                raise ReleaseRepositoryError(
                    "query dataset descriptors must be mappings"
                )
            for key in ("path", "dataset", "datasetSchemaVersion", "sha256"):
                if key not in descriptor:
                    raise ReleaseRepositoryError(
                        f"query dataset descriptor missing {key!r}"
                    )
            normalized.append(
                {
                    "path": str(descriptor["path"]),
                    "dataset": str(descriptor["dataset"]),
                    "datasetSchemaVersion": int(
                        descriptor["datasetSchemaVersion"]
                    ),
                    "sha256": str(descriptor["sha256"]),
                }
            )
        manifest["queryDatasets"] = normalized
        new_body = (
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix="manifest-",
                suffix=".part",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                output.write(new_body)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        return path

    def current_release_id(self, region: Region, channel: Channel) -> str | None:
        pointer_path = self.release_root / region.value / channel.value / "current.json"
        if not pointer_path.is_file():
            return None
        try:
            value = json.loads(pointer_path.read_text(encoding="utf-8"))
            release_id = value["contentReleaseId"]
            expected_hash = value["manifestSha256"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ReleaseRepositoryError("current release pointer is invalid") from error
        manifest_path = self.manifest_path(region, channel, release_id)
        if (
            not isinstance(expected_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
            or not manifest_path.is_file()
            or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != expected_hash
        ):
            raise ReleaseRepositoryError(
                "current release pointer failed integrity verification"
            )
        return release_id

    def load_current_release(
        self,
        region: Region,
        channel: Channel,
    ) -> tuple[str, dict[str, Any]] | None:
        """Return ``(contentReleaseId, manifest)`` after verifying the pointer.

        Returns ``None`` when there is no current release for the server.
        Raises :class:`ReleaseRepositoryError` if the pointer or manifest fails
        integrity verification.
        """

        pointer_path = self.release_root / region.value / channel.value / "current.json"
        if not pointer_path.is_file():
            return None
        try:
            value = json.loads(pointer_path.read_text(encoding="utf-8"))
            release_id = str(value["contentReleaseId"])
            expected_hash = str(value["manifestSha256"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ReleaseRepositoryError("current release pointer is invalid") from error
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise ReleaseRepositoryError(
                "current release pointer failed integrity verification"
            )
        manifest_path = self.manifest_path(region, channel, release_id)
        if not manifest_path.is_file():
            raise ReleaseRepositoryError(
                "current release pointer failed integrity verification"
            )
        actual_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ReleaseRepositoryError(
                "current release pointer failed integrity verification"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ReleaseRepositoryError("release manifest is not an object")
        content = manifest.get("contentRelease")
        if (
            not isinstance(content, dict)
            or content.get("id") != release_id
            or content.get("region") != region.value
            or content.get("channel") != channel.value
        ):
            raise ReleaseRepositoryError(
                "current release pointer failed identity verification"
            )
        return release_id, manifest
