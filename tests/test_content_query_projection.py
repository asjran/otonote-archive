"""T2 tests for query projection publishing.

Each test prepares an isolated ``releases/<region>/<channel>/<id>``
candidate, runs ``query_projection.publish_query_projections`` against it,
and asserts the on-disk contract from design §5.1:

- ``query/events.json``, ``query/gacha-pools.json`` and ``query/shops.json``
  belong to the same Release directory and are recorded in
  ``manifest.queryDatasets``;
- writing is atomic (``.part`` + ``fsync`` + ``os.replace``);
- any failure leaves ``current.json`` untouched and the candidate dir clean.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.contracts import (  # noqa: E402
    Availability,
    Dataset,
    Freshness,
    Provenance,
)
from tools.resource_pipeline.models import (  # noqa: E402
    Channel,
    ClientBuild,
    ContentRelease,
    Region,
    VersionVector,
)
from tools.resource_pipeline.query_projection import (  # noqa: E402
    DatasetDescriptor,
    QueryProjectionError,
    build_query_projections,
    publish_query_projections,
)
from tools.resource_pipeline.release_repository import (  # noqa: E402
    ReleaseRepository,
)


def _release(catalog_hash: str, region: Region = Region.GLOBAL, channel: Channel = Channel.PRODUCTION) -> ContentRelease:
    build = ClientBuild(
        region=region,
        channel=channel,
        platform="android",
        package_name="com.example.fixture",
        version_name="1.0.0",
        version_code=1,
        package_sha256="a" * 64,
        unity_version="6000.3.12f1",
        client_generation="fixture-v1",
        auth_profile_ref="fixture-auth",
    )
    return ContentRelease.for_client_build(
        build,
        VersionVector(
            client_version="1.0.0+1",
            minimum_client_version=None,
            bootstrap_revision="bootstrap-1",
            catalog_hash=catalog_hash,
            master_version="master-1",
            asset_manifest_version=None,
            remote_code_hash=None,
        ),
    )


def _write_master(root: Path, tables: dict[str, list[dict]]) -> None:
    for name, rows in tables.items():
        (root / f"{name}.json").write_text(
            json.dumps({"_allData": rows}),
            encoding="utf-8",
        )


class BuildQueryProjectionsTest(unittest.TestCase):
    def test_baseline_master_without_events_returns_unavailable(self) -> None:
        # The plan explicitly forbids guessing event content when no real
        # ``MasterEvent`` rows exist. The projection must instead be an
        # honest unavailable envelope with provenance ``configured``.
        with tempfile.TemporaryDirectory() as temporary:
            master = Path(temporary) / "master"
            master.mkdir()

            projections = build_query_projections(master, "fixture-release")

            events = projections[Dataset.EVENTS]
            self.assertEqual(events["dataset"], "events")
            self.assertEqual(events["availability"], Availability.UNAVAILABLE.value)
            self.assertEqual(events["freshness"], Freshness.UNKNOWN.value)
            self.assertEqual(events["provenance"], Provenance.CONFIGURED.value)
            self.assertEqual(events["items"], [])
            self.assertTrue(events["warnings"])

    def test_gacha_pools_and_shops_are_unverified_for_baseline(self) -> None:
        # Design §5.1 + plan step 5: no verified mapping exists for gacha /
        # shops yet, so they MUST come back as ``unavailable`` with the
        # ``source_mapping_unverified`` warning.
        with tempfile.TemporaryDirectory() as temporary:
            master = Path(temporary) / "master"
            master.mkdir()

            projections = build_query_projections(master, "fixture-release")

            for dataset in (Dataset.GACHA_POOLS, Dataset.SHOPS):
                payload = projections[dataset]
                self.assertEqual(payload["availability"], Availability.UNAVAILABLE.value)
                self.assertEqual(payload["freshness"], Freshness.UNKNOWN.value)
                self.assertEqual(payload["provenance"], Provenance.UNKNOWN.value)
                self.assertEqual(payload["items"], [])
                codes = [warning["code"] for warning in payload["warnings"]]
                self.assertIn("source_mapping_unverified", codes)

    def test_known_event_row_with_unverified_schema_stays_unavailable(self) -> None:
        # A ``MasterEvent`` row is present but its field semantics are not
        # yet proven. The projection must NOT emit a fake "active" item —
        # the events gate (G1) is what authorizes that.
        with tempfile.TemporaryDirectory() as temporary:
            master = Path(temporary) / "master"
            master.mkdir()
            _write_master(master, {"MasterEvent": [{"_id": 1, "_eventId": 100}]})

            events = build_query_projections(master, "fixture-release")[Dataset.EVENTS]

            self.assertEqual(events["availability"], Availability.UNAVAILABLE.value)
            self.assertEqual(events["items"], [])


class PublishQueryProjectionsTest(unittest.TestCase):
    def test_writes_three_query_files_inside_release_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("catalog-fixture")
            repository.create_candidate(release, {"objects": []})
            payloads = build_query_projections(Path(temporary) / "master-unused", release.id)

            descriptors = publish_query_projections(repository, release, payloads)

            release_dir = (
                root
                / "content"
                / "releases"
                / release.region.value
                / release.channel.value
                / release.id
            )
            for dataset, expected_name in (
                (Dataset.EVENTS, "events.json"),
                (Dataset.GACHA_POOLS, "gacha-pools.json"),
                (Dataset.SHOPS, "shops.json"),
            ):
                path = release_dir / "query" / expected_name
                self.assertTrue(path.is_file(), msg=f"missing {path}")
                descriptor = next(item for item in descriptors if item.dataset == dataset)
                self.assertEqual(descriptor.path, f"query/{expected_name}")
                actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(actual_hash, descriptor.sha256)
                self.assertGreaterEqual(descriptor.dataset_schema_version, 1)

    def test_manifest_queryDatasets_records_each_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("catalog-manifest")
            repository.create_candidate(release, {"objects": []})
            payloads = build_query_projections(Path(temporary) / "master-unused", release.id)

            descriptors = publish_query_projections(repository, release, payloads)

            manifest_path = (
                root
                / "content"
                / "releases"
                / release.region.value
                / release.channel.value
                / release.id
                / "manifest.json"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            recorded = manifest["queryDatasets"]
            self.assertEqual(len(recorded), 3)
            for descriptor in descriptors:
                self.assertIn(
                    {
                        "path": descriptor.path,
                        "dataset": descriptor.dataset.value,
                        "datasetSchemaVersion": descriptor.dataset_schema_version,
                        "sha256": descriptor.sha256,
                    },
                    recorded,
                )

    def test_publish_is_atomic_and_does_not_leave_part_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("catalog-atomic")
            repository.create_candidate(release, {"objects": []})
            payloads = build_query_projections(Path(temporary) / "master-unused", release.id)

            publish_query_projections(repository, release, payloads)

            release_dir = (
                root
                / "content"
                / "releases"
                / release.region.value
                / release.channel.value
                / release.id
            )
            for path in release_dir.rglob("*.part"):
                self.fail(f"atomic write left part file behind: {path}")

    def test_publish_records_descriptors_in_stable_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("catalog-order")
            repository.create_candidate(release, {"objects": []})
            payloads = build_query_projections(Path(temporary) / "master-unused", release.id)

            first = publish_query_projections(repository, release, payloads)
            second = publish_query_projections(repository, release, payloads)

            self.assertEqual([item.dataset for item in first], [item.dataset for item in second])
            self.assertEqual([item.path for item in first], [item.path for item in second])

    def test_publish_failure_does_not_advance_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("catalog-failure")

            with self.assertRaises(QueryProjectionError):
                publish_query_projections(
                    repository,
                    release,
                    {Dataset.EVENTS: {"dataset": "events", "items": []}},
                )

            manifest_path = (
                root
                / "content"
                / "releases"
                / release.region.value
                / release.channel.value
                / release.id
                / "manifest.json"
            )
            self.assertFalse(manifest_path.exists())
            self.assertIsNone(repository.current_release_id(release.region, release.channel))

    def test_payload_dataset_must_match_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("catalog-mismatch")
            repository.create_candidate(release, {"objects": []})

            with self.assertRaises(QueryProjectionError):
                publish_query_projections(
                    repository,
                    release,
                    {Dataset.EVENTS: {"dataset": "gacha-pools", "items": []}},
                )


class ReleaseRegionIsolationTest(unittest.TestCase):
    def test_production_and_staging_release_directories_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            jp = _release("staging-cat", Region.GLOBAL, Channel.STAGING)
            global_release = _release("global-cat", Region.GLOBAL, Channel.PRODUCTION)
            repository.create_candidate(jp, {"objects": []})
            repository.create_candidate(global_release, {"objects": []})

            publish_query_projections(repository, jp, build_query_projections(Path(temporary) / "m", jp.id))
            publish_query_projections(repository, global_release, build_query_projections(Path(temporary) / "m", global_release.id))

            jp_dir = (
                root / "content/releases/global/staging" / jp.id / "query" / "events.json"
            )
            global_dir = (
                root
                / "content/releases/global/production"
                / global_release.id
                / "query"
                / "events.json"
            )
            self.assertTrue(jp_dir.is_file())
            self.assertTrue(global_dir.is_file())
            self.assertNotEqual(jp_dir.read_bytes(), global_dir.read_bytes())


class DescriptorShapeTest(unittest.TestCase):
    def test_descriptor_payload_round_trip(self) -> None:
        descriptor = DatasetDescriptor(
            dataset=Dataset.EVENTS,
            path="query/events.json",
            dataset_schema_version=1,
            sha256="0" * 64,
        )
        payload = descriptor.to_dict()
        rebuilt = DatasetDescriptor.from_dict(payload)
        self.assertEqual(rebuilt, descriptor)
        self.assertEqual(rebuilt.to_dict(), payload)


if __name__ == "__main__":
    unittest.main()