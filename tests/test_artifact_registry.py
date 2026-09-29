from __future__ import annotations

import unittest

from tools.artifact_registry import (
    ArtifactValidationError,
    schema_versions,
    validate_artifact,
)


class ArtifactRegistryTest(unittest.TestCase):
    @staticmethod
    def catalog() -> dict[str, object]:
        return {
            "schemaVersion": 6,
            "generatedAt": "2026-07-26T00:00:00+00:00",
            "release": {
                "id": "release-1",
                "region": "global",
                "channel": "staging",
                "locale": "zh-CN",
            },
            "projectionContext": {
                "contentReleaseId": "release-1",
                "region": "global",
                "channel": "staging",
                "locale": "zh-CN",
            },
            "bands": [],
            "characters": [],
            "memberCards": [],
            "supportCards": [],
            "musicTracks": [],
            "assets": [],
        }

    def test_exposes_current_versions_by_published_artifact_path(self) -> None:
        self.assertEqual(
            schema_versions(),
            {
                "catalog.json": 6,
                "database-shards/manifest.json": 1,
                "release-index.json": 1,
                "story-resources.json": 2,
            },
        )

    def test_accepts_a_catalog_v6_projection(self) -> None:
        catalog = self.catalog()

        self.assertIs(validate_artifact("catalog.json", catalog), catalog)

    def test_rejects_catalog_without_a_required_collection(self) -> None:
        catalog = self.catalog()
        del catalog["assets"]

        with self.assertRaisesRegex(
            ArtifactValidationError,
            r"catalog\.json: assets must be an array",
        ):
            validate_artifact("catalog.json", catalog)

    def test_rejects_catalog_with_a_mismatched_projection_identity(self) -> None:
        catalog = self.catalog()
        projection_context = catalog["projectionContext"]
        assert isinstance(projection_context, dict)
        projection_context["contentReleaseId"] = "release-2"

        with self.assertRaisesRegex(
            ArtifactValidationError,
            r"catalog\.json: projectionContext must match release identity",
        ):
            validate_artifact("catalog.json", catalog)

    def test_accepts_a_story_resources_v2_index(self) -> None:
        story_resources = {
            "schemaVersion": 2,
            "sourceReleaseId": "release-1",
            "source": {"storageScope": "connected_device_snapshot"},
            "summary": {
                "total": 1,
                "byKind": {"adv_bgm": 1},
                "byBrowserState": {"available": 1},
            },
            "resources": [
                {
                    "id": "story-resource-1",
                    "kind": "adv_bgm",
                    "browserState": "available",
                    "sourceReleaseId": "release-1",
                }
            ],
        }

        self.assertIs(
            validate_artifact("story-resources.json", story_resources),
            story_resources,
        )

    def test_rejects_story_resources_with_an_incorrect_total(self) -> None:
        story_resources = {
            "schemaVersion": 2,
            "sourceReleaseId": "release-1",
            "source": {},
            "summary": {
                "total": 2,
                "byKind": {},
                "byBrowserState": {},
            },
            "resources": [],
        }

        with self.assertRaisesRegex(
            ArtifactValidationError,
            r"story-resources\.json: summary\.total must equal resources length",
        ):
            validate_artifact("story-resources.json", story_resources)

    def test_rejects_release_index_when_active_projection_is_missing(self) -> None:
        release_index = {
            "schemaVersion": 1,
            "active": {
                "contentReleaseId": "release-2",
                "region": "global",
                "channel": "staging",
                "locale": "zh-CN",
                "catalogPath": "/data/releases/release-2/zh-CN/catalog.json",
            },
            "projections": [
                {
                    "contentReleaseId": "release-1",
                    "region": "global",
                    "channel": "staging",
                    "locale": "zh-CN",
                    "catalogPath": "/data/releases/release-1/zh-CN/catalog.json",
                }
            ],
        }

        with self.assertRaisesRegex(
            ArtifactValidationError,
            r"release-index\.json: active projection is not in projections",
        ):
            validate_artifact("release-index.json", release_index)

    def test_rejects_database_manifest_with_an_incorrect_file_count(self) -> None:
        manifest = {
            "schemaVersion": 1,
            "contentReleaseId": "release-1",
            "fileCount": 2,
            "totalBytes": 10,
            "files": [
                {
                    "path": "items-index.json",
                    "kind": "item-index",
                    "recordCount": 1,
                    "sha256": "a" * 64,
                    "byteSize": 10,
                }
            ],
        }

        with self.assertRaisesRegex(
            ArtifactValidationError,
            r"database-shards/manifest\.json: fileCount must equal files length",
        ):
            validate_artifact("database-shards/manifest.json", manifest)


if __name__ == "__main__":
    unittest.main()
