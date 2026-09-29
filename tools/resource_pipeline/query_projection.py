"""Static query projections for ContentRelease.

Builds and publishes three JSON datasets (``events``, ``gacha-pools``,
``shops``) under each ContentRelease candidate and records their hashes in
``manifest.queryDatasets``. The on-disk format is a near-complete
``DatasetResult`` envelope so the runtime Query Module only needs to add
runtime metadata (region, channel, locale, current time) at query time.

All projection outputs are explicitly **unavailable** for the first phase:

- ``events``: real MasterEvent rows are required (gate G1). The baseline
  has no verified schema for ``startAt`` / ``endAt`` / ``localizedText`` so
  the projection carries an evidence-count warning instead of guessed
  items.
- ``gacha-pools`` / ``shops``: the Master mapping is not yet verified
  (gates G2 / G3). They come back as ``availability=unavailable`` with the
  ``source_mapping_unverified`` warning.
- ``rankings``: never stored here. The runtime module returns
  ``no_observation`` until the ObservationRelease Repository lands.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from backend.contracts import Availability, Dataset, Freshness, Provenance

from .models import Channel, ContentRelease, Region
from .release_repository import ReleaseRepository


class QueryProjectionError(RuntimeError):
    """Raised when query projection payload validation or publishing fails."""


_DATASET_FILE_NAMES: dict[Dataset, str] = {
    Dataset.EVENTS: "events.json",
    Dataset.GACHA_POOLS: "gacha-pools.json",
    Dataset.SHOPS: "shops.json",
}

# Stable publication order keeps manifest hashes deterministic.
_PUBLICATION_ORDER: tuple[Dataset, ...] = (
    Dataset.EVENTS,
    Dataset.GACHA_POOLS,
    Dataset.SHOPS,
)


@dataclass(frozen=True)
class DatasetDescriptor:
    dataset: Dataset
    path: str
    dataset_schema_version: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("DatasetDescriptor.path cannot be empty")
        if not isinstance(self.sha256, str) or len(self.sha256) != 64:
            raise ValueError(
                "DatasetDescriptor.sha256 must be a 64-character hex string"
            )
        if not isinstance(self.dataset_schema_version, int) or isinstance(
            self.dataset_schema_version, bool
        ):
            raise ValueError(
                "DatasetDescriptor.dataset_schema_version must be an integer"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "dataset": self.dataset.value,
            "datasetSchemaVersion": self.dataset_schema_version,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DatasetDescriptor":
        return cls(
            dataset=Dataset(value["dataset"]),
            path=str(value["path"]),
            dataset_schema_version=int(value["datasetSchemaVersion"]),
            sha256=str(value["sha256"]),
        )


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_query_projections(
    master_root: Path,
    release_id: str,
) -> dict[Dataset, dict[str, Any]]:
    """Build the three static query projection payloads for ``release_id``.

    ``master_root`` is the Master database root. It is used only to detect
    whether ``MasterEvent`` rows exist; their semantics are not yet trusted
    so the events projection is ``unavailable`` until gate G1 is approved.
    """

    has_event_rows = (master_root / "MasterEvent.json").is_file()
    return {
        Dataset.EVENTS: _build_events_payload(release_id, has_event_rows),
        Dataset.GACHA_POOLS: _build_unverified_payload(
            Dataset.GACHA_POOLS, release_id
        ),
        Dataset.SHOPS: _build_unverified_payload(Dataset.SHOPS, release_id),
    }


def _build_events_payload(
    release_id: str,
    has_event_rows: bool,
) -> dict[str, Any]:
    if has_event_rows:
        # MasterEvent rows exist but the field semantics are not yet
        # verified — gate G1 must approve the mapping before items can be
        # emitted. Returning ``configured`` provenance with explicit
        # ``event_definition_unverified`` warning communicates this clearly.
        return {
            "datasetSchemaVersion": 1,
            "dataset": Dataset.EVENTS.value,
            "availability": Availability.UNAVAILABLE.value,
            "freshness": Freshness.UNKNOWN.value,
            "provenance": Provenance.CONFIGURED.value,
            "warnings": [
                {
                    "code": "event_definition_unverified",
                    "message": (
                        "MasterEvent rows are present but their field "
                        "mapping is not yet verified; gate G1 must approve "
                        "before items can be exposed"
                    ),
                    "releaseId": release_id,
                }
            ],
            "items": [],
        }
    return {
        "datasetSchemaVersion": 1,
        "dataset": Dataset.EVENTS.value,
        "availability": Availability.UNAVAILABLE.value,
        "freshness": Freshness.UNKNOWN.value,
        "provenance": Provenance.CONFIGURED.value,
        "warnings": [
            {
                "code": "no_event_definitions",
                "message": "no MasterEvent rows in baseline; events route is empty",
                "releaseId": release_id,
            }
        ],
        "items": [],
    }


def _build_unverified_payload(
    dataset: Dataset, release_id: str
) -> dict[str, Any]:
    return {
        "datasetSchemaVersion": 1,
        "dataset": dataset.value,
        "availability": Availability.UNAVAILABLE.value,
        "freshness": Freshness.UNKNOWN.value,
        "provenance": Provenance.UNKNOWN.value,
        "warnings": [
            {
                "code": "source_mapping_unverified",
                "message": (
                    f"{dataset.value} Master mapping is not yet verified; "
                    "items will be exposed after the corresponding gate "
                    "is approved"
                ),
                "releaseId": release_id,
            }
        ],
        "items": [],
    }


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------


def publish_query_projections(
    repository: ReleaseRepository,
    release: ContentRelease,
    payloads: Mapping[Dataset, Mapping[str, Any]],
) -> list[DatasetDescriptor]:
    """Write each ``query/<dataset>.json`` file under the release directory.

    The publisher enforces that:

    - the release directory exists (created earlier by ``create_candidate``);
    - every payload matches its key (``payload.dataset == dataset.value``);
    - writing uses ``.part`` + ``flush`` + ``fsync`` + ``os.replace`` so a
      partial file never replaces a valid one;
    - descriptor hashes match the bytes that landed on disk.

    Returns the ordered list of :class:`DatasetDescriptor` instances for the
    manifest's ``queryDatasets`` field.
    """

    release_dir = _release_directory(repository, release.region, release.channel, release.id)
    if not release_dir.is_dir():
        raise QueryProjectionError(
            f"release directory does not exist: {release_dir}"
        )

    descriptors: list[DatasetDescriptor] = []
    for dataset in _PUBLICATION_ORDER:
        payload = payloads.get(dataset)
        if payload is None:
            raise QueryProjectionError(
                f"missing query projection payload for {dataset.value}"
            )
        _validate_payload(dataset, payload)
        descriptor = _write_dataset(release_dir, dataset, payload)
        descriptors.append(descriptor)

    repository.update_manifest_query_datasets(
        release.region,
        release.channel,
        release.id,
        [descriptor.to_dict() for descriptor in descriptors],
    )
    return descriptors


def _release_directory(
    repository: ReleaseRepository,
    region: Region,
    channel: Channel,
    content_release_id: str,
) -> Path:
    return (
        repository.release_root
        / region.value
        / channel.value
        / content_release_id
    )


def _validate_payload(dataset: Dataset, payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise QueryProjectionError(
            f"payload for {dataset.value} must be a mapping"
        )
    payload_dataset = payload.get("dataset")
    if payload_dataset != dataset.value:
        raise QueryProjectionError(
            f"payload.dataset {payload_dataset!r} does not match key {dataset.value!r}"
        )
    schema_version = payload.get("datasetSchemaVersion")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise QueryProjectionError(
            f"payload for {dataset.value} missing datasetSchemaVersion"
        )
    if schema_version < 1:
        raise QueryProjectionError(
            f"payload for {dataset.value} has invalid datasetSchemaVersion"
        )


def _write_dataset(
    release_dir: Path, dataset: Dataset, payload: Mapping[str, Any]
) -> DatasetDescriptor:
    query_dir = release_dir / "query"
    file_name = _DATASET_FILE_NAMES[dataset]
    target = query_dir / file_name
    body = json.dumps(
        dict(payload),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")

    query_dir.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=query_dir,
            prefix=f"{file_name}-",
            suffix=".part",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    return DatasetDescriptor(
        dataset=dataset,
        path=f"query/{file_name}",
        dataset_schema_version=int(payload["datasetSchemaVersion"]),
        sha256=sha256,
    )


__all__ = [
    "DatasetDescriptor",
    "QueryProjectionError",
    "build_query_projections",
    "publish_query_projections",
]