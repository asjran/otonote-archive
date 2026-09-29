from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.database_shards import (
    DatabaseShardError,
    build_database_shards,
    validate_database_shard_tree,
    write_database_shards,
)


class DatabaseShardsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.database = {
            "schemaVersion": 1,
            "sourceReleaseId": "release-1",
            "skills": [
                {
                    "id": "live-skill-1",
                    "masterId": 1,
                    "kind": "live",
                    "name": "Skill",
                    "iconAssetId": "asset-1",
                    "iconStatus": "identified",
                    "publicationStatus": "public",
                    "publicationReason": "referenced_by_public_card",
                    "interpretationStatus": "identified",
                    "levels": [
                        {
                            "level": 1,
                            "renderedSummary": "Score up",
                            "effects": [
                                {
                                    "effectType": 1,
                                    "effectName": "Score",
                                    "targetIds": ["skill-target-1"],
                                    "conditionGroupId": 0,
                                    "releaseConditionGroupId": 0,
                                    "triggerConditionGroupId": 0,
                                    "cumulativeConditionId": 0,
                                }
                            ],
                        }
                    ],
                    "relatedCardIds": ["member-card-1"],
                }
            ],
            "items": [{"id": "item-1", "name": "Coin", "usages": []}],
            "growthProfiles": [{"id": "growth-1", "sourceCardIds": ["member-card-1"]}],
            "targets": [{"id": "skill-target-1"}],
            "conditions": [],
            "conditionGroups": [],
            "cumulativeConditions": [],
            "skillLevelResourceProfiles": [],
            "quality": {"skillCount": 1},
        }
        self.projections = {
            "schemaVersion": 1,
            "memberCards": [
                {
                    "cardId": "member-card-1",
                    "growthProfileId": "growth-1",
                    "skillRefs": [{"skillId": "live-skill-1"}],
                    "materialSummary": [],
                }
            ],
            "supportCards": [],
        }

    def test_builds_light_indexes_and_hashed_detail_shards(self) -> None:
        built = build_database_shards(
            self.database, self.projections, "release-1"
        )

        self.assertEqual(built.manifest["contentReleaseId"], "release-1")
        self.assertEqual(built.files["skills-index.json"]["recordCount"], 1)
        index = built.files["skills-index.json"]["records"][0]
        self.assertNotIn("levels", index)
        self.assertEqual(index["highestSummary"], "Score up")
        self.assertEqual(
            built.files["skills/live-skill-1.json"]["record"]["id"],
            "live-skill-1",
        )
        self.assertEqual(built.report["status"], "passed")

    def test_rejects_missing_skill_reference(self) -> None:
        self.projections["memberCards"][0]["skillRefs"][0]["skillId"] = "missing"

        with self.assertRaisesRegex(DatabaseShardError, "missing skill"):
            build_database_shards(
                self.database, self.projections, "release-1"
            )

    def test_writes_manifest_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = write_database_shards(
                self.database,
                self.projections,
                "release-1",
                root / "generated",
                root / "public",
                root / "report.json",
                additional_roots=(
                    root / "generated/releases/release-1/en/database-shards",
                    root / "public/releases/release-1/en/database-shards",
                ),
            )

            manifest = json.loads(
                (root / "generated/manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["status"], "passed")
            self.assertGreater(manifest["totalBytes"], 0)
            self.assertTrue((root / "public/items/item-1.json").is_file())
            self.assertTrue(
                (
                    root
                    / "generated/releases/release-1/en/database-shards"
                    / "items/item-1.json"
                ).is_file()
            )

            item_path = root / "public/items/item-1.json"
            value = json.loads(item_path.read_text(encoding="utf-8"))
            value["record"]["name"] = "Tampered"
            item_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(DatabaseShardError, "digest mismatch"):
                validate_database_shard_tree(root / "public", "release-1")


if __name__ == "__main__":
    unittest.main()
