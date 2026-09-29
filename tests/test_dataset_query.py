"""T2 tests for ``backend.query.DatasetQueryModule``.

The module reads ``releases/<region>/<channel>/current.json``, verifies the
manifest SHA-256 and each ``queryDatasets`` entry, applies locale fallback,
and returns a ``DatasetResult`` envelope. Rankings always come back as
``availability=unavailable`` with ``no_observation`` until the
ObservationRelease Repository is implemented in a later task.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend import query as backend_query  # noqa: E402
from backend.contracts import (  # noqa: E402
    Availability,
    Channel,
    Dataset,
    DatasetResult,
    Freshness,
    Locale,
    Provenance,
    QuerySpec,
    Region,
)
from backend.query import (  # noqa: E402
    DatasetIntegrityError,
    DatasetQueryModule,
)
from tools.resource_pipeline.models import (  # noqa: E402
    Channel as ModelChannel,
    ClientBuild,
    ContentRelease,
    Region as ModelRegion,
    VersionVector,
)
from tools.resource_pipeline.query_projection import (  # noqa: E402
    build_query_projections,
    publish_query_projections,
)
from tools.resource_pipeline.release_repository import (  # noqa: E402
    ReleaseRepository,
)


def _release(catalog_hash: str, region: ModelRegion, channel: ModelChannel) -> ContentRelease:
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


def _publish_release(
    repository: ReleaseRepository,
    release: ContentRelease,
    *,
    event_items: list[dict] | None = None,
) -> Path:
    payloads = build_query_projections(Path("/nonexistent-master"), release.id)
    if event_items is not None:
        payloads[Dataset.EVENTS] = {
            "dataset": "events",
            "datasetSchemaVersion": 1,
            "availability": "available",
            "freshness": "fresh",
            "provenance": "configured",
            "warnings": [],
            "items": event_items,
        }
    repository.create_candidate(release, {"objects": []})
    publish_query_projections(repository, release, payloads)
    repository.publish_candidate(release.region, release.channel, release.id)
    return (
        repository.release_root
        / release.region.value
        / release.channel.value
        / release.id
    )


class DatasetQueryModuleResolutionTest(unittest.TestCase):
    def test_resolves_current_pointer_per_region_and_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("catalog-q", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(repository, release)

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
            )

            result = module.query(Dataset.EVENTS, spec)

            self.assertIsInstance(result, DatasetResult)
            self.assertEqual(result.dataset, Dataset.EVENTS)
            self.assertEqual(result.query.region, "global")
            self.assertEqual(result.query.channel, "production")
            self.assertEqual(result.query.locale, "ja")

    def test_rankings_returns_unavailable_with_no_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("catalog-rank", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(repository, release)

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
            )

            result = module.query(Dataset.RANKINGS, spec)

            self.assertEqual(result.availability, Availability.UNAVAILABLE)
            self.assertEqual(result.freshness, Freshness.UNKNOWN)
            self.assertEqual(result.provenance, Provenance.UNKNOWN)
            self.assertEqual(result.items, ())
            self.assertTrue(result.warnings)
            self.assertEqual(result.warnings[0].code, "no_observation")

    def test_no_pointer_returns_unavailable_with_no_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content" / "releases")
            # Nothing published; no current.json anywhere.
            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
            )

            result = module.query(Dataset.EVENTS, spec)

            self.assertEqual(result.availability, Availability.UNAVAILABLE)
            self.assertTrue(result.warnings)
            codes = [warning.code for warning in result.warnings]
            self.assertIn("no_current_release", codes)

    def test_region_channel_pair_without_release_returns_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            # Publish production, then ask for staging.
            release = _release("production-only", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(repository, release)

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.STAGING,
                locale=Locale.EN,
            )

            result = module.query(Dataset.EVENTS, spec)

            self.assertEqual(result.availability, Availability.UNAVAILABLE)
            codes = [warning.code for warning in result.warnings]
            self.assertIn("no_current_release", codes)


class DatasetQueryModuleIntegrityTest(unittest.TestCase):
    def test_manifest_tamper_raises_integrity_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("catalog-tamper", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(repository, release)

            manifest_path = (
                repository.release_root
                / release.region.value
                / release.channel.value
                / release.id
                / "manifest.json"
            )
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["contentRelease"]["id"] = "different-id"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
            )

            with self.assertRaises(DatasetIntegrityError):
                module.query(Dataset.EVENTS, spec)

    def test_dataset_tamper_raises_integrity_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("catalog-dataset-tamper", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(repository, release)

            dataset_path = (
                repository.release_root
                / release.region.value
                / release.channel.value
                / release.id
                / "query"
                / "events.json"
            )
            payload = json.loads(dataset_path.read_text(encoding="utf-8"))
            payload["items"] = [{"eventId": "forged", "localizedText": {"ja": "x"}}]
            dataset_path.write_text(json.dumps(payload), encoding="utf-8")

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
            )

            with self.assertRaises(DatasetIntegrityError):
                module.query(Dataset.EVENTS, spec)

    def test_missing_query_dataset_entry_raises_integrity_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("catalog-missing", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(repository, release)

            manifest_path = (
                repository.release_root
                / release.region.value
                / release.channel.value
                / release.id
                / "manifest.json"
            )
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["queryDatasets"] = [
                entry for entry in payload["queryDatasets"] if entry.get("dataset") != "events"
            ]
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
            )

            with self.assertRaises(DatasetIntegrityError):
                module.query(Dataset.EVENTS, spec)


class LocaleFallbackTest(unittest.TestCase):
    def test_falls_back_to_region_default_locale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("jp-fallback", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(
                repository,
                release,
                event_items=[
                    {
                        "eventId": "event-fb",
                        "localizedText": {"ja": "日本語"},
                        "startAt": "2026-08-01T00:00:00Z",
                        "endAt": "2026-08-15T23:59:59Z",
                        "state": "active",
                        "rankingAvailable": False,
                        "sourceRef": "0" * 64,
                    }
                ],
            )

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.ZH_CN,
            )

            result = module.query(Dataset.EVENTS, spec)
            self.assertEqual(result.items[0]["localizedText"], "日本語")
            codes = [warning.code for warning in result.warnings]
            self.assertIn("locale_fallback", codes)

    def test_global_default_locale_is_en(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("global-fallback", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(
                repository,
                release,
                event_items=[
                    {
                        "eventId": "event-g",
                        "localizedText": {"en": "Sample"},
                        "startAt": "2026-08-01T00:00:00Z",
                        "endAt": "2026-08-15T23:59:59Z",
                        "state": "active",
                        "rankingAvailable": False,
                        "sourceRef": "0" * 64,
                    }
                ],
            )

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.ZH_CN,
            )

            result = module.query(Dataset.EVENTS, spec)
            self.assertEqual(result.items[0]["localizedText"], "Sample")

    def test_requested_locale_present_has_no_fallback_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("jp-direct", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(
                repository,
                release,
                event_items=[
                    {
                        "eventId": "event-direct",
                        "localizedText": {"ja": "日本語"},
                        "startAt": "2026-08-01T00:00:00Z",
                        "endAt": "2026-08-15T23:59:59Z",
                        "state": "active",
                        "rankingAvailable": False,
                        "sourceRef": "0" * 64,
                    }
                ],
            )

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
            )

            result = module.query(Dataset.EVENTS, spec)
            self.assertEqual(result.items[0]["localizedText"], "日本語")
            codes = [warning.code for warning in result.warnings]
            self.assertNotIn("locale_fallback", codes)


class LimitAndCursorTest(unittest.TestCase):
    def test_default_limit_is_twenty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("jp-limit", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            items = [
                {
                    "eventId": f"event-{index}",
                    "localizedText": {"ja": f"event-{index}"},
                    "startAt": "2026-08-01T00:00:00Z",
                    "endAt": "2026-08-15T23:59:59Z",
                    "state": "active",
                    "rankingAvailable": False,
                    "sourceRef": "0" * 64,
                }
                for index in range(25)
            ]
            _publish_release(repository, release, event_items=items)

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
            )

            result = module.query(Dataset.EVENTS, spec)
            self.assertEqual(len(result.items), 20)
            self.assertEqual(result.page.limit, 20)
            self.assertIsNotNone(result.page.next_cursor)

    def test_limit_clamped_to_one_hundred(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("jp-clamp", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(repository, release, event_items=[])

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
                limit=100,
            )

            result = module.query(Dataset.EVENTS, spec)
            self.assertEqual(result.page.limit, 100)

    def test_cursor_advances_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("jp-cursor", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            items = [
                {
                    "eventId": f"event-{index:02d}",
                    "localizedText": {"ja": f"event-{index:02d}"},
                    "startAt": "2026-08-01T00:00:00Z",
                    "endAt": "2026-08-15T23:59:59Z",
                    "state": "active",
                    "rankingAvailable": False,
                    "sourceRef": "0" * 64,
                }
                for index in range(10)
            ]
            _publish_release(repository, release, event_items=items)

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec_first = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
                limit=4,
            )
            first = module.query(Dataset.EVENTS, spec_first)
            self.assertEqual(len(first.items), 4)
            self.assertEqual([item["eventId"] for item in first.items],
                             ["event-00", "event-01", "event-02", "event-03"])
            self.assertIsNotNone(first.page.next_cursor)

            spec_next = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
                limit=4,
                cursor=first.page.next_cursor,
            )
            second = module.query(Dataset.EVENTS, spec_next)
            self.assertEqual(len(second.items), 4)
            self.assertEqual([item["eventId"] for item in second.items],
                             ["event-04", "event-05", "event-06", "event-07"])


class ResultEnvelopeTest(unittest.TestCase):
    def test_dataset_result_carries_release_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("jp-envelope", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(repository, release)

            module = DatasetQueryModule(release_root=root / "content" / "releases")
            spec = QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
            )

            result = module.query(Dataset.EVENTS, spec)

            self.assertEqual(result.release.content_release_id, release.id)
            self.assertEqual(result.dataset, Dataset.EVENTS)
            self.assertEqual(result.schema_version, 1)


if __name__ == "__main__":
    unittest.main()